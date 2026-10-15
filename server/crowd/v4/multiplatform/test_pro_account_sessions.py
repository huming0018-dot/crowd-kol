import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
import uuid
from account_sessions import AccountSessions, safe_account_ref
from pro_account_sessions import install_pro_account_hooks, self_proof


class ProAccountTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.sid, self.rid = str(uuid.uuid4()), str(uuid.uuid4())
        self.events = []
        self.hook = None

    def tearDown(self):
        if self.hook:
            self.hook.restore()
        self.temp.cleanup()

    def fixture(self, platform='bili', payload=None, fail=None, native=True):
        session = self.root/'sessions'/self.sid
        session.mkdir(parents=True)
        (session/'identity.json').write_text(json.dumps({'platform': platform}))
        (session/'outbox.json').write_text('ORIGINAL_OUTBOX')
        self.store = AccountSessions(self.root)
        url = {'bili': 'https://api.bilibili.com/x/web-interface/nav',
               'xhs': 'https://edith.xiaohongshu.com/api/sns/web/v2/user/me',
               'dy': 'https://www.douyin.com/aweme/v1/web/history/read/'}[platform]
        response = SimpleNamespace(url=url, status_code=200, json=lambda: payload)
        calls = []
        class HTTP:
            async def send(self, request):
                calls.append(request)
                if fail:
                    raise fail
                return response
        class SDK:
            async def pong(self):
                try:
                    await HTTP().send(url)
                    return native
                except Exception:
                    return False
        self.hook = install_pro_account_hooks(self.root, self.sid, platform, self.rid,
            lambda state, data: self.events.append((state, data)), SimpleNamespace(AsyncClient=HTTP), SDK)
        return SDK(), calls, response

    def run_pong(self, client, exit_code=None):
        if exit_code:
            with self.assertRaises(SystemExit) as e:
                asyncio.run(client.pong())
            self.assertEqual(e.exception.code, exit_code)
        else:
            self.assertTrue(asyncio.run(client.pong()))
        self.assertEqual((self.root/'sessions'/self.sid/'outbox.json').read_text(), 'ORIGINAL_OUTBOX')

    def test_same_original_run_logout_login(self):
        client, _, response = self.fixture(payload={'code': 0, 'data': {'isLogin': True, 'mid': 123}})
        self.run_pong(client)
        response.json = lambda: {'code': 0, 'data': {'isLogin': False}}
        self.run_pong(client, 77)
        state = self.store.status(self.sid)
        self.assertEqual(state['state'], 'logged_out')
        self.assertEqual(state['pending_run_id'], self.rid)
        response.json = lambda: {'code': 0, 'data': {'isLogin': True, 'mid': 123}}
        self.run_pong(client)
        state = self.store.status(self.sid)
        self.assertEqual((state['state'], state['authorized_for_run']), ('resumed', self.rid))
        self.assertNotIn('mid', json.dumps(self.events))

    def test_different_subject_refuses_old_run(self):
        client, _, response = self.fixture(payload={'code': 0, 'data': {'isLogin': True, 'mid': 123}})
        self.run_pong(client)
        response.json = lambda: {'code': 0, 'data': {'isLogin': True, 'mid': 456}}
        self.run_pong(client, 78)
        state = self.store.status(self.sid)
        self.assertEqual(state['state'], 'account_changed')
        self.assertIsNone(state['authorized_for_run'])
        self.assertEqual(state['account_ref'], safe_account_ref('bili', 123))

    def test_network_and_budget_not_logged_out(self):
        for error, code in [(ValueError('PRIVATE_COOKIE'), 77), (SystemExit(73), 73)]:
            with self.subTest(error=type(error).__name__):
                if self.hook:
                    self.hook.restore(); self.hook = None
                self.sid = str(uuid.uuid4())
                client, _, _ = self.fixture(fail=error)
                self.run_pong(client, code)
                self.assertEqual(self.store.status(self.sid)['state'], 'check_failed')
                self.assertNotIn('PRIVATE_COOKIE', json.dumps(self.events))

    def test_reporting_failure_never_replaces_original_budget_or_cancellation(self):
        for original in [SystemExit(73), asyncio.CancelledError()]:
            for target in ['event', 'store']:
                with self.subTest(original=type(original).__name__, target=target):
                    if self.hook:
                        self.hook.restore(); self.hook = None
                    self.sid = str(uuid.uuid4())
                    client, _, _ = self.fixture(fail=original)
                    if target == 'event':
                        def event(state, _):
                            if state == 'check_failed':
                                raise OSError('SYNTHETIC_DIAGNOSTIC_FAILURE')
                        self.hook.event = event
                    else:
                        observe = self.hook.store.observe
                        def failing_observe(session, platform, state, *args, **kwargs):
                            if state == 'check_failed':
                                raise OSError('SYNTHETIC_DIAGNOSTIC_FAILURE')
                            return observe(session, platform, state, *args, **kwargs)
                        self.hook.store.observe = failing_observe
                    async def verify_inside_task():
                        try:
                            await client.pong()
                        except BaseException as error:
                            self.assertIs(error, original)
                            raise
                    # asyncio.run normalizes task cancellation at its boundary.
                    with self.assertRaises(type(original)):
                        asyncio.run(verify_inside_task())

    def test_normal_authentication_store_failure_is_not_hidden(self):
        client, _, _ = self.fixture(payload={'code': 0, 'data': {'isLogin': True, 'mid': 123}})
        observe = self.hook.store.observe
        def failing_observe(session, platform, state, *args, **kwargs):
            if state == 'authenticated':
                raise OSError('SYNTHETIC_AUTH_STORE_FAILURE')
            return observe(session, platform, state, *args, **kwargs)
        self.hook.store.observe = failing_observe
        with self.assertRaisesRegex(OSError, 'SYNTHETIC_AUTH_STORE_FAILURE'):
            asyncio.run(client.pong())
        self.assertIsNone(self.store.status(self.sid)['authorized_for_run'])

    def test_dy_does_not_request_private_history(self):
        client, calls, _ = self.fixture('dy', {'status_code': 0})
        self.run_pong(client, 77)
        self.assertEqual(calls, [])
        self.assertEqual(self.store.status(self.sid)['state'], 'check_failed')

    def test_xhs_self_only_and_missing_identity(self):
        client, _, response = self.fixture('xhs', {'success': True, 'data': {'user_id': 'SELF_123'}})
        self.run_pong(client)
        response.url = 'https://edith.xiaohongshu.com/api/sns/web/v1/feed'
        response.json = lambda: {'success': True, 'data': {'user_id': 'AUTHOR_456'}}
        self.run_pong(client, 77)
        self.assertEqual(self.store.status(self.sid)['account_ref'], safe_account_ref('xhs', 'SELF_123'))

    def test_unknown_baseline_confirmation_binds_then_is_reused(self):
        client, _, _ = self.fixture(payload={'code': 0, 'data': {'isLogin': True, 'mid': 123}})
        self.store.observe(self.sid, 'bili', 'check_failed', self.rid)
        self.run_pong(client, 77)
        state = self.store.status(self.sid)
        self.assertEqual(state['state'], 'identity_unverified')
        self.assertEqual(state['unverified_account_ref'], safe_account_ref('bili', 123))
        self.store.confirm_same_account(self.sid, state['generation'], True)
        self.run_pong(client)
        state = self.store.status(self.sid)
        self.assertEqual(state['account_ref'], safe_account_ref('bili', 123))
        self.assertNotIn('unverified_account_ref', state)

    def test_expired_or_failed_check_clears_unconfirmed_ref(self):
        client, _, _ = self.fixture(payload={'code': 0, 'data': {'isLogin': True, 'mid': 123}})
        self.store.observe(self.sid, 'bili', 'check_failed', self.rid)
        self.run_pong(client, 77)
        state = self.store.status(self.sid)
        self.store._update(self.sid, 'bili', lambda v: v.update(verified_at=1))
        with self.assertRaisesRegex(ValueError, 'account_login_check_stale'):
            self.store.confirm_same_account(self.sid, state['generation'], True)
        self.assertNotIn('unverified_account_ref', self.store.status(self.sid))
        self.assertFalse(self.store.status(self.sid)['login_verified'])
        self.run_pong(client, 77)
        self.store.observe(self.sid, 'bili', 'check_failed', self.rid)
        self.assertNotIn('unverified_account_ref', self.store.status(self.sid))

    def test_native_success_without_self_identity_or_guest_is_not_proof(self):
        for payload in [{'code': False, 'data': {'isLogin': True, 'mid': 123}}, {'code': 0, 'data': {'isLogin': True}}, {'code': 0, 'data': {'isLogin': True, 'mid': 0}}]:
            response = SimpleNamespace(url='https://api.bilibili.com/x/web-interface/nav', status_code=200, json=lambda: payload)
            self.assertEqual(self_proof('bili', response)[0], 'check_failed')
        response = SimpleNamespace(url='https://edith.xiaohongshu.com/api/sns/web/v2/user/me', status_code=200, json=lambda: {'success': True, 'data': {'user_id': 'GUEST', 'guest': True}})
        self.assertEqual(self_proof('xhs', response)[0], 'check_failed')

    def test_spoofed_self_origin_or_status_rejected(self):
        for url in ['https://api.bilibili.com.evil/x/web-interface/nav', 'http://api.bilibili.com/x/web-interface/nav', 'https://api.bilibili.com:444/x/web-interface/nav', 'https://name:secret@api.bilibili.com/x/web-interface/nav']:
            self.assertEqual(self_proof('bili', SimpleNamespace(url=url, status_code=200, json=lambda: {'code': 0, 'data': {'isLogin': True, 'mid': 123}}))[0], 'check_failed')


if __name__ == '__main__':
    unittest.main()
