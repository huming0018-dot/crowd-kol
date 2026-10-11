import asyncio
import fcntl
import json
from pathlib import Path
import tempfile
import os
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid

from account_sessions import AccountSessions, guard_auth_response, install_hooks, own_account_id
from owner_tasks import OwnerTasks


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.sid, self.rid = str(uuid.uuid4()), str(uuid.uuid4())
        session = self.root / 'sessions' / self.sid
        session.mkdir(parents=True)
        (session / 'identity.json').write_text(json.dumps({'platform': 'wb'}))
        (session / 'browser_data').mkdir()
        self.private = session / 'browser_data' / 'untouched'; self.private.write_text('not-read-by-account-module')
        self.store = AccountSessions(self.root)

    def tearDown(self):
        self.assertEqual(self.private.read_text(), 'not-read-by-account-module')
        self.temp.cleanup()

    def authenticated(self, uid='old-user'):
        self.store.observe(self.sid, 'wb', 'checking', self.rid)
        return self.store.observe(self.sid, 'wb', 'authenticated', self.rid, uid)

    def test_unverified_not_inferred_from_profile_and_platform_ids_not_guessed(self):
        self.assertEqual(self.store.status(self.sid)['state'], 'unverified')
        self.assertEqual(len(self.store.list()['sessions']), 1)
        with self.assertRaisesRegex(ValueError, 'session_platform_mismatch'):
            self.store.status(self.sid, 'xhs')
        with self.assertRaises(ValueError): self.store.status('../private')
        self.assertFalse((self.root / 'accounts').exists())

    def test_same_identity_resumes_exact_original_run(self):
        first = self.authenticated()
        self.store.observe(self.sid, 'wb', 'logged_out', self.rid)
        self.store.observe(self.sid, 'wb', 'waiting_login', self.rid)
        self.store.observe(self.sid, 'wb', 'checking')
        restored = self.store.observe(self.sid, 'wb', 'authenticated', account_id='old-user')
        self.assertEqual(restored['state'], 'resumed')
        self.assertEqual(restored['generation'], first['generation'])
        self.assertEqual(restored['authorized_for_run'], self.rid)
        self.assertNotIn('old-user', json.dumps(restored))

    def test_new_account_cannot_inherit_prior_authorization(self):
        self.authenticated()
        changed = self.store.observe(self.sid, 'wb', 'authenticated', self.rid, 'new-user')
        self.assertEqual(changed['state'], 'account_changed')
        self.assertIsNone(changed['authorized_for_run'])
        with self.assertRaisesRegex(ValueError, 'account_confirmation_not_available'):
            self.store.confirm_same_account(self.sid, changed['generation'], True)
        with self.assertRaisesRegex(ValueError, 'explicit_new_account_scope_required'):
            self.store.accept_account_switch(self.sid, changed['generation'])
        accepted = self.store.accept_account_switch(self.sid, changed['generation'], True)
        self.assertIsNone(accepted['authorized_for_run']); self.assertIsNone(accepted['pending_run_id'])
        self.assertEqual(accepted['identity_status'], 'explicitly_accepted_new_account')

    def test_missing_identity_needs_explicit_same_account_confirmation_on_recovery(self):
        self.authenticated(uid=None)
        self.store.observe(self.sid, 'wb', 'logged_out', self.rid)
        self.store.observe(self.sid, 'wb', 'checking')
        checked = self.store.observe(self.sid, 'wb', 'authenticated')
        self.assertEqual(checked['state'], 'identity_unverified')
        with self.assertRaises(ValueError): self.store.confirm_same_account(self.sid, checked['generation'])
        with self.assertRaisesRegex(ValueError, 'account_generation_changed'):
            self.store.confirm_same_account(self.sid, checked['generation'] + 1, True)
        confirmed = self.store.confirm_same_account(self.sid, checked['generation'], True)
        self.assertEqual(confirmed['state'], 'resumed'); self.assertEqual(confirmed['authorized_for_run'], self.rid)

    def test_original_account_can_return_without_assigning_new_account_scope(self):
        self.authenticated()
        changed = self.store.observe(self.sid, 'wb', 'authenticated', self.rid, 'other-user')
        repeated = self.store.observe(self.sid, 'wb', 'authenticated', self.rid, 'other-user')
        self.assertEqual(changed['generation'], repeated['generation'])
        self.store.observe(self.sid, 'wb', 'checking')
        restored = self.store.observe(self.sid, 'wb', 'authenticated', account_id='old-user')
        self.assertEqual(restored['state'], 'resumed')
        self.assertEqual(restored['authorized_for_run'], self.rid)

    def test_network_failure_recovery_requires_fresh_same_account_confirmation(self):
        self.authenticated(uid=None)
        self.store.observe(self.sid, 'wb', 'check_failed', self.rid)
        self.assertIsNone(self.store.status(self.sid)['authorized_for_run'])
        self.store.observe(self.sid, 'wb', 'checking')
        recovered = self.store.observe(self.sid, 'wb', 'authenticated')
        self.assertEqual(recovered['state'], 'identity_unverified')
        with patch('account_sessions.time.time', return_value=recovered['verified_at'] + 181):
            with self.assertRaisesRegex(ValueError, 'account_login_check_stale'):
                self.store.confirm_same_account(self.sid, recovered['generation'], True)
        self.assertIsNone(self.store.status(self.sid)['authorized_for_run'])
        confirmed = self.store.confirm_same_account(self.sid, recovered['generation'], True)
        self.assertEqual(confirmed['authorized_for_run'], self.rid)

    def test_existing_pong_and_native_login_update_hook(self):
        events = []
        class Client:
            logged_in = True
            async def request(self): return {'uid': 'old-user'}
            async def pong(self):
                await self.request()
                return self.logged_in
            async def update_cookies(self): self.logged_in = True
        install_hooks(self.root, self.sid, 'wb', self.rid,
                      lambda state, value: events.append(state), client_class=Client)
        async def check():
            client = Client()
            self.assertTrue(await client.pong())
            client.logged_in = False
            self.assertFalse(await client.pong())
            self.assertEqual(self.store.status(self.sid)['state'], 'waiting_login')
            await client.update_cookies()
            self.assertEqual(self.store.status(self.sid)['state'], 'resumed')
        asyncio.run(check())
        self.assertIn('logged_out', events); self.assertIn('checking', events); self.assertIn('resumed', events)

    def test_check_failure_not_mislabeled_logout_and_headless_stops(self):
        class Client:
            async def request(self): raise OSError('synthetic network failure')
            async def pong(self):
                try: await self.request()
                except OSError: return False
            async def update_cookies(self): pass
        install_hooks(self.root, self.sid, 'wb', self.rid, lambda *_: None, client_class=Client)
        with self.assertRaises(SystemExit) as error: asyncio.run(Client().pong())
        self.assertEqual(error.exception.code, 77)
        self.assertEqual(self.store.status(self.sid)['state'], 'check_failed')

    def test_runtime_changed_identity_stops_before_collecting(self):
        self.authenticated()
        class Client:
            async def request(self): return {'uid': 'another-account'}
            async def pong(self): await self.request(); return True
            async def update_cookies(self): pass
        install_hooks(self.root, self.sid, 'wb', self.rid, lambda *_: None, client_class=Client)
        with self.assertRaises(SystemExit) as error: asyncio.run(Client().pong())
        self.assertEqual(error.exception.code, 78)
        self.assertEqual(self.store.status(self.sid)['state'], 'account_changed')

    def test_explicit_auth_response_stops_but_cdn_failure_does_not(self):
        self.authenticated()
        response = SimpleNamespace(request=SimpleNamespace(url='https://cdn.other.test/file'), status_code=401)
        guard_auth_response(self.store, self.sid, 'wb', self.rid, lambda *_: None, response)
        self.assertEqual(self.store.status(self.sid)['state'], 'authenticated')
        response.request.url = 'https://m.weibo.cn/api/test'
        with self.assertRaises(SystemExit) as error:
            guard_auth_response(self.store, self.sid, 'wb', self.rid, lambda *_: None, response)
        self.assertEqual(error.exception.code, 77)
        self.assertEqual(self.store.status(self.sid)['state'], 'logged_out')

    def test_login_open_is_exclusive_no_collection_and_cancel_only_marker(self):
        mc = self.root / 'fake-mc'; (mc / '.venv/bin').mkdir(parents=True)
        (mc / '.venv/bin/python').write_text('fixture'); (mc / 'main.py').write_text('fixture')
        lock_path = self.root / 'sessions' / self.sid / 'active.lock'
        with open(lock_path, 'a+') as lock, patch('account_sessions.subprocess.Popen') as spawn:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, 'session_busy'): self.store.open_login(self.sid, 'wb', mc)
            spawn.assert_not_called()
        with patch('account_sessions.subprocess.Popen', return_value=SimpleNamespace(pid=12345)) as spawn:
            opened = self.store.open_login(self.sid, 'wb', mc)
            self.assertFalse(opened['source_collection_started'])
            self.assertIn('_login_worker', spawn.call_args.args[0])
            self.assertEqual(len(spawn.call_args.kwargs['pass_fds']), 1)
        self.assertTrue(self.store.cancel_login(self.sid)['cancel_requested'])
        self.assertTrue((self.root / 'accounts' / self.sid / 'login-stop').exists())

    def test_self_identity_whitelist_does_not_use_target_authors_or_credentials(self):
        self.assertEqual(own_account_id('bili', {'mid': 123}), 123)
        self.assertIsNone(own_account_id('wb', {'author': {'uid': 'target'}, 'access_token': 'private'}))
        self.assertIsNone(own_account_id('dy', {'uid': 'not-a-supported-self-field'}))

    def test_actual_login_worker_process_disables_collection_and_preserves_original_profile(self):
        self.authenticated()
        mc = self.root / 'login-executor'
        for path in ('.venv/bin', 'libs', 'playwright', 'media_platform/weibo', 'media_platform/kuaishou/graphql'):
            (mc / path).mkdir(parents=True)
        (mc / '.venv/bin/python').symlink_to(sys.executable)
        (mc / 'config.py').write_text('')
        (mc / 'playwright/__init__.py').write_text('')
        (mc / 'playwright/async_api.py').write_text('class BrowserType:\n async def launch_persistent_context(self,*a,**kw): pass\n')
        (mc / 'httpx.py').write_text('class AsyncClient:\n async def send(self,*a,**kw): pass\n')
        (mc / 'media_platform/weibo/client.py').write_text('''class WeiboClient:
 logged_in=False
 async def request(self): return {'uid':'old-user'}
 async def pong(self): await self.request();return self.logged_in
 async def update_cookies(self): pass
''')
        (mc / 'main.py').write_text('''from pathlib import Path
from media_platform.weibo.client import WeiboClient
class Context:
 async def close(self): pass
class Crawler:
 def __init__(self): self.browser_context=Context()
 async def search(self): Path('SOURCE_COLLECTION_SENTINEL').touch()
 async def start(self):
  assert Path('libs').is_dir() and Path('media_platform/kuaishou/graphql').is_dir()
  assert Path('browser_data/untouched').read_text()=='not-read-by-account-module'
  client=WeiboClient()
  if not await client.pong():
   client.logged_in=True
   await client.update_cookies()
  await self.search()
class CrawlerFactory:
 CRAWLERS={'wb':Crawler}
''')
        opened = self.store.open_login(self.sid, 'wb', mc)
        _, result = os.waitpid(opened['login_worker_pid'], 0)
        self.assertEqual(result, 0)
        checked = self.store.status(self.sid)
        self.assertEqual(checked['state'], 'resumed')
        self.assertEqual(checked['authorized_for_run'], self.rid)
        self.assertFalse(list((self.root / 'accounts').rglob('SOURCE_COLLECTION_SENTINEL')))


class RecoveryTests(unittest.TestCase):
    def test_owner_login_resume_requires_same_original_run_and_keeps_remaining_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            sid, old_rid, new_rid = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
            calls = []; checked = {'ok': False}; phase = 'login_required'
            def runner(action, payload):
                calls.append((action, payload))
                if action == 'start':
                    rid = old_rid if not any(a == 'start' for a, _ in calls[:-1]) else new_rid
                    return {'ok': True, 'result': {'run_id': rid}}
                if action == 'status': return {'ok': True, 'result': {'state': phase, 'api_attempts': 1, 'account_state': 'logged_out'}}
                if action == 'import': return {'ok': True, 'result': {'records': []}}
                if action == 'account_status': return checked
                return {'ok': True, 'result': {'runs': []}}
            service = OwnerTasks(temp, runner); service._ensure_thread = lambda: None
            try:
                task = service.create({'platforms': ['wb'], 'mode': 'detail', 'targets_by_platform': {'wb': ['123']},
                    'session_by_platform': {'wb': sid}, 'desired_items': 1, 'max_api_requests': 4,
                    'purpose': 'noncommercial_research', 'idempotency_key': 'recovery'})['task']
                service.poll(); service.poll()
                service.resume(task['task_id']); service.poll()
                self.assertEqual(sum(a == 'start' for a, _ in calls), 1)
                checked = {'ok': True, 'state': 'resumed', 'authorized_for_run': new_rid, 'generation': 1,
                           'login_verified': True, 'verified_at': time.time()}
                service.poll(); self.assertEqual(sum(a == 'start' for a, _ in calls), 1)
                checked['authorized_for_run'] = old_rid
                phase = 'running'; service.poll()
                starts = [p for a, p in calls if a == 'start']
                self.assertEqual(len(starts), 2); self.assertEqual(starts[-1]['max_api_requests'], 3)
                self.assertEqual(starts[-1]['session_id'], sid)
            finally: service.close()


if __name__ == '__main__': unittest.main()
