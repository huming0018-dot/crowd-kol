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

from account_sessions import (AccountSessions, guard_auth_response, install_hooks, own_account_id,
                             record_login_failure, install_manual_login_fallback, LoginVerified, LoginFlowError, LoginVerificationWindow, LoginVerificationPaused)
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

    def test_login_failure_reports_only_category_and_keeps_verified_account(self):
        record_login_failure(self.root,self.sid,'wb',RuntimeError('secret-cookie-value'))
        status=self.store.status(self.sid)
        self.assertEqual(status['state'],'check_failed')
        self.assertEqual(status['login_error_code'],'login_executor_failed')
        self.assertNotIn('secret-cookie-value',json.dumps(status))
        self.authenticated()
        self.store.confirm_same_account(self.sid,0,True)
        record_login_failure(self.root,self.sid,'wb',TimeoutError('private-token'))
        self.assertEqual(self.store.status(self.sid)['state'],'resumed')
        self.assertNotIn('private-token',json.dumps(self.store.status(self.sid)))

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

    def test_first_expired_session_preserves_zero_scope_until_human_confirmation(self):
        for account_id in (None, 'newly-observed-self-id'):
            with self.subTest(account_id_present=account_id is not None):
                self.store.observe(self.sid, 'wb', 'logged_out', self.rid)
                self.store.observe(self.sid, 'wb', 'checking')
                checked = self.store.observe(self.sid, 'wb', 'authenticated', account_id=account_id)
                self.assertEqual(checked['state'], 'identity_unverified')
                self.assertEqual(checked['generation'], 0)
                self.assertIsNone(checked.get('account_ref'))
                self.assertIsNone(checked['authorized_for_run'])
                confirmed = self.store.confirm_same_account(self.sid, 0, True)
                self.assertEqual(confirmed['generation'], 0)
                self.assertIsNone(confirmed.get('account_ref'))
                self.assertEqual(confirmed['identity_status'], 'manually_confirmed_same_account')
                self.assertEqual(confirmed['authorized_for_run'], self.rid)

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


class LoginFallbackTests(unittest.TestCase):
    def test_self_check_exception_and_401_keep_login_visible_but_source_remains_strict(self):
        for direct_error in (False,True):
            for interactive in (False,True):
                with self.subTest(direct=direct_error,interactive=interactive), tempfile.TemporaryDirectory() as temp:
                    root=Path(temp).resolve();sid=str(uuid.uuid4());session=root/'sessions'/sid;session.mkdir(parents=True)
                    (session/'identity.json').write_text('{"platform":"zhihu"}');(session/'browser_data').mkdir()
                    class Client:
                        async def request(self):raise ValueError('HTTP401 private-secret')
                        async def pong(self):
                            if direct_error:raise RuntimeError('private-secret')
                            try:await self.request()
                            except ValueError:return False
                        async def update_cookies(self,**kwargs):pass
                    store=install_hooks(root,sid,'zhihu',None,lambda *_:None,client_class=Client,interactive_login=interactive)
                    if interactive:
                        self.assertFalse(asyncio.run(Client().pong()))
                        value=store.status(sid);self.assertEqual(value['state'],'waiting_login')
                        self.assertFalse(value['login_verification_available']);self.assertIsNone(value['authorized_for_run'])
                        self.assertNotIn('private-secret',json.dumps(value))
                        self.assertFalse(asyncio.run(Client().update_cookies()) or False)
                    else:
                        with self.assertRaises(RuntimeError if direct_error else SystemExit):asyncio.run(Client().pong())

    def test_active_lock_status_does_not_use_pid_or_persist_stale_flag(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();sid=str(uuid.uuid4());session=root/'sessions'/sid;session.mkdir(parents=True)
            (session/'identity.json').write_text('{"platform":"zhihu"}');store=AccountSessions(root)
            self.assertFalse(store.status(sid)['login_in_progress'])
            with open(session/'active.lock','a+') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                self.assertTrue(store.status(sid)['login_in_progress'])
                store.observe(sid,'zhihu','waiting_login')
                self.assertNotIn('login_in_progress',json.loads((store.root/sid/'state.json').read_text()))
            self.assertFalse(store.status(sid)['login_in_progress'])

    def test_real_login_child_qr_exit_keeps_page_then_verifies_without_post_login_search(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();sid=str(uuid.uuid4());session=root/'sessions'/sid
            session.mkdir(parents=True);(session/'identity.json').write_text('{"platform":"zhihu"}')
            (session/'browser_data').mkdir();(session/'browser_data'/'untouched').write_text('original fixture profile')
            store=AccountSessions(root);store.observe(sid,'zhihu','authenticated',account_id='original')
            mc=root/'fake-native'
            for name in ['.venv/bin','libs','tools','playwright','media_platform/zhihu','media_platform/kuaishou/graphql']:(mc/name).mkdir(parents=True)
            (mc/'.venv/bin/python').symlink_to(sys.executable);(mc/'config.py').write_text('')
            (mc/'playwright/__init__.py').write_text('')
            (mc/'playwright/async_api.py').write_text('class BrowserType:\n async def launch_persistent_context(self,*a,**kw): pass\n')
            (mc/'httpx.py').write_text('class AsyncClient:\n async def send(self,*a,**kw): pass\n')
            (mc/'tools/utils.py').write_text('async def find_qrcode_img_from_canvas(*a,**kw): return None\n')
            (mc/'media_platform/zhihu/client.py').write_text("class ZhiHuClient:\n logged_in=False\n async def request(self):\n  if not self.logged_in: raise ValueError('HTTP401')\n  return {'uid':'original'}\n async def pong(self):\n  try: await self.request(); return self.logged_in\n  except ValueError: return False\n async def update_cookies(self,**kw): self.logged_in=True\n")
            (mc/'media_platform/zhihu/login.py').write_text('from tools import utils\nclass ZhiHuLogin:\n async def begin(self):\n  if not await utils.find_qrcode_img_from_canvas(): raise SystemExit()\n')
            (mc/'main.py').write_text('''from pathlib import Path
from media_platform.zhihu.client import ZhiHuClient
from media_platform.zhihu.login import ZhiHuLogin
class Page:
 def is_closed(self): return False
 async def bring_to_front(self): Path('ORIGINAL_PAGE_VISIBLE').touch()
 async def goto(self,url,**kw):
  assert url=='https://www.zhihu.com/signin'
  Path('OFFICIAL_SIGNIN_VISIBLE').touch()
class Context:
 async def __aenter__(self): return self
 async def __aexit__(self,*a): await self.close()
 async def close(self): Path('CLOSED_AFTER_VERIFICATION').touch()
class Crawler:
 cookie_urls=['https://www.zhihu.com']
 async def search(self): Path('SOURCE_COLLECTION_SENTINEL').touch()
 async def start(self):
  async with Context() as context:
   self.browser_context=context; self.context_page=Page(); self.zhihu_client=ZhiHuClient()
   if not await self.zhihu_client.pong(): await ZhiHuLogin().begin()
   Path('POST_LOGIN_SEARCH_NAVIGATION').touch()
   await self.search()
class CrawlerFactory: CRAWLERS={'zhihu':Crawler}
''')
            opened=store.open_login(sid,'zhihu',mc);_,status=os.waitpid(opened['login_worker_pid'],0)
            self.assertEqual(status,0);checked=store.status(sid);self.assertEqual(checked['state'],'resumed')
            self.assertTrue(list((root/'accounts').rglob('ORIGINAL_PAGE_VISIBLE')))
            self.assertTrue(list((root/'accounts').rglob('OFFICIAL_SIGNIN_VISIBLE')))
            self.assertFalse(list((root/'accounts').rglob('POST_LOGIN_SEARCH_NAVIGATION')))
            self.assertFalse(list((root/'accounts').rglob('SOURCE_COLLECTION_SENTINEL')))
            self.assertEqual((session/'browser_data'/'untouched').read_text(),'original fixture profile')

    def test_missing_native_qr_keeps_original_page_until_verified_with_no_collection(self):
        for platform in ('zhihu', 'ks'):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as temp:
                root=Path(temp).resolve();sid=str(uuid.uuid4());folder=root/'sessions'/sid
                folder.mkdir(parents=True);(folder/'identity.json').write_text(json.dumps({'platform':platform}))
                (folder/'browser_data').mkdir();store=AccountSessions(root)
                store.observe(sid,platform,'authenticated',account_id='original')
                calls=[];confirmations=[]
                class Page:
                    def is_closed(self):return False
                    async def bring_to_front(self):calls.append('front')
                    async def goto(self,url,**kwargs):calls.append(url)
                class Client:
                    logged_in=False
                    async def request(self):return {'uid':'original'}
                    async def pong(self):await self.request();return self.logged_in
                    async def update_cookies(self,**kwargs):pass
                async def finder(*args,**kwargs):return None
                utilities=SimpleNamespace(find_qrcode_img_from_canvas=finder,find_login_qrcode=finder)
                class Login:
                    async def begin(self):
                        await getattr(utilities,'find_qrcode_img_from_canvas' if platform=='zhihu' else 'find_login_qrcode')()
                        raise SystemExit()
                install_hooks(root,sid,platform,None,lambda *_:None,client_class=Client)
                client=Client();crawler=SimpleNamespace(context_page=Page(),browser_context=object(),cookie_urls=['official-home'])
                setattr(crawler,'zhihu_client' if platform=='zhihu' else 'ks_client',client)
                install_manual_login_fallback(crawler,store,sid,platform,time.monotonic()+5,Login,Client,utilities)
                async def human_action(_delay):
                    if store.status(sid)['state']=='identity_unverified':
                        self.assertIsNone(store.status(sid)['authorized_for_run'])
                        confirmations.append('person-confirms-original-account')
                        store.confirm_same_account(sid,store.status(sid)['generation'],True)
                    else:client.logged_in=True
                with patch('account_sessions.asyncio.sleep',human_action):
                    with self.assertRaises(LoginVerified):asyncio.run(Login().begin())
                checked=store.status(sid);self.assertEqual(checked['state'],'resumed')
                self.assertTrue(checked['login_page_ready']);self.assertEqual(checked['login_wait_reason'],'qr_missing')
                self.assertEqual(calls,['front','front','https://www.zhihu.com/signin'] if platform=='zhihu' else ['front','front'])
                if platform=='ks':self.assertEqual(len(confirmations),1)

    def test_native_120_or_600_wait_is_visible_before_poll_and_bounded(self):
        for platform,native_wait in [('zhihu',120),('ks',600)]:
            with self.subTest(platform=platform),tempfile.TemporaryDirectory() as temp:
                root=Path(temp).resolve();sid=str(uuid.uuid4());folder=root/'sessions'/sid;folder.mkdir(parents=True)
                (folder/'identity.json').write_text(json.dumps({'platform':platform}));(folder/'browser_data').mkdir()
                store=AccountSessions(root);events=[]
                class Page:
                    def is_closed(self):return False
                    async def bring_to_front(self):events.append('visible')
                    async def goto(self,url,**kwargs):events.append(url)
                class Client:
                    async def pong(self):return False
                    async def update_cookies(self,**kwargs):raise AssertionError('expired budget must not send')
                class Login:
                    async def begin(self):
                        value=store.status(sid)
                        self_outer.assertTrue(value['login_page_ready'])
                        self_outer.assertEqual(value['login_flow'],'native_original_browser')
                        self_outer.assertEqual(events,['visible'])
                        try:await asyncio.sleep(native_wait)
                        finally:events.append('native_cancelled')
                self_outer=self;crawler=SimpleNamespace(context_page=Page(),browser_context=object(),cookie_urls=[])
                setattr(crawler,'zhihu_client' if platform=='zhihu' else 'ks_client',Client())
                started=time.monotonic()
                install_manual_login_fallback(crawler,store,sid,platform,started+.05,Login,Client,SimpleNamespace())
                with self.assertRaises(LoginFlowError) as error:asyncio.run(Login().begin())
                self.assertEqual(error.exception.code,'login_user_timeout');self.assertLess(time.monotonic()-started,1)
                self.assertIn('native_cancelled',events);self.assertEqual(events.count('visible'),2)
                self.assertEqual(store.status(sid)['state'],'waiting_login')
                self.assertIsNone(store.status(sid).get('authorized_for_run'))

    def test_manual_timeout_cancel_dependency_and_auth_hard_stop_are_distinct(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();sid=str(uuid.uuid4());folder=root/'sessions'/sid;folder.mkdir(parents=True)
            (folder/'identity.json').write_text('{"platform":"zhihu"}');(folder/'browser_data').mkdir();store=AccountSessions(root)
            class Page:
                def is_closed(self):return False
                async def bring_to_front(self):pass
                async def goto(self,*args,**kwargs):pass
            class Client:
                async def pong(self):return False
                async def update_cookies(self,**kwargs):pass
            crawler=SimpleNamespace(context_page=Page(),browser_context=object(),cookie_urls=[],zhihu_client=Client())
            class Login:
                async def begin(self):raise SystemExit()
            install_manual_login_fallback(crawler,store,sid,'zhihu',time.monotonic()-1,Login,Client,SimpleNamespace())
            with self.assertRaises(LoginFlowError) as error:asyncio.run(Login().begin())
            self.assertEqual(error.exception.code,'login_user_timeout')
            record_login_failure(root,sid,'zhihu',error.exception)
            self.assertEqual(store.status(sid)['login_error_code'],'login_user_timeout')
            for failure,expected in [(ImportError('never log private-value'),'login_dependency_missing'),
                                     (LoginFlowError('login_request_budget_exhausted'),'login_request_budget_exhausted')]:
                record_login_failure(root,sid,'zhihu',failure);self.assertEqual(store.status(sid)['login_error_code'],expected)
                self.assertNotIn('private-value',json.dumps(store.status(sid)))
            class CancelLogin:
                async def begin(self):raise SystemExit()
            install_manual_login_fallback(crawler,store,sid,'zhihu',time.monotonic()+5,CancelLogin,Client,SimpleNamespace())
            (store.root/sid/'login-stop').touch()
            with self.assertRaises(LoginFlowError) as error:asyncio.run(CancelLogin().begin())
            self.assertEqual(error.exception.code,'login_user_cancelled')
            class HardStop:
                async def begin(self):raise SystemExit(78)
            install_manual_login_fallback(crawler,store,sid,'zhihu',time.monotonic()+5,HardStop,Client,SimpleNamespace())
            with self.assertRaises(SystemExit) as error:asyncio.run(HardStop().begin())
            self.assertEqual(error.exception.code,78)



class FreshCookiePauseTests(unittest.TestCase):
    def test_real_child_one_continue_refreshes_native_client_headers(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();sid=str(uuid.uuid4());session=root/'sessions'/sid
            session.mkdir(parents=True);(session/'identity.json').write_text('{"platform":"zhihu"}')
            (session/'browser_data').mkdir();(session/'browser_data/untouched').write_bytes(b'original')
            store=AccountSessions(root);store.observe(sid,'zhihu','authenticated',account_id='original')
            mc=root/'fake-native'
            for name in ['.venv/bin','libs','tools','playwright','media_platform/zhihu','media_platform/kuaishou/graphql']:(mc/name).mkdir(parents=True)
            (mc/'.venv/bin/python').symlink_to(sys.executable);(mc/'config.py').write_text('')
            (mc/'playwright/__init__.py').write_text('')
            (mc/'playwright/async_api.py').write_text('class BrowserType:\n async def launch_persistent_context(self,*a,**kw): pass\n')
            (mc/'tools/utils.py').write_text('async def find_qrcode_img_from_canvas(*a,**kw): return None\n')
            (mc/'httpx.py').write_text('''from pathlib import Path
class AsyncClient:
 async def send(self,headers):
  with Path('SYNTHETIC_REQUESTS').open('a') as log: log.write(headers['synthetic_auth']+'\\n')
  if headers['synthetic_auth']=='human-signed-in': return {'uid':'original'}
  raise ValueError('synthetic_unauthenticated')
''')
            (mc/'media_platform/zhihu/client.py').write_text('''from pathlib import Path
from httpx import AsyncClient
class ZhiHuClient:
 def __init__(self): self.headers={'synthetic_auth':'guest'}
 async def request(self):
  for _ in range(9):
   try: return await AsyncClient().send(headers=self.headers.copy())
   except ValueError: pass
  return None
 async def pong(self): return bool(await self.request())
 async def update_cookies(self,browser_context,urls):
  assert urls==['https://www.zhihu.com']
  self.headers={'synthetic_auth':browser_context.synthetic_cookie()}
  Path('NATIVE_COOKIE_REFRESH').touch()
''')
            (mc/'media_platform/zhihu/login.py').write_text('class ZhiHuLogin:\n async def begin(self): raise AssertionError("initial verification should resume directly")\n')
            (mc/'main.py').write_text('''from pathlib import Path
from media_platform.zhihu.client import ZhiHuClient
class Page:
 def is_closed(self): return False
 async def bring_to_front(self): Path('ORIGINAL_PAGE_VISIBLE').touch()
class Context:
 def synthetic_cookie(self): return 'human-signed-in' if Path('SYNTHETIC_HUMAN_LOGIN').exists() else 'guest'
 async def close(self): Path('CLOSED').touch()
class Crawler:
 cookie_urls=['https://www.zhihu.com']
 async def search(self): Path('SOURCE_COLLECTION_SENTINEL').touch()
 async def start(self):
  self.browser_context=Context();self.context_page=Page();self.zhihu_client=ZhiHuClient()
  await self.zhihu_client.pong()
  Path('POST_LOGIN_NAVIGATION').touch()
class CrawlerFactory: CRAWLERS={'zhihu':Crawler}
''')
            opened=store.open_login(sid,'zhihu',mc);pid=opened['login_worker_pid'];reaped=False
            try:
                deadline=time.monotonic()+5
                while time.monotonic()<deadline and not store.status(sid).get('login_verification_paused'):time.sleep(.02)
                self.assertTrue(store.status(sid).get('login_verification_paused'))
                work=next((root/'accounts'/sid).glob('login-*'))
                self.assertEqual((work/'SYNTHETIC_REQUESTS').read_text().splitlines(),['guest']*8)
                self.assertTrue(store.status(sid)['login_page_ready']);self.assertTrue(store.status(sid)['login_in_progress'])
                (work/'SYNTHETIC_HUMAN_LOGIN').touch();store.resume_verification(sid)
                deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    done,_=os.waitpid(pid,os.WNOHANG)
                    if done:reaped=True;break
                    time.sleep(.02)
                self.assertTrue(reaped,'one explicit continue must complete original identity verification')
                state=store.status(sid);self.assertEqual(state['state'],'resumed')
                self.assertEqual((state['login_verification_round'],state['login_verification_attempts']),(2,1))
                self.assertEqual((work/'SYNTHETIC_REQUESTS').read_text().splitlines(),['guest']*8+['human-signed-in'])
                self.assertTrue((work/'NATIVE_COOKIE_REFRESH').exists());self.assertFalse((work/'POST_LOGIN_NAVIGATION').exists())
                self.assertFalse((work/'SOURCE_COLLECTION_SENTINEL').exists())
                self.assertEqual((session/'browser_data/untouched').read_bytes(),b'original')
            finally:
                if not reaped:store.cancel_login(sid);os.waitpid(pid,0)


class VerificationPauseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.sid=str(uuid.uuid4());session=self.root/'sessions'/self.sid
        session.mkdir(parents=True);(session/'identity.json').write_text('{"platform":"zhihu"}')
        (session/'browser_data').mkdir();self.original=session/'browser_data/untouched';self.original.write_bytes(b'original profile')
        self.lock=open(session/'active.lock','a+');fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB);self.addCleanup(self.lock.close)
        self.store=AccountSessions(self.root);self.store.observe(self.sid,'zhihu','waiting_login')
        self.store._update(self.sid,'zhihu',lambda v:v.update(login_page_ready=True))

    def test_eight_checks_pause_without_reset_until_explicit_human_marker(self):
        async def run():
            budget=LoginVerificationWindow(self.store,self.sid,'zhihu',time.monotonic()+180)
            for _ in range(8):await budget.before_request()
            with self.assertRaises(LoginVerificationPaused):await budget.before_request()
            blocked=asyncio.create_task(budget.ensure_window())
            await asyncio.sleep(.03)
            state=self.store.status(self.sid)
            self.assertEqual(state['state'],'waiting_login');self.assertEqual(state['login_wait_reason'],'verification_paused')
            self.assertTrue(state['login_page_ready']);self.assertTrue(state['login_in_progress']);self.assertFalse(state['login_verified'])
            self.assertEqual(budget.attempts,8);self.assertEqual(budget.round,1);self.assertFalse(blocked.done())
            await asyncio.sleep(.03);self.assertFalse(blocked.done());self.assertEqual(budget.attempts,8)
            response=self.store.resume_verification(self.sid);self.assertTrue(response['verification_continue_requested'])
            await asyncio.wait_for(blocked,2)
            await budget.before_request()
            self.assertEqual((budget.attempts,budget.round,budget.paused),(1,2,False))
            self.assertIsNone(self.store.status(self.sid).get('authorized_for_run'))
            self.assertFalse((budget.folder/'login-verify-continue').exists())
        asyncio.run(run());self.assertEqual(self.original.read_bytes(),b'original profile')

    def test_180s_expiry_keeps_window_and_cancel_releases_wait(self):
        async def run():
            budget=LoginVerificationWindow(self.store,self.sid,'zhihu',time.monotonic()-1)
            with self.assertRaises(LoginVerificationPaused):await budget.before_request()
            blocked=asyncio.create_task(budget.ensure_window());await asyncio.sleep(.02)
            self.assertTrue(budget.paused);self.assertEqual(budget.attempts,0)
            self.assertTrue(self.store.status(self.sid)['login_page_ready'])
            self.store.cancel_login(self.sid)
            with self.assertRaises(LoginFlowError) as error:await asyncio.wait_for(blocked,2)
            self.assertEqual(error.exception.code,'login_user_cancelled');self.assertEqual(budget.round,1)
        asyncio.run(run())

    def test_resume_requires_actual_locked_paused_worker_and_refuses_symlink(self):
        with self.assertRaisesRegex(ValueError,'login_verification_not_paused'):self.store.resume_verification(self.sid)
        budget=LoginVerificationWindow(self.store,self.sid,'zhihu',0);budget.pause()
        marker=budget.folder/'login-verify-continue';marker.symlink_to(self.original)
        with self.assertRaisesRegex(ValueError,'unsafe_login_continue_marker'):self.store.resume_verification(self.sid)
        marker.unlink();fcntl.flock(self.lock,fcntl.LOCK_UN)
        with self.assertRaisesRegex(ValueError,'login_verification_not_paused'):self.store.resume_verification(self.sid)
        self.assertEqual(self.original.read_bytes(),b'original profile')

    def test_cancel_before_continue_consumed_reopen_clears_old_marker_under_lock(self):
        old=LoginVerificationWindow(self.store,self.sid,'zhihu',0);old.pause()
        self.store.resume_verification(self.sid);self.store.cancel_login(self.sid)
        marker=old.folder/'login-verify-continue';self.assertTrue(marker.exists())
        fcntl.flock(self.lock,fcntl.LOCK_UN)
        mc=self.root/'fake-mc';(mc/'.venv/bin').mkdir(parents=True)
        (mc/'.venv/bin/python').write_text('fixture');(mc/'main.py').write_text('fixture')
        def spawn(*args,**kwargs):
            self.assertFalse(marker.exists());self.assertFalse((old.folder/'login-stop').exists())
            with open(self.root/'sessions'/self.sid/'active.lock','a+') as other:
                with self.assertRaises(BlockingIOError):fcntl.flock(other,fcntl.LOCK_EX|fcntl.LOCK_NB)
            return SimpleNamespace(pid=12345)
        with patch('account_sessions.subprocess.Popen',side_effect=spawn):self.store.open_login(self.sid,'zhihu',mc)
        async def no_stale_round():
            new=LoginVerificationWindow(self.store,self.sid,'zhihu',time.monotonic()+180)
            for _ in range(8):await new.before_request()
            with self.assertRaises(LoginVerificationPaused):await new.before_request()
            waiter=asyncio.create_task(new.ensure_window());await asyncio.sleep(.03)
            self.assertFalse(waiter.done());self.assertEqual(new.round,1)
            self.store.cancel_login(self.sid)
            with self.assertRaises(LoginFlowError):await asyncio.wait_for(waiter,2)
        asyncio.run(no_stale_round())
        marker.symlink_to(self.original)
        with patch('account_sessions.subprocess.Popen',side_effect=spawn):self.store.open_login(self.sid,'zhihu',mc)
        self.assertFalse(marker.is_symlink());self.assertEqual(self.original.read_bytes(),b'original profile')

    def test_initial_selfcheck_retry_exhaustion_still_exposes_original_page(self):
        budget=LoginVerificationWindow(self.store,self.sid,'zhihu',time.monotonic()+180);events=[]
        self.store._update(self.sid,'zhihu',lambda value:value.update(login_page_ready=False))
        outer=self
        class Page:
            def is_closed(self):return False
            async def bring_to_front(self):events.append('front')
        class Client:
            async def pong(self):
                outer.assertTrue(outer.store.status(outer.sid)['login_page_ready'])
                for _ in range(9):await budget.before_request()
                return False
        class Login:
            async def begin(self):raise AssertionError('initial selfcheck is still waiting')
        crawler=SimpleNamespace(context_page=Page())
        install_manual_login_fallback(crawler,self.store,self.sid,'zhihu',budget.deadline,Login,Client,SimpleNamespace(),verification=budget)
        async def run():
            blocked=asyncio.create_task(Client().pong());await asyncio.sleep(.03)
            self.assertTrue(budget.paused);self.assertEqual(events,['front'])
            self.store.cancel_login(self.sid)
            with self.assertRaises(LoginFlowError) as error:await asyncio.wait_for(blocked,2)
            self.assertEqual(error.exception.code,'login_user_cancelled')
        asyncio.run(run())


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
