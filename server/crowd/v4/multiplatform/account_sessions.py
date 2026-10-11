"""Account metadata and existing-MC login callbacks; never import browser credentials."""
import argparse
import asyncio
import contextlib
import fcntl
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
import uuid
from urllib.parse import urlsplit

PLATFORMS = {'xhs', 'dy', 'ks', 'bili', 'wb', 'tieba', 'zhihu'}
CLIENTS = {'xhs': ('xhs', 'XiaoHongShuClient'), 'dy': ('douyin', 'DouYinClient'),
           'ks': ('kuaishou', 'KuaiShouClient'), 'bili': ('bilibili', 'BilibiliClient'),
           'wb': ('weibo', 'WeiboClient'), 'tieba': ('tieba', 'BaiduTieBaClient'),
           'zhihu': ('zhihu', 'ZhiHuClient')}


def identifier(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError('invalid_session_id')
    return value


def safe_account_ref(platform, value):
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        return None
    value = str(value)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value):
        return None
    return hashlib.sha256((platform + ':' + value).encode()).hexdigest()


def own_account_id(platform, data):
    """Only fields from the existing authenticated self-check, never target authors."""
    paths = {'bili': [('mid',)], 'wb': [('uid',), ('data', 'uid')], 'zhihu': [('uid',)],
             'xhs': [('data', 'user_id'), ('data', 'basic_info', 'user_id'),
                     ('data', 'result', 'user_id'), ('data', 'result', 'user', 'user_id')]}
    for path in paths.get(platform, []):
        value = data
        for key in path:
            value = value.get(key) if isinstance(value, dict) else None
        if safe_account_ref(platform, value):
            return value
    return None


class AccountSessions:
    def __init__(self, collector_root):
        self.collector_root = Path(collector_root).resolve()
        self.root = self.collector_root / 'accounts'

    def _session(self, session_id, platform=None):
        session_id = identifier(session_id)
        path = self.collector_root / 'sessions' / session_id
        if not path.is_dir() or path.is_symlink():
            raise ValueError('session_not_found')
        identity = json.loads((path / 'identity.json').read_text())
        if identity.get('platform') not in PLATFORMS or (platform and identity['platform'] != platform):
            raise ValueError('session_platform_mismatch')
        return path, identity['platform']

    def status(self, session_id, platform=None):
        _, platform = self._session(session_id, platform)
        path = self.root / session_id / 'state.json'
        try:
            value = json.loads(path.read_text())
        except FileNotFoundError:
            value = {'session_id': session_id, 'platform': platform, 'state': 'unverified',
                     'generation': 0, 'identity_status': 'unverified', 'authorized_for_run': None}
        return {'ok': True, **value, 'credentials_imported': False}

    def list(self):
        sessions = []
        for path in (self.collector_root / 'sessions').glob('*'):
            if path.is_dir() and not path.is_symlink():
                try:
                    sessions.append(self.status(path.name))
                except (ValueError, OSError, TypeError):
                    continue
        return {'ok': True, 'sessions': sessions}

    def _update(self, session_id, platform, change):
        self._session(session_id, platform)
        folder = self.root / session_id
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        with open(folder / 'state.lock', 'a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            value = self.status(session_id, platform)
            value.pop('ok', None)
            change(value)
            value['updated_at'] = time.time()
            temporary = folder / ('state-' + secrets.token_hex(8))
            with os.fdopen(os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'w') as stream:
                json.dump(value, stream)
                stream.flush(); os.fsync(stream.fileno())
            temporary.replace(folder / 'state.json')
        return {'ok': True, **value}

    def observe(self, session_id, platform, event, run_id=None, account_id=None):
        if event not in ('checking', 'logged_out', 'waiting_login', 'check_failed', 'authenticated'):
            raise ValueError('invalid_account_event')
        if run_id is not None:
            identifier(run_id)
        account_ref = safe_account_ref(platform, account_id)
        def change(value):
            if run_id and event in ('checking', 'logged_out', 'waiting_login'):
                value['pending_run_id'] = run_id
            if event == 'checking':
                value['recovering'] = value.get('recovering') or value['state'] in ('logged_out', 'waiting_login', 'identity_unverified', 'account_changed', 'check_failed')
                value['state'] = 'checking'
                return
            if event != 'authenticated':
                value['state'] = event
                if event in ('logged_out', 'waiting_login', 'check_failed'):
                    value['recovering'] = True
                    value['authorized_for_run'] = None
                return
            previous = value.get('account_ref')
            if previous and account_ref and previous != account_ref:
                generation = value.get('generation', 0) + (value.get('candidate_account_ref') != account_ref)
                value.update(state='account_changed', generation=generation,
                             candidate_account_ref=account_ref, authorized_for_run=None,
                             identity_status='different_account', recovering=True)
                return
            if previous and previous == account_ref:
                value.pop('candidate_account_ref', None)
            if value.get('candidate_account_ref'):
                value.update(state='account_changed', authorized_for_run=None)
                return
            if value.get('recovering') and value.get('generation', 0) > 0 and (not previous or not account_ref):
                value.update(state='identity_unverified', authorized_for_run=None,
                             identity_status='same_account_confirmation_required', login_verified=True,
                             verified_at=time.time())
                return
            value.update(state='resumed' if value.get('recovering') else 'authenticated',
                         account_ref=account_ref or previous,
                         generation=max(value.get('generation', 0), 1),
                         identity_status='authenticated_self_id' if account_ref else 'session_only_unverified',
                         login_verified=True, recovering=False,
                         verified_at=time.time(),
                         verification_method='upstream_browser_flag' if platform in ('dy', 'tieba') else 'upstream_authenticated_endpoint',
                         authorized_for_run=value.get('pending_run_id') or run_id)
        return self._update(session_id, platform, change)

    def confirm_same_account(self, session_id, expected_generation, confirm_same_account=False):
        status = self.status(session_id)
        if type(expected_generation) is not int or confirm_same_account is not True:
            raise ValueError('explicit_same_account_confirmation_required')
        def change(value):
            if value.get('generation') != expected_generation:
                raise ValueError('account_generation_changed')
            if value['state'] != 'identity_unverified' or not value.get('login_verified'):
                raise ValueError('account_confirmation_not_available')
            if time.time() - value.get('verified_at', 0) > 180:
                raise ValueError('account_login_check_stale')
            value.update(state='resumed', identity_status='manually_confirmed_same_account',
                         recovering=False, authorized_for_run=value.get('pending_run_id'))
        return self._update(session_id, status['platform'], change)

    def accept_account_switch(self, session_id, expected_generation, acknowledge_new_scope=False):
        status = self.status(session_id)
        if type(expected_generation) is not int or acknowledge_new_scope is not True:
            raise ValueError('explicit_new_account_scope_required')
        def change(value):
            if value.get('generation') != expected_generation or value['state'] != 'account_changed':
                raise ValueError('account_generation_changed')
            value.update(account_ref=value.pop('candidate_account_ref'), state='authenticated',
                         identity_status='explicitly_accepted_new_account', recovering=False,
                         authorized_for_run=None, pending_run_id=None)
        return self._update(session_id, status['platform'], change)

    def open_login(self, session_id, platform, mc_root):
        session, _ = self._session(session_id, platform)
        mc_root = Path(mc_root).resolve()
        if not (mc_root / '.venv/bin/python').is_file() or not (mc_root / 'main.py').is_file():
            raise ValueError('external_executor_missing')
        lock = open(session / 'active.lock', 'a+')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close(); raise ValueError('session_busy')
        try:
            status = self.observe(session_id, platform, 'checking')
            folder = self.root / session_id
            (folder / 'login-stop').unlink(missing_ok=True)
            process = subprocess.Popen([str(mc_root / '.venv/bin/python'), str(Path(__file__).resolve()),
                '--root', str(self.collector_root), '--mc-root', str(mc_root), '--session-id', session_id,
                '--platform', platform, '--lock-fd', str(lock.fileno()), '_login_worker'],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True, pass_fds=(lock.fileno(),), env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
            status = self._update(session_id, platform, lambda value: value.update(login_worker_pid=process.pid))
            return {**status, 'source_collection_started': False}
        finally:
            lock.close()

    def cancel_login(self, session_id):
        self._session(session_id)
        folder = self.root / session_id
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        (folder / 'login-stop').touch(mode=0o600)
        return {'ok': True, 'session_id': session_id, 'cancel_requested': True}


def install_hooks(collector_root, session_id, platform, run_id, event, headless=False, client_class=None):
    """Observe original pong; recheck after native login updates, without copying cookies."""
    store = AccountSessions(collector_root)
    if client_class is None:
        module, name = CLIENTS[platform]
        client_class = getattr(importlib.import_module('media_platform.' + module + '.client'), name)
    original_pong = client_class.pong
    original_update = client_class.update_cookies
    capture = {'checking': False, 'account_id': None, 'error': False, 'args': ()}
    def emit(value):
        event(value['state'], value)
    for method_name in ('query_self', 'get_current_user_info', 'get', 'request', 'post'):
        original = getattr(client_class, method_name, None)
        if original is None:
            continue
        def wrap(function):
            async def observed(self, *args, **kwargs):
                try:
                    value = await function(self, *args, **kwargs)
                except Exception:
                    if capture['checking']:
                        capture['error'] = True
                    raise
                if capture['checking']:
                    own_id = own_account_id(platform, value)
                    if own_id is not None:
                        capture['account_id'] = own_id
                return value
            return observed
        setattr(client_class, method_name, wrap(original))
    async def pong(self, *args, **kwargs):
        capture.update(checking=True, account_id=None, error=False, args=args)
        emit(store.observe(session_id, platform, 'checking', run_id))
        try:
            result = await original_pong(self, *args, **kwargs)
        finally:
            capture['checking'] = False
        if result is True:
            value = store.observe(session_id, platform, 'authenticated', run_id, capture['account_id'])
            emit(value)
            if value['state'] == 'account_changed':
                raise SystemExit(78)
            if value['state'] == 'identity_unverified':
                deadline = time.monotonic() + 120
                while time.monotonic() < deadline:
                    value = store.status(session_id, platform)
                    if value['state'] == 'resumed':
                        emit(value); return True
                    if (store.root / session_id / 'login-stop').exists():
                        raise SystemExit(77)
                    await asyncio.sleep(1)
                raise SystemExit(77)
            return True
        value = store.observe(session_id, platform, 'check_failed' if capture['error'] else 'logged_out', run_id)
        emit(value)
        if headless or capture['error']:
            raise SystemExit(77)
        emit(store.observe(session_id, platform, 'waiting_login', run_id))
        return False
    async def update(self, *args, **kwargs):
        result = await original_update(self, *args, **kwargs)
        status = store.status(session_id, platform)
        if status['state'] in ('logged_out', 'waiting_login', 'check_failed'):
            ping_args = capture['args']
            if platform in ('dy', 'tieba') and not ping_args:
                ping_args = (kwargs.get('browser_context') or (args[0] if args else None),)
            await self.pong(*ping_args)
        return result
    client_class.pong = pong
    client_class.update_cookies = update
    return store


def guard_auth_response(store, session_id, platform, run_id, event, response):
    """Stop explicit source authentication failures; CDN URLs are not account evidence."""
    domains = {'xhs': ('xiaohongshu.com',), 'dy': ('douyin.com',), 'ks': ('kuaishou.com',),
               'bili': ('bilibili.com',), 'wb': ('weibo.cn', 'weibo.com'),
               'tieba': ('tieba.baidu.com',), 'zhihu': ('zhihu.com',)}
    host = urlsplit(str(response.request.url)).hostname or ''
    if not any(host == d or host.endswith('.' + d) for d in domains[platform]):
        return
    status = store.status(session_id, platform)
    if status['state'] not in ('authenticated', 'resumed'):
        return
    logout = response.status_code in (401, 419)
    if response.status_code == 200:
        try:
            data = response.json()
            message = str(data.get('message') or data.get('msg') or '').lower() if isinstance(data, dict) else ''
            logout = any(text in message for text in ('not logged in', 'login required', '请先登录', '未登录', '登录失效', '登录过期'))
        except (ValueError, TypeError, RuntimeError):
            pass
    if logout:
        value = store.observe(session_id, platform, 'logged_out', run_id)
        event(value['state'], value)
        raise SystemExit(77)


async def login_worker(args):
    """Use MC's visible human-login path with every content-collection entry disabled."""
    store = AccountSessions(args.root)
    session, _ = store._session(args.session_id, args.platform)
    folder = store.root / args.session_id
    work = folder / ('login-' + secrets.token_hex(8)); work.mkdir(mode=0o700)
    (work / 'browser_data').symlink_to(session / 'browser_data', target_is_directory=True)
    (work / 'libs').symlink_to(Path(args.mc_root).resolve() / 'libs', target_is_directory=True)
    graphql = work / 'media_platform/kuaishou'
    graphql.mkdir(parents=True)
    (graphql / 'graphql').symlink_to(Path(args.mc_root).resolve() / 'media_platform/kuaishou/graphql', target_is_directory=True)
    os.chdir(work)
    sys.path.insert(0, str(Path(args.mc_root).resolve()))
    class Silent:
        def write(self, value): return len(value)
        def flush(self): pass
        def isatty(self): return False
    with contextlib.redirect_stdout(Silent()), contextlib.redirect_stderr(Silent()):
        import config
        config.PLATFORM = args.platform; config.CRAWLER_TYPE = 'search'; config.LOGIN_TYPE = 'qrcode'
        config.ENABLE_CDP_MODE = False; config.CDP_CONNECT_EXISTING = False
        config.ENABLE_IP_PROXY = False; config.COOKIES = ''
        config.SAVE_LOGIN_STATE = True; config.USER_DATA_DIR = '%s_bridge_profile'; config.HEADLESS = False
        config.ENABLE_GET_COMMENTS = False; config.ENABLE_GET_CONTACTS = False; config.ENABLE_GET_DYNAMICS = False
        import main as upstream
        crawler_class = upstream.CrawlerFactory.CRAWLERS[args.platform]
        async def no_collection(self, *_args, **_kwargs): return None
        crawler_class.search = no_collection
        def event(_state, _value): pass
        install_hooks(args.root, args.session_id, args.platform, None, event)
        from playwright.async_api import BrowserType
        original = BrowserType.launch_persistent_context
        async def persistent(self, *a, **kw):
            if self.name == 'chromium' and not Path(self.executable_path).is_file():
                kw['executable_path'] = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
            return await original(self, *a, **kw)
        BrowserType.launch_persistent_context = persistent
        import httpx
        send = httpx.AsyncClient.send
        attempts = 0
        async def bounded_send(self, *a, **kw):
            nonlocal attempts
            attempts += 1
            if attempts > 8: raise SystemExit(77)
            return await send(self, *a, **kw)
        httpx.AsyncClient.send = bounded_send
        crawler = crawler_class()
        task = asyncio.create_task(crawler.start())
        deadline = time.monotonic() + 180
        try:
            while not task.done():
                if time.monotonic() > deadline or (folder / 'login-stop').exists():
                    task.cancel(); raise SystemExit(77)
                await asyncio.sleep(.5)
            await task
        finally:
            if not task.done(): task.cancel()
            if getattr(crawler, 'browser_context', None):
                await crawler.browser_context.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True); parser.add_argument('--mc-root', required=True)
    parser.add_argument('--session-id', required=True); parser.add_argument('--platform', choices=sorted(PLATFORMS), required=True)
    parser.add_argument('--lock-fd', type=int, required=True); parser.add_argument('action', choices=['_login_worker'])
    arguments = parser.parse_args()
    try:
        asyncio.run(login_worker(arguments))
    except BaseException:
        status = AccountSessions(arguments.root).status(arguments.session_id)
        if status['state'] not in ('resumed', 'authenticated', 'account_changed', 'identity_unverified'):
            AccountSessions(arguments.root).observe(arguments.session_id, arguments.platform, 'check_failed')
    finally:
        os.close(arguments.lock_fd)
