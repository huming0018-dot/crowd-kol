import asyncio,contextlib,json,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import account_sessions as a

class CloseOrderTests(unittest.TestCase):
 def fixture(self,platform='bili',verified=True,binding=None,close_error=None):
  t=tempfile.TemporaryDirectory(dir='/private/tmp');self.addCleanup(t.cleanup);root=Path(t.name)
  store=a.AccountSessions(root);sid='11111111-1111-4111-8111-111111111111'
  session=root/'sessions'/sid;session.mkdir(parents=True);(session/'identity.json').write_text(json.dumps({'platform':platform}))
  store._update(sid,platform,lambda v:v.update(state='resumed',login_verified=True,pending_run_id='original',authorized_for_run='original',**({'browser_connection':binding} if binding else {})))
  trace=[]
  class Client:
   async def pong(self):trace.append('official_pong');return verified
  class Login:
   async def begin(self):return None
  class Context:
   async def close(self):
    trace.append('context_close')
    if close_error:raise close_error
  crawler=SimpleNamespace(context_page=SimpleNamespace(is_closed=lambda:False,bring_to_front=self.noop),browser_context=Context())
  a.install_manual_login_fallback(crawler,store,sid,platform,time.monotonic()+180,Login,Client,SimpleNamespace())
  return store,sid,Client(),trace
 async def noop(self):pass
 def test_close_before_native_manager_exit(self):
  store,sid,client,trace=self.fixture()
  @contextlib.asynccontextmanager
  async def manager():
   try:yield
   finally:trace.append('native_manager_exit')
  async def run():
   async with manager():await client.pong()
  with self.assertRaises(a.LoginVerified):asyncio.run(run())
  self.assertEqual(trace,['official_pong','context_close','native_manager_exit'])
  self.assertEqual(store.status(sid)['login_persistence_status'],'context_closed_before_driver_exit')
 def test_unverified_does_not_close(self):
  store,sid,c,trace=self.fixture(verified=False);self.assertFalse(asyncio.run(c.pong()));self.assertEqual(trace,['official_pong'])
 def test_other_platforms_unchanged(self):
  for platform in ('xhs','zhihu','ks'):
   store,sid,c,trace=self.fixture(platform)
   with self.assertRaises(a.LoginVerified):asyncio.run(c.pong())
   self.assertNotIn('context_close',trace)
 def test_borrowed_browser_not_closed(self):
  store,sid,c,trace=self.fixture(binding={'mode':'existing_cdp'})
  with self.assertRaises(a.LoginVerified):asyncio.run(c.pong())
  self.assertNotIn('context_close',trace)
 def test_close_failure_preserves_self_proof_but_not_persistence(self):
  store,sid,c,trace=self.fixture(close_error=OSError('SECRET_PATH_COOKIE'))
  with self.assertRaises(a.LoginFlowError) as e:asyncio.run(c.pong())
  self.assertEqual(e.exception.code,'login_browser_persistence_failed');v=store.status(sid);self.assertTrue(v['login_verified']);self.assertEqual(v['authorized_for_run'],'original');self.assertEqual(v['pending_run_id'],'original');self.assertEqual(v['login_persistence_status'],'context_close_failed');self.assertNotIn('SECRET',json.dumps(v))
 def test_timeout_is_bounded(self):
  store,sid,c,trace=self.fixture();original=asyncio.wait_for
  async def timeout(coro,timeout):
   self.assertEqual(timeout,10);coro.close();raise asyncio.TimeoutError()
  with patch.object(a.asyncio,'wait_for',timeout),self.assertRaises(a.LoginFlowError):asyncio.run(c.pong())
  self.assertTrue(store.status(sid)['login_verified']);self.assertEqual(store.status(sid)['login_persistence_status'],'context_close_failed')
 def test_cancellation_not_converted(self):
  store,sid,c,trace=self.fixture(close_error=asyncio.CancelledError())
  with self.assertRaises(asyncio.CancelledError):asyncio.run(c.pong())
  self.assertNotIn('login_persistence_status',store.status(sid))
 def test_system_exit_not_converted(self):
  store,sid,c,trace=self.fixture(close_error=SystemExit(73))
  with self.assertRaises(SystemExit) as e:asyncio.run(c.pong())
  self.assertEqual(e.exception.code,73)

if __name__=='__main__':unittest.main()
