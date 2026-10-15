"""Pro self-check observations joined to the existing task/session state; no credentials."""
from contextvars import ContextVar
from urllib.parse import urlsplit
try:
    from .account_sessions import AccountSessions, own_account_id, safe_account_ref
except ImportError:
    from account_sessions import AccountSessions, own_account_id, safe_account_ref

SELF_ENDPOINTS = {'bili': ('api.bilibili.com', '/x/web-interface/nav'),
                  'xhs': ('edith.xiaohongshu.com', '/api/sns/web/v2/user/me')}


def self_proof(platform, response):
    """Only an exact official self response can prove the logged-in subject."""
    try:
        u = urlsplit(str(response.url))
        if u.scheme != 'https' or (u.hostname, u.path) != SELF_ENDPOINTS.get(platform) or u.username or u.password or u.port not in (None, 443):
            return 'check_failed', None
        if type(response.status_code) is not int or response.status_code != 200:
            return 'check_failed', None
        data = response.json()
        if not isinstance(data, dict):
            return 'check_failed', None
        if platform == 'bili':
            body = data.get('data')
            if type(data.get('code')) is not int:
                return 'check_failed', None
            if data.get('code') == -101 or (data.get('code') == 0 and isinstance(body, dict) and body.get('isLogin') is False):
                return 'logged_out', None
            if data.get('code') != 0 or not isinstance(body, dict) or body.get('isLogin') is not True:
                return 'check_failed', None
            uid = body.get('mid')
            if isinstance(uid, bool) or not str(uid).isdigit() or int(uid) <= 0:
                return 'check_failed', None
        elif platform == 'xhs':
            if data.get('code') == -100:
                return 'logged_out', None
            if data.get('success') is not True:
                return 'check_failed', None
            body = data.get('data')
            if not isinstance(body, dict) or body.get('guest') is True or body.get('is_login') is False:
                return 'check_failed', None
            uid = own_account_id('xhs', data)
        else:
            return 'check_failed', None
        return ('authenticated', uid) if safe_account_ref(platform, uid) else ('check_failed', None)
    except Exception:
        return 'check_failed', None


class ProAccountHooks:
    def __init__(self, collector_root, session_id, platform, run_id, event, httpx_module, client_class):
        self.store = AccountSessions(collector_root)
        self.session_id, self.platform, self.run_id = session_id, platform, run_id
        self.event, self.httpx, self.client_class = event, httpx_module, client_class
        self.capture = ContextVar('pro_self_check', default=None)
        self.original_send, self.original_pong = httpx_module.AsyncClient.send, client_class.pong

    def emit(self, value):
        fields = ('state', 'session_id', 'platform', 'generation', 'identity_status', 'account_ref',
                  'authorized_for_run', 'pending_run_id', 'login_verified', 'verification_method')
        self.event(value['state'], {k: value[k] for k in fields if k in value})

    def observe_response(self, response):
        """Call before budget transport's response rejection when available."""
        capture = self.capture.get()
        if capture is None:
            return
        try:
            u = urlsplit(str(response.url))
            if u.scheme == 'https' and (u.hostname, u.path) == SELF_ENDPOINTS.get(self.platform):
                capture['proof'] = self_proof(self.platform, response)
        except Exception:
            capture['proof'] = ('check_failed', None)

    def install(self):
        hook = self
        async def send(client, *args, **kwargs):
            response = await hook.original_send(client, *args, **kwargs)
            hook.observe_response(response)
            return response
        async def pong(client, *args, **kwargs):
            previous = hook.store.status(hook.session_id, hook.platform)
            if previous.get('pending_run_id') and not previous.get('account_ref'):
                hook.store._update(hook.session_id, hook.platform, lambda v: v.update(
                    recovering=True, identity_status='baseline_unverified'))
            hook.emit(hook.store.observe(hook.session_id, hook.platform, 'checking', hook.run_id))
            if hook.platform not in SELF_ENDPOINTS:
                hook.store.observe(hook.session_id, hook.platform, 'check_failed', hook.run_id)
                value = hook.store._update(hook.session_id, hook.platform, lambda v: v.update(
                    identity_status='pro_self_check_unsupported'))
                hook.emit(value)
                raise SystemExit(77)  # Pro DY uses private history; no supported self proof yet.
            capture = {'proof': ('check_failed', None)}
            token = hook.capture.set(capture)
            try:
                result = await hook.original_pong(client, *args, **kwargs)
            except BaseException:
                # Includes budget/captcha/cancellation exits. Preserve the original exit.
                try:
                    proof, _ = capture['proof']
                    hook.emit(hook.store.observe(hook.session_id, hook.platform,
                        'logged_out' if proof == 'logged_out' else 'check_failed', hook.run_id))
                except BaseException:
                    pass  # Preserve the source/budget/cancellation failure over diagnostic storage.
                raise
            finally:
                hook.capture.reset(token)
            proof, uid = capture['proof']
            if result is not True or proof != 'authenticated':
                hook.emit(hook.store.observe(hook.session_id, hook.platform,
                    'logged_out' if proof == 'logged_out' else 'check_failed', hook.run_id))
                raise SystemExit(77)
            value = hook.store.observe(hook.session_id, hook.platform, 'authenticated', hook.run_id, uid)
            hook.emit(value)
            if value['state'] == 'account_changed':
                raise SystemExit(78)
            if value['state'] == 'identity_unverified' or value.get('authorized_for_run') != hook.run_id:
                raise SystemExit(77)
            return True
        self.httpx.AsyncClient.send, self.client_class.pong = send, pong
        return self

    def restore(self):
        self.httpx.AsyncClient.send, self.client_class.pong = self.original_send, self.original_pong


def install_pro_account_hooks(collector_root, session_id, platform, run_id, event, httpx_module, client_class):
    return ProAccountHooks(collector_root, session_id, platform, run_id, event, httpx_module, client_class).install()
