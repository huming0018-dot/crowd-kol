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


class LoginVerified(Exception):
    """Exit login-only navigation after native account verification, before collection."""


class LoginFlowError(BaseException):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _login_failure_kind(error):
    name = type(error).__name__
    if name == 'DataFetchError':
        return 'graphql_error'
    if name == 'JSONDecodeError':
        return 'response_not_json'
    if name in ('TimeoutError', 'TimeoutException', 'ConnectTimeout', 'ReadTimeout', 'WriteTimeout', 'PoolTimeout'):
        return 'network_timeout'
    if name in ('ConnectError', 'ReadError', 'WriteError', 'NetworkError', 'RemoteProtocolError', 'RequestError'):
        return 'network_error'
    return 'unknown_error'


def _ks_graphql_error_kind(errors):
    """Categorize already received errors; never return server text, IDs or codes."""
    if not errors:return 'none'
    if not isinstance(errors,list) or not 1<=len(errors)<=20:return 'unknown'
    kinds=set()
    codes={'GRAPHQL_VALIDATION_FAILED':'schema_validation','GRAPHQL_PARSE_FAILED':'schema_validation',
           'UNAUTHENTICATED':'authentication_required','RATE_LIMITED':'rate_or_permission','FORBIDDEN':'rate_or_permission'}
    for error in errors:
        if not isinstance(error,dict):return 'unknown'
        extensions=error.get('extensions');code=extensions.get('code') if isinstance(extensions,dict) else None
        kind=codes.get(code) if isinstance(code,str) else None
        message=error.get('message')
        if kind is None and isinstance(message,str):
            message=message[:5000].lower()
            if any(pattern in message for pattern in ('cannot query field ', 'unknown argument ', 'unknown type ', 'syntax error:')):
                kind='schema_validation'
        kinds.add(kind or 'unknown')
    return next(iter(kinds)) if len(kinds)==1 else 'unknown'


def _ks_response_diagnostic(response):
    """Classify the existing loaded response; never persist headers, bodies or messages."""
    status = getattr(response, 'status_code', None)
    result = {'http_status': status if type(status) is int and 100 <= status <= 599 else None,
              'response_kind': 'unknown', 'graphql_errors': 'unknown', 'graphql_result': 'unknown', 'graphql_error_kind':'unknown'}
    if getattr(response, 'is_stream_consumed', True) is False:
        return result
    try:
        data = response.json()
    except Exception:
        result['response_kind'] = 'non_json'
        return result
    result['response_kind'] = 'json'
    if isinstance(data, dict):
        result['graphql_errors'] = 'present' if data.get('errors') else 'absent'
        result['graphql_error_kind'] = _ks_graphql_error_kind(data.get('errors'))
        payload = data.get('data')
        profile = payload.get('visionProfileUserList') if isinstance(payload, dict) else None
        result['graphql_result'] = ('one' if profile['result'] == 1 else 'other') if isinstance(profile, dict) and 'result' in profile else 'missing'
    return result


def _bili_self_request(request):
    """Only recognize the official self endpoint in memory; retain no URL fields."""
    try:
        parsed = urlsplit(str(request.url))
        return (request.method == 'GET' and parsed.scheme == 'https' and
                parsed.hostname == 'api.bilibili.com' and parsed.port in (None, 443) and
                parsed.path == '/x/web-interface/nav' and not parsed.query and
                not parsed.fragment and parsed.username is None and parsed.password is None)
    except (AttributeError, TypeError, ValueError):
        return False


def _bili_self_diagnostic(response=None, error=None):
    """Fixed categories from already received self response, never raw text or subject."""
    status = getattr(response, 'status_code', None)
    result = {'http_status': status if type(status) is int and 100 <= status <= 599 else None,
              'api_code': None, 'json_shape': 'unavailable', 'data_shape': 'unavailable',
              'is_login_type': 'unavailable', 'subject_present': False,
              'transport_category': _login_failure_kind(error) if error is not None else 'none'}
    if response is None or getattr(response, 'is_stream_consumed', True) is False:
        return result
    try:
        value = response.json()
    except Exception:
        result['json_shape'] = 'invalid_json'
        return result
    def shape(value):
        return ('object' if isinstance(value, dict) else 'array' if isinstance(value, list)
                else 'null' if value is None else 'scalar')
    result['json_shape'] = shape(value)
    if not isinstance(value, dict):
        return result
    code = value.get('code')
    if type(code) is int and -(2**31) <= code < 2**31:
        result['api_code'] = code
    data = value.get('data')
    result['data_shape'] = shape(data) if 'data' in value else 'missing'
    if isinstance(data, dict):
        flag = data.get('isLogin')
        result['is_login_type'] = ('missing' if 'isLogin' not in data else 'boolean' if type(flag) is bool
            else 'null' if flag is None else 'number' if type(flag) in (int, float)
            else 'string' if isinstance(flag, str) else 'other')
        result['subject_present'] = 'mid' in data and data['mid'] is not None
    return result


def _record_bili_self_diagnostic(store, session_id, request, verification, response=None, error=None):
    """Observation is best effort; it cannot replace the original result or exception."""
    try:
        if not _bili_self_request(request) or store.status(session_id).get('state') != 'checking':
            return
        diagnostic = _bili_self_diagnostic(response, error)
        diagnostic.update(round=verification.round, attempt=verification.attempts)
        store._update(session_id, 'bili', lambda value: value.update(login_diagnostic=diagnostic))
    except Exception:
        pass


def _original_profile_reference(session, platform):
    """Only a migration-pinned original XHS session may supply browser_data."""
    try:
        marker = session / 'browser-profile-reference.json'
        if platform != 'xhs' or marker.is_symlink() or marker.stat().st_mode & 0o077 or marker.stat().st_uid != os.getuid() or marker.stat().st_size > 4096:
            return False
        value = json.loads(marker.read_text())
        if set(value) != {'schema', 'session_id', 'platform', 'browser_data', 'identity_sha256', 'binding_sha256'} or value['schema'] != 'crowd-pro-original-browser-profile-v1' or value['session_id'] != session.name or value['platform'] != platform:
            return False
        original = Path(value['browser_data'])
        if not original.is_absolute() or original.resolve() != original or original.name != 'browser_data' or original.parent.name != session.name or original.parent.parent.name != 'sessions' or original.parent == session or not original.is_dir() or not (session / 'browser_data').is_symlink() or (session / 'browser_data').resolve() != original:
            return False
        for name, field in (('identity.json', 'identity_sha256'), ('pro-binding.json', 'binding_sha256')):
            for path in (session / name, original.parent / name):
                if path.is_symlink() or path.stat().st_size > 16384 or hashlib.sha256(path.read_bytes()).hexdigest() != value[field]:
                    return False
        return json.loads((session / 'identity.json').read_text()) == {'platform': platform}
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        return False


def _preserve_bound_xhs_bridge(root, session_id, platform, browser_name, user_data_dir, options):
    """Only keep the already-bound XHS/Bili profile's installed extensions enabled.

    No extension is installed/loaded here; missing registration remains a separate
    recovery condition. MC profiles without an explicit Pro binding stay unchanged.
    """
    result = dict(options)
    if platform not in ('xhs', 'bili') or browser_name != 'chromium':
        return result
    try:
        session = Path(root).resolve() / 'sessions' / identifier(session_id)
        expected = session / 'browser_data' / (platform + '_bridge_profile')
        binding = session / 'pro-binding.json'
        if (session.is_symlink() or session.parent.is_symlink() or (expected.parent.is_symlink() and not _original_profile_reference(session, platform))
                or not expected.is_dir() or expected.is_symlink() or not binding.is_file()
                or binding.is_symlink() or binding.stat().st_size > 16384):
            return result
        if Path(user_data_dir).resolve() != expected.resolve():
            return result
        value = json.loads(binding.read_text())
        if (not isinstance(value, dict) or set(value) != {'platform', 'client_id', 'cookiebridge_url', 'sign_url'}
                or value.get('platform') != platform or not isinstance(value.get('client_id'), str)
                or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value['client_id'])):
            return result
        for field in ('cookiebridge_url', 'sign_url'):
            if not isinstance(value[field], str):
                return result
            url = urlsplit(value[field])
            if not (url.scheme == 'http' and url.hostname in ('localhost', '127.0.0.1', '::1')
                    and url.port and not url.username and not url.password
                    and url.path in ('', '/') and not url.query and not url.fragment):
                return result
        ignored = result.get('ignore_default_args', [])
        if not isinstance(ignored, (list, tuple)) or not all(isinstance(x, str) for x in ignored):
            return result
        result['ignore_default_args'] = list(dict.fromkeys([*ignored, '--disable-extensions']))
    except (OSError, ValueError, TypeError, RecursionError):
        return dict(options)
    return result


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
        session, platform = self._session(session_id, platform)
        path = self.root / session_id / 'state.json'
        try:
            value = json.loads(path.read_text())
        except FileNotFoundError:
            value = {'session_id': session_id, 'platform': platform, 'state': 'unverified',
                     'generation': 0, 'identity_status': 'unverified', 'authorized_for_run': None}
        active = session / 'active.lock'
        busy = active.is_symlink()
        if active.exists() and not busy:
            try:
                with open(active, 'r+') as lock:
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        busy = True
                    else:
                        fcntl.flock(lock, fcntl.LOCK_UN)
            except OSError:
                busy = True
        return {'ok': True, **value, 'credentials_imported': False, 'login_in_progress': busy}

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
            value.pop('login_in_progress', None)
            change(value)
            value['updated_at'] = time.time()
            temporary = folder / ('state-' + secrets.token_hex(8))
            with os.fdopen(os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'w') as stream:
                json.dump(value, stream)
                stream.flush(); os.fsync(stream.fileno())
            temporary.replace(folder / 'state.json')
        return {'ok': True, **value}

    def observe(self, session_id, platform, event, run_id=None, account_id=None, *, _expected_context=None, _allow_account_change=False):
        if event not in ('checking', 'logged_out', 'waiting_login', 'check_failed', 'authenticated'):
            raise ValueError('invalid_account_event')
        if run_id is not None:
            identifier(run_id)
        account_ref = safe_account_ref(platform, account_id)
        if type(_allow_account_change) is not bool or (_allow_account_change and (platform!='zhihu' or event!='authenticated' or _expected_context is None)):
            raise ValueError('invalid_account_change_context')
        def change(value):
            if _expected_context is not None:
                if (event not in ('checking','authenticated','check_failed','logged_out') or not run_id or type(_expected_context) is not dict
                        or set(_expected_context) != {'generation','account_ref'}
                        or type(_expected_context['generation']) is not int or _expected_context['generation'] < 1
                        or not isinstance(_expected_context['account_ref'],str)
                        or not re.fullmatch(r'[0-9a-f]{64}',_expected_context['account_ref'])
                        or type(value.get('generation')) is not int
                        or value.get('generation') != _expected_context['generation']
                        or value.get('account_ref') != _expected_context['account_ref']
                        or value.get('state') == 'account_changed'
                        or event!='checking' and value.get('pending_run_id')!=run_id
                        or event=='authenticated' and (account_ref!=_expected_context['account_ref'] and not _allow_account_change
                            or (self.root/session_id/'login-stop').exists()
                            or (self.root/session_id/'login-stop').is_symlink())):
                    raise ValueError('cloud_login_account_changed')
            if run_id and event in ('checking', 'logged_out', 'waiting_login', 'check_failed'):
                value['pending_run_id'] = run_id
            if event != 'authenticated':
                value.pop('unverified_account_ref', None)
                value.update(login_verified=False, verified_at=0, authorized_for_run=None)
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
            value.pop('login_error_code', None)
            value.pop('browser_connection_error', None)
            value.pop('unverified_account_ref', None)
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
            if value.get('recovering') and (not previous or not account_ref):
                if account_ref:
                    value['unverified_account_ref'] = account_ref
                else:
                    value.pop('unverified_account_ref', None)
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
        expired = False
        def change(value):
            nonlocal expired
            if value.get('generation') != expected_generation:
                raise ValueError('account_generation_changed')
            if value['state'] != 'identity_unverified' or not value.get('login_verified'):
                raise ValueError('account_confirmation_not_available')
            if time.time() - value.get('verified_at', 0) > 180:
                value.pop('unverified_account_ref', None)
                value.update(login_verified=False, verified_at=0, authorized_for_run=None)
                expired = True
                return
            pending_ref = value.pop('unverified_account_ref', None)
            if pending_ref:
                value['account_ref'] = pending_ref
            value.update(state='resumed', identity_status='manually_confirmed_same_account',
                         recovering=False, authorized_for_run=value.get('pending_run_id'))
        result = self._update(session_id, status['platform'], change)
        if expired:
            raise ValueError('account_login_check_stale')
        return result

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

    def open_login(self, session_id, platform, mc_root, *, _recovery=None):
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
            def close_abandoned_self_check(value):
                check=value.get('last_self_check')
                if isinstance(check,dict) and check.get('check_only') is True and check.get('phase')=='checking':
                    value['last_self_check']={**check,'phase':'interrupted','reason':'previous_check_outcome_unknown'}
            # The acquired original active lock proves the old self-check no longer owns it.
            # Keep all operation files and account proof; only retire the stale display.
            self._update(session_id,platform,close_abandoned_self_check)
            if _recovery is not None:
                if type(_recovery) is not dict or set(_recovery) != {'run_id','generation','account_ref'}:
                    raise ValueError('invalid_cloud_login_context')
                status = self.observe(session_id, platform, 'checking', run_id=_recovery['run_id'],
                    _expected_context={key:_recovery[key] for key in ('generation','account_ref')})
            else:
                status = self.observe(session_id, platform, 'checking')
            self._update(session_id, platform, lambda value: value.pop('login_error_code', None))
            folder = self.root / session_id
            (folder / 'login-stop').unlink(missing_ok=True)
            (folder / 'login-verify-continue').unlink(missing_ok=True)
            self._update(session_id, platform, lambda value: value.update(login_verification_paused=False))
            process = subprocess.Popen([str(mc_root / '.venv/bin/python'), str(Path(__file__).resolve()),
                '--root', str(self.collector_root), '--mc-root', str(mc_root), '--session-id', session_id,
                '--platform', platform, '--lock-fd', str(lock.fileno()), '_login_worker'],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True, pass_fds=(lock.fileno(),), env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
            status = self._update(session_id, platform, lambda value: value.update(login_worker_pid=process.pid))
            return {**status, 'source_collection_started': False}
        finally:
            lock.close()

    def browser_candidates(self, session_id, port=9222, restart_connection=False,refresh_targets=False):
        from browser_session import inspect_browser
        _,platform=self._session(session_id)
        if type(restart_connection) is not bool:raise ValueError('invalid_browser_restart')
        if type(refresh_targets) is not bool:raise ValueError('invalid_browser_refresh')
        try:value=inspect_browser(port,platform,retain_connection=True,restart_connection=restart_connection,refresh_targets=refresh_targets)
        except ValueError as error:
            if str(error) not in ('browser_connection_pending','browser_connection_expired'):raise
            return {'ok':True,'session_id':session_id,'port':port,'targets':[],
                    'browser_connection_state':'pending' if str(error)=='browser_connection_pending' else 'expired',
                    'reason_code':str(error),'credentials_imported':False}
        value.pop('_socket_path',None)
        value.pop('_all_targets',None)
        return {'ok':True,'session_id':session_id,**value,'credentials_imported':False}

    def bind_browser(self, session_id, port, target_id, browser_fingerprint, expected_generation):
        return self._bind_browser_candidate(session_id,port,target_id,browser_fingerprint,expected_generation)

    def bind_pro_browser(self, session_id, port, target_id, browser_fingerprint, recovery):
        if (type(recovery) is not dict or set(recovery)!={'run_id','generation','account_ref'}
                or type(recovery['generation']) is not int or recovery['generation']<1
                or type(recovery['account_ref']) is not str or not re.fullmatch('[a-f0-9]{64}',recovery['account_ref'])):
            raise ValueError('cloud_login_account_changed')
        identifier(recovery['run_id'])
        return self._bind_browser_candidate(session_id,port,target_id,browser_fingerprint,recovery['generation'],recovery=recovery)

    def _bind_browser_candidate(self, session_id, port, target_id, browser_fingerprint, expected_generation, current=None, *, recovery=None):
        from browser_session import BrowserSessionError
        session,platform=self._session(session_id)
        if type(expected_generation) is not int:raise ValueError('account_generation_changed')
        with open(session/'active.lock','a+') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise ValueError('session_busy') from None
            if current is None:current=self.browser_candidates(session_id,port)
            if current.get('browser_connection_state') in ('pending','expired'):
                raise BrowserSessionError(current['reason_code'])
            if current['browser_fingerprint']!=browser_fingerprint or target_id not in {row['target_id'] for row in current['targets']}:
                raise BrowserSessionError('browser_selection_changed')
            selected=next(row for row in current['targets'] if row['target_id']==target_id)
            if recovery is not None:
                if platform!='bili' or selected.get('selection_kind')!='platform_page':raise ValueError('browser_platform_page_required')
                from managed_pro_signer import private_object,SignerError
                from pro_executor import binding_for
                try:
                    previous=private_object(session/'pro-binding.json')
                    if previous!=binding_for(self.collector_root,{'platform':platform,'session_id':session_id}):raise ValueError()
                except (SignerError,SystemExit,ValueError):raise ValueError('pro_account_binding_required') from None
            def change(value):
                if type(value.get('generation')) is not int or value.get('generation')!=expected_generation:raise ValueError('account_generation_changed')
                if recovery is not None and (value.get('account_ref')!=recovery['account_ref']
                        or value.get('pending_run_id')!=recovery['run_id'] or value.get('state')=='account_changed'):
                    raise ValueError('cloud_login_account_changed')
                value.update(browser_connection={'mode':'existing_cdp','port':port,'target_id':target_id,'browser_fingerprint':browser_fingerprint,'selection_kind':selected['selection_kind']},
                             state='checking',recovering=bool(value.get('account_ref') or value.get('pending_run_id') or value.get('recovering')),
                             login_verified=False,verified_at=0,authorized_for_run=None)
                value.pop('browser_connection_error',None)
                value.pop('login_error_code',None)
                if recovery is not None:
                    value.update(state='unverified',login_diagnostic=None)
            result=self._update(session_id,platform,change)
            if recovery is None:return result
            # Revoke the old proof durably before changing its credential provider.
            temporary=session/('pro-binding-'+secrets.token_hex(8)+'.tmp')
            try:
                backup=session/('pro-binding-before-cdp-'+hashlib.sha256(json.dumps(previous,sort_keys=True).encode()).hexdigest()+'.json')
                try:backup_fd=os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
                except FileExistsError:
                    if private_object(backup)!=previous:raise OSError('binding_backup_changed')
                else:
                    with os.fdopen(backup_fd,'w') as stream:
                        json.dump(previous,stream);stream.flush();os.fsync(stream.fileno())
                with os.fdopen(os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'w') as stream:
                    json.dump({'platform':'bili','provider':'existing_cdp'},stream);stream.flush();os.fsync(stream.fileno())
                temporary.replace(session/'pro-binding.json')
            except (OSError,SignerError):
                raise ValueError('browser_binding_outcome_unknown') from None
            finally:
                with contextlib.suppress(OSError):temporary.unlink(missing_ok=True)
            return {**result,'browser_bound':True,'verification_required':True,'credentials_imported':False}

    def create_browser_session(self, platform, port, target_id, browser_fingerprint):
        from browser_session import inspect_browser
        candidate=inspect_browser(port,platform,retain_connection=True)
        if candidate['browser_fingerprint']!=browser_fingerprint or target_id not in {row['target_id'] for row in candidate['targets']}:
            raise ValueError('browser_selection_changed')
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        with open(self.root/'browser-registry.lock','a+') as registry:
            fcntl.flock(registry,fcntl.LOCK_EX)
            matches=[row for row in self.list()['sessions'] if row['platform']==platform and
                     all(row.get('browser_connection',{}).get(key)==value for key,value in {'port':port,'target_id':target_id,'browser_fingerprint':browser_fingerprint}.items())]
            if len(matches)>1:raise ValueError('browser_registration_ambiguous')
            if matches:return {**matches[0],'registration_replayed':True}
            session_id=str(uuid.uuid4());session=self.collector_root/'sessions'/session_id
            session.mkdir(parents=True,mode=0o700)
            with os.fdopen(os.open(session/'identity.json',os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'w') as stream:
                json.dump({'platform':platform},stream);stream.flush();os.fsync(stream.fileno())
            return self._bind_browser_candidate(session_id,port,target_id,browser_fingerprint,0,candidate)

    def use_persistent_browser(self, session_id, expected_generation):
        session,platform=self._session(session_id)
        if type(expected_generation) is not int:raise ValueError('account_generation_changed')
        with open(session/'active.lock','a+') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise ValueError('session_busy') from None
            def change(value):
                if value.get('generation')!=expected_generation:raise ValueError('account_generation_changed')
                if not value.get('browser_connection'):raise ValueError('browser_binding_not_present')
                value.pop('browser_connection',None);value.pop('browser_connection_error',None)
                value.update(state='checking',recovering=bool(value.get('account_ref') or value.get('pending_run_id') or value.get('recovering')),
                             authorized_for_run=None,login_verified=False,verified_at=0)
            return self._update(session_id,platform,change)

    def cancel_login(self, session_id):
        self._session(session_id)
        folder = self.root / session_id
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        (folder / 'login-stop').touch(mode=0o600)
        return {'ok': True, 'session_id': session_id, 'cancel_requested': True}

    def resume_verification(self, session_id):
        status = self.status(session_id)
        if status.get('login_in_progress') is not True or status.get('login_verification_paused') is not True:
            raise ValueError('login_verification_not_paused')
        marker = self.root / session_id / 'login-verify-continue'
        if marker.is_symlink():
            raise ValueError('unsafe_login_continue_marker')
        try:
            fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        except FileExistsError:
            return {'ok': True, 'session_id': session_id, 'verification_continue_requested': True}
        os.close(fd)
        return {'ok': True, 'session_id': session_id, 'verification_continue_requested': True}


class LoginVerificationPaused(BaseException):
    """Unwind a request made with old credentials before waiting for the human."""


class LoginVerificationWindow:
    """Pause authenticated HTTP checks; only an explicit human marker opens another bounded round."""
    def __init__(self, store, session_id, platform, deadline):
        self.store, self.session_id, self.platform = store, session_id, platform
        self.deadline, self.attempts, self.round, self.paused = deadline, 0, 1, False
        self.folder = store.root / session_id

    def pause(self):
        if self.paused:
            return
        self.paused = True
        self.store.observe(self.session_id, self.platform, 'waiting_login')
        self.store._update(self.session_id, self.platform, lambda value: value.update(
            login_verification_paused=True, login_wait_reason='verification_paused',
            login_verified=False, authorized_for_run=None, login_verification_round=self.round,
            login_verification_attempts=self.attempts))

    async def ensure_window(self):
        if self.attempts >= 8 or time.monotonic() >= self.deadline:
            self.pause()
        while self.paused:
            if (self.folder / 'login-stop').exists():
                raise LoginFlowError('login_user_cancelled')
            marker = self.folder / 'login-verify-continue'
            if marker.is_symlink():
                raise LoginFlowError('unsafe_login_continue_marker')
            if marker.exists():
                marker.unlink()
                self.deadline, self.attempts, self.paused = time.monotonic()+180, 0, False
                self.round += 1
                self.store._update(self.session_id, self.platform, lambda value: value.update(
                    login_verification_paused=False, login_wait_reason='explicit_verification_round',
                    login_verification_round=self.round, login_verification_attempts=0))
                return
            await asyncio.sleep(.5)

    async def before_request(self):
        if self.paused or self.attempts >= 8 or time.monotonic() >= self.deadline:
            self.pause()
            raise LoginVerificationPaused()
        self.attempts += 1
        self.store._update(self.session_id, self.platform, lambda value: value.update(
            login_verification_round=self.round, login_verification_attempts=self.attempts))


def install_hooks(collector_root, session_id, platform, run_id, event, headless=False, client_class=None,
                  interactive_login=False):
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
                except Exception as error:
                    if capture['checking']:
                        capture['error'] = True
                        if interactive_login and platform == 'ks':
                            store._update(session_id, platform, lambda value: value['login_diagnostic'].update(
                                failure_kind=_login_failure_kind(error),
                                round=value.get('login_verification_round', 1),
                                attempt=value.get('login_verification_attempts', 0)))
                    raise
                if capture['checking']:
                    if interactive_login and platform == 'bili':
                        # Native pong accepts truthy flags; recovery needs the official boolean and subject.
                        flag = value.get('isLogin') if isinstance(value, dict) else None
                        subject = value.get('mid') if isinstance(value, dict) else None
                        if type(flag) is not bool or flag and (isinstance(subject, bool) or not re.fullmatch(r'[1-9][0-9]{0,29}', str(subject))):
                            capture['error'] = True
                    own_id = own_account_id(platform, value)
                    if own_id is not None:
                        capture['account_id'] = own_id
                return value
            return observed
        setattr(client_class, method_name, wrap(original))
    async def pong(self, *args, **kwargs):
        capture.update(checking=True, account_id=None, error=False, args=args)
        emit(store.observe(session_id, platform, 'checking', run_id))
        if interactive_login and platform == 'ks':
            def reset_diagnostic(value):
                value.pop('login_error_code', None)
                value.pop('login_verification_available', None)
                cookies = getattr(self, 'cookie_dict', None)
                value['login_diagnostic'] = {'round': value.get('login_verification_round', 1),
                    'attempt': value.get('login_verification_attempts', 0), 'http_status': None,
                    'response_kind': 'unknown', 'graphql_errors': 'unknown', 'graphql_result': 'unknown',
                    'graphql_error_kind':'unknown', 'failure_kind': None, 'client_login_flag_present': isinstance(cookies, dict) and bool(cookies.get('passToken'))}
            store._update(session_id, platform, reset_diagnostic)
        try:
            result = await original_pong(self, *args, **kwargs)
        except Exception as error:
            if not interactive_login or isinstance(error, (ImportError, FileNotFoundError)):
                # Keep the original failure, but never leave durable auth stuck at checking.
                emit(store.observe(session_id, platform, 'check_failed', run_id))
                raise
            capture['error'] = True
            result = False
        finally:
            capture['checking'] = False
        if interactive_login and platform == 'bili' and capture['error']:
            result = False
        if result is True:
            value = store.observe(session_id, platform, 'authenticated', run_id, capture['account_id'])
            if interactive_login:
                value = store._update(session_id, platform, lambda item: item.update(login_verification_available=True))
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
        if headless or capture['error'] and not interactive_login:
            raise SystemExit(77)
        if capture['error']:
            store._update(session_id, platform, lambda value: value.update(
                login_error_code='login_verification_unavailable', login_verification_available=False))
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


def install_manual_login_fallback(crawler, store, session_id, platform, deadline,
                                  login_class=None, client_class=None, utilities=None, verification=None):
    """Keep the original visible context alive when a native QR selector fails."""
    if platform not in ('zhihu', 'ks', 'xhs', 'bili'):
        return
    module, name = CLIENTS[platform]
    if client_class is None:
        client_class = getattr(importlib.import_module('media_platform.' + module + '.client'), name)
    if login_class is None:
        login_class = getattr(importlib.import_module('media_platform.' + module + '.login'),
                              {'zhihu': 'ZhiHuLogin', 'ks': 'KuaishouLogin', 'xhs': 'XiaoHongShuLogin', 'bili': 'BilibiliLogin'}[platform])
    if utilities is None:
        from tools import utils as utilities
    checked_pong = client_class.pong
    async def verified_pong(self, *args, **kwargs):
        page = crawler.context_page
        if page.is_closed():
            raise LoginFlowError('login_browser_closed')
        if not store.status(session_id).get('login_page_ready'):
            await page.bring_to_front()
            store._update(session_id, platform, lambda value: value.update(
                login_flow='native_original_browser', login_page_ready=True))
        if verification and (verification.paused or verification.attempts >= 8 or time.monotonic() >= verification.deadline):
            # A check without budget must not erase the last real response diagnosis.
            await verification.ensure_window()
            await self.update_cookies(browser_context=crawler.browser_context, urls=crawler.cookie_urls)
            return False
        try:
            verified = await checked_pong(self, *args, **kwargs)
        except LoginVerificationPaused:
            if verification is None:
                raise
            await verification.ensure_window()
            # The old HTTP request has unwound; native cookies must refresh before a new pong.
            await self.update_cookies(browser_context=crawler.browser_context, urls=crawler.cookie_urls)
            return False
        if verified is True:
            if platform == 'bili' and not store.status(session_id).get('browser_connection'):
                # Close while the native Playwright manager still owns its driver.
                try:
                    await asyncio.wait_for(crawler.browser_context.close(), timeout=10)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    store._update(session_id, platform, lambda value: value.update(
                        login_persistence_status='context_close_failed'))
                    raise LoginFlowError('login_browser_persistence_failed') from None
                store._update(session_id, platform, lambda value: value.update(
                    login_persistence_status='context_closed_before_driver_exit'))
            raise LoginVerified()
        return False
    client_class.pong = verified_pong
    missing = {'qr': False}
    finder = 'find_qrcode_img_from_canvas' if platform == 'zhihu' else 'find_login_qrcode'
    original_finder = getattr(utilities, finder, None)
    if original_finder:
        async def find(*args, **kwargs):
            value = await original_finder(*args, **kwargs)
            missing['qr'] = not bool(value)
            return value
        setattr(utilities, finder, find)
    native_begin = login_class.begin
    async def begin(self):
        page = crawler.context_page
        if page.is_closed():
            raise LoginFlowError('login_browser_closed')
        await page.bring_to_front()
        store._update(session_id, platform, lambda value: value.update(
            login_flow='native_original_browser', login_wait_reason='native_qr_preparation', login_page_ready=True))
        async def native_result():
            try:
                await native_begin(self)
            except SystemExit as error:
                return error
        try:
            # Native cookie polling can wait 120/600 rounds; retain time for authenticated self-check.
            window_deadline = verification.deadline if verification else deadline
            native_exit = await asyncio.wait_for(native_result(), timeout=min(30, max(.01, window_deadline-time.monotonic())))
            if native_exit is not None:
                raise native_exit
        except SystemExit as error:
            if error.code not in (None, 0):
                raise
            reason = 'qr_missing' if missing['qr'] else 'native_qr_wait_ended'
        except Exception as error:
            if type(error).__name__ != 'TimeoutError':
                raise
            reason = 'qr_element_unavailable'
        else:
            reason = 'native_login_requires_verification'
        if page.is_closed():
            raise LoginFlowError('login_browser_closed')
        await page.bring_to_front()
        if platform == 'zhihu':
            await page.goto('https://www.zhihu.com/signin', wait_until='domcontentloaded')
        store.observe(session_id, platform, 'waiting_login')
        store._update(session_id, platform, lambda value: value.update(
            login_flow='manual_original_browser', login_wait_reason='verification_paused' if verification and verification.paused else reason, login_page_ready=True))
        client = getattr(crawler, {'zhihu': 'zhihu_client', 'ks': 'ks_client', 'xhs': 'xhs_client', 'bili': 'bili_client'}[platform])
        while verification or time.monotonic() < deadline:
            if (store.root / session_id / 'login-stop').exists():
                raise LoginFlowError('login_user_cancelled')
            if page.is_closed():
                raise LoginFlowError('login_browser_closed')
            if verification:
                await verification.ensure_window()
            # Native update_cookies hook invokes the original authenticated pong.
            await client.update_cookies(browser_context=crawler.browser_context, urls=crawler.cookie_urls)
            window_deadline = verification.deadline if verification else deadline
            await asyncio.sleep(min(20, max(0, window_deadline - time.monotonic())))
        raise LoginFlowError('login_user_timeout')
    login_class.begin = begin


async def login_worker(args):
    """Use MC's visible human-login path with every content-collection entry disabled."""
    deadline = time.monotonic() + 180
    store = AccountSessions(args.root)
    verification = LoginVerificationWindow(store, args.session_id, args.platform, deadline) if args.platform in ('zhihu', 'ks', 'xhs', 'bili') else None
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
        install_hooks(args.root, args.session_id, args.platform, None, event,
                      interactive_login=args.platform in ('zhihu', 'ks', 'xhs', 'bili'))
        from playwright.async_api import BrowserType
        original = BrowserType.launch_persistent_context
        async def persistent(self, *a, **kw):
            if self.name == 'chromium' and not Path(self.executable_path).is_file():
                kw['executable_path'] = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
            profile = a[0] if a else kw.get('user_data_dir')
            kw = _preserve_bound_xhs_bridge(args.root, args.session_id, args.platform, self.name, profile, kw)
            return await original(self, *a, **kw)
        BrowserType.launch_persistent_context = persistent
        from browser_session import install_browser_reuse
        install_browser_reuse(store,args.session_id,args.platform,BrowserType,crawler_class)
        import httpx
        send = httpx.AsyncClient.send
        attempts = 0
        async def bounded_send(self, *a, **kw):
            nonlocal attempts
            if verification:
                await verification.before_request()
            else:
                attempts += 1
                if attempts > 8: raise LoginFlowError('login_request_budget_exhausted')
            try:
                response = await send(self, *a, **kw)
            except Exception as error:
                if args.platform == 'bili' and verification:
                    _record_bili_self_diagnostic(store, args.session_id, a[0] if a else kw.get('request'), verification, error=error)
                raise
            if args.platform == 'bili' and verification:
                _record_bili_self_diagnostic(store, args.session_id, a[0] if a else kw.get('request'), verification, response=response)
            if args.platform == 'ks' and store.status(args.session_id).get('state') == 'checking':
                store._update(args.session_id, args.platform, lambda value: value['login_diagnostic'].update(
                    **_ks_response_diagnostic(response), round=verification.round, attempt=verification.attempts))
            return response
        httpx.AsyncClient.send = bounded_send
        crawler = crawler_class()
        install_manual_login_fallback(crawler, store, args.session_id, args.platform, deadline, verification=verification)
        task = asyncio.create_task(crawler.start())
        try:
            while not task.done():
                if verification and time.monotonic() > verification.deadline:
                    verification.pause()
                elif verification is None and time.monotonic() > deadline:
                    task.cancel(); raise LoginFlowError('login_user_timeout')
                if verification and getattr(crawler, 'context_page', None) and crawler.context_page.is_closed():
                    task.cancel(); raise LoginFlowError('login_browser_closed')
                if (folder / 'login-stop').exists():
                    task.cancel(); raise LoginFlowError('login_user_cancelled')
                await asyncio.sleep(.5)
            try:
                await task
            except LoginVerified:
                pass
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            if getattr(crawler, 'browser_context', None):
                with contextlib.suppress(Exception):
                    await crawler.browser_context.close()
            store._update(args.session_id, args.platform, lambda value: value.update(
                login_page_ready=False, login_verification_paused=False))


def record_login_failure(root, session_id, platform, error):
    """Report a fixed error category, never upstream exception text or credentials."""
    store = AccountSessions(root)
    status = store.status(session_id)
    if status['state'] in ('resumed', 'authenticated', 'account_changed', 'identity_unverified'):
        return
    name = type(error).__name__
    code = (error.code if isinstance(error, LoginFlowError) else
            'login_browser_timeout' if name == 'TimeoutError' else
            'login_browser_closed' if name == 'TargetClosedError' else
            'login_dependency_missing' if isinstance(error, (ImportError, FileNotFoundError)) else
            'login_flow_ended_before_verification' if isinstance(error, SystemExit) else
            'login_executor_failed')
    store.observe(session_id, platform, 'check_failed')
    store._update(session_id, platform, lambda value: value.update(login_error_code=code))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True); parser.add_argument('--mc-root', required=True)
    parser.add_argument('--session-id', required=True); parser.add_argument('--platform', choices=sorted(PLATFORMS), required=True)
    parser.add_argument('--lock-fd', type=int, required=True); parser.add_argument('action', choices=['_login_worker'])
    arguments = parser.parse_args()
    try:
        asyncio.run(login_worker(arguments))
    except BaseException as error:
        record_login_failure(arguments.root, arguments.session_id, arguments.platform, error)
    finally:
        os.close(arguments.lock_fd)
