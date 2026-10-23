import asyncio,json,tempfile,unittest,uuid,sys,os
from pathlib import Path
from unittest.mock import patch
import httpx
from account_sessions import AccountSessions
from pro_login_recovery import verify,VerificationFailure
PRO=Path(__file__).resolve().parents[3]/'references/mediacrawler-pro-2026-10-14/MediaCrawlerPro-Python'
class Tests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name).resolve();self.sid=str(uuid.uuid4());self.run=str(uuid.uuid4());p=self.root/'sessions'/self.sid;p.mkdir(parents=True);(p/'identity.json').write_text(json.dumps({'platform':'bili'}));(p/'pro-binding.json').write_text(json.dumps({'platform':'bili','client_id':'synthetic-client','cookiebridge_url':'http://127.0.0.1:8274','sign_url':'http://127.0.0.1:8990'}));self.store=AccountSessions(self.root)
  a=self.store.observe(self.sid,'bili','authenticated',account_id='123');self.recovery={'run_id':self.run,'generation':1,'account_ref':a['account_ref']};self.store.observe(self.sid,'bili','checking',run_id=self.run,_expected_context={k:self.recovery[k] for k in ('generation','account_ref')});self.calls=[]
 def tearDown(self):self.t.cleanup()
 def go(self,proof=None,bridge=None,status=200,diagnostic=None,cancel_after=None):
  def respond(req):
   self.calls.append((req.method,req.url.host,req.url.path));data=(bridge or {'isok':True,'data':{'client_id':'synthetic-client','platform':'bili','valid':True,'cookies':'synthetic=notreal'}}) if req.url.host=='127.0.0.1' else (proof or {'code':0,'data':{'isLogin':True,'mid':123}})
   if cancel_after==len(self.calls):(self.store.root/self.sid/'login-stop').touch()
   return httpx.Response(status,json=data,request=req)
  with patch.object(httpx,'AsyncHTTPTransport',lambda **kw:httpx.MockTransport(respond)):
   return asyncio.run(verify(self.store,self.sid,self.recovery,{'root':str(PRO),'python':sys.executable},diagnostic))
 def test_original_sdk_same_subject_no_browser_and_2_http(self):
  out=self.go();self.assertEqual(out['authorized_for_run'],self.run);self.assertEqual(len(self.calls),2);self.assertEqual(self.calls,[('GET','127.0.0.1','/api/cookies/bili'),('GET','api.bilibili.com','/x/web-interface/nav')]);self.assertNotIn('login_wait_reason',self.store.status(self.sid))
 def test_pending_swap_between_baseline_and_observe_never_authorizes_other_run(self):
  original=self.store.observe;other=str(uuid.uuid4())
  def race(*args,**kw):
   if args[2]=='authenticated':self.store._update(self.sid,'bili',lambda v:v.update(pending_run_id=other))
   return original(*args,**kw)
  with patch.object(self.store,'observe',side_effect=race),self.assertRaises(ValueError):self.go()
  self.assertIsNone(self.store.status(self.sid)['authorized_for_run'])
 def test_current_diagnostic_has_only_this_methods_status_and_counts(self):
  diag={};self.go(diagnostic=diag);d=self.store.status(self.sid)['login_diagnostic'];self.assertEqual(d['method'],'pro_official_self');self.assertEqual(d['official_self_http_status'],200);self.assertEqual(d['official_self_business_code'],0);self.assertEqual(d['bridge_requests'],1);self.assertEqual(d['official_self_requests'],1)
 def test_other_subject_not_authorized(self):
  with self.assertRaises(VerificationFailure):self.go(proof={'code':0,'data':{'isLogin':True,'mid':456}})
  self.assertIsNone(self.store.status(self.sid)['authorized_for_run'])
 def test_official_logout_and_malformed_never_auth(self):
  for value in ({'code':-101},{'code':0,'data':{'isLogin':True}}, {'code':True,'data':{'isLogin':True,'mid':123}}):
   with self.subTest(value=value),self.assertRaises(VerificationFailure):self.go(proof=value)
   self.assertIsNone(self.store.status(self.sid)['authorized_for_run'])
 def test_bridge_unavailable_does_not_call_official(self):
  with self.assertRaises(SystemExit) as e:self.go(bridge={'isok':False,'biz_code':100})
  self.assertEqual(e.exception.code,86);self.assertEqual(len(self.calls),1);self.assertIsNone(self.store.status(self.sid)['authorized_for_run'])
 def test_launch_is_pro_child_not_mc_browser(self):
  import io
  from types import SimpleNamespace
  from pro_login_recovery import launch
  class Keep(io.BytesIO):
   def close(self):pass
  child=SimpleNamespace(pid=999999,stdin=Keep())
  with patch('pro_executor.task_installation',return_value={'root':str(PRO),'python':sys.executable}),patch('pro_executor.binding_for',return_value={}),patch('pro_login_recovery.subprocess.Popen',return_value=child) as spawn:
   result=launch(self.store,self.sid,'bili',self.recovery)
  args,kw=spawn.call_args;self.assertIn('pro_login_recovery.py',args[0][1]);self.assertFalse(result['browser_started']);self.assertFalse(result['source_collection_started']);self.assertIsNone(self.store.status(self.sid)['authorized_for_run']);self.assertEqual(json.loads(child.stdin.getvalue())['recovery'],self.recovery)
 def test_existing_api_dispatches_exact_pro_context(self):
  from dashboard import Application
  app=Application.__new__(Application);app.mc_root='unused';app.cloud_client=object();app._roots=lambda:[self.root]
  class Worker:
   def recover_cloud_login(inner,task,child,owner,callback):return callback(self.sid,'bili',self.recovery,'pro')
  app.cloud_worker=Worker()
  with patch('pro_login_recovery.launch',return_value={'ok':True,'browser_started':False}) as start:
   result=app.accounts('recover_cloud_login',{'task_id':str(uuid.uuid4()),'child_id':str(uuid.uuid4())})
  self.assertTrue(result['ok']);self.assertEqual(start.call_args.args[1:],(self.sid,'bili',self.recovery))
 def test_main_stdin_runs_whole_original_sdk_and_state_machine(self):
  import io
  from types import SimpleNamespace
  import pro_login_recovery as module
  calls=[]
  def respond(req):
   calls.append(req.url.host)
   data={'isok':True,'data':{'client_id':'synthetic-client','platform':'bili','valid':True,'cookies':'synthetic=notreal'}} if req.url.host=='127.0.0.1' else {'code':0,'data':{'isLogin':True,'mid':123}}
   return httpx.Response(200,json=data,request=req)
  fd=os.open('/dev/null',os.O_RDONLY);payload={'recovery':self.recovery,'installed':{'root':str(PRO),'python':sys.executable}}
  with patch.object(sys,'argv',['helper','--root',str(self.root),'--session-id',self.sid,'--lock-fd',str(fd)]),patch.object(sys,'stdin',SimpleNamespace(buffer=io.BytesIO(json.dumps(payload).encode()))),patch.object(httpx,'AsyncHTTPTransport',lambda **kw:httpx.MockTransport(respond)):module.main()
  self.assertEqual(calls,['127.0.0.1','api.bilibili.com']);d=self.store.status(self.sid);self.assertEqual(d['authorized_for_run'],self.run);self.assertEqual(d['login_diagnostic']['method'],'pro_official_self')
 def test_main_failure_replaces_old_mc_diagnostic(self):
  import io
  from types import SimpleNamespace
  import pro_login_recovery as module
  self.store._update(self.sid,'bili',lambda v:v.update(login_diagnostic={'http_status':200,'api_code':0}))
  async def failed(store,sid,recovery,installed,diagnostic):
   diagnostic.update(bridge_requests=1,official_self_requests=1,official_self_http_status=503)
   raise VerificationFailure('official_check_failed')
  fd=os.open('/dev/null',os.O_RDONLY)
  args=['helper','--root',str(self.root),'--session-id',self.sid,'--lock-fd',str(fd)]
  with patch.object(sys,'argv',args),patch.object(sys,'stdin',SimpleNamespace(buffer=io.BytesIO(json.dumps({'recovery':self.recovery,'installed':{}}).encode()))),patch.object(module,'verify',failed):module.main()
  d=self.store.status(self.sid);self.assertEqual(d['state'],'check_failed');self.assertEqual(d['login_diagnostic']['official_self_http_status'],503);self.assertNotIn('api_code',d['login_diagnostic']);self.assertEqual(d['login_diagnostic']['phase'],'failed')
 def test_main_failure_cannot_clear_newer_tasks_authorization(self):
  import io
  from types import SimpleNamespace
  import pro_login_recovery as module
  other=str(uuid.uuid4())
  async def failed(store,sid,recovery,installed,diagnostic):
   store._update(sid,'bili',lambda v:v.update(pending_run_id=other,authorized_for_run=other,state='authenticated'))
   raise VerificationFailure('official_check_failed')
  fd=os.open('/dev/null',os.O_RDONLY)
  with patch.object(sys,'argv',['helper','--root',str(self.root),'--session-id',self.sid,'--lock-fd',str(fd)]),patch.object(sys,'stdin',SimpleNamespace(buffer=io.BytesIO(json.dumps({'recovery':self.recovery,'installed':{}}).encode()))),patch.object(module,'verify',failed):module.main()
  d=self.store.status(self.sid);self.assertEqual(d['state'],'authenticated');self.assertEqual(d['authorized_for_run'],other)
 def test_cancel_after_bridge_or_official_blocks_authorization(self):
  for n in (1,2):
   (self.store.root/self.sid/'login-stop').unlink(missing_ok=True);self.calls=[]
   with self.subTest(n=n),self.assertRaises(VerificationFailure) as failure:self.go(cancel_after=n)
   self.assertEqual(failure.exception.reason,'login_user_cancelled');self.assertEqual(len(self.calls),n);self.assertIsNone(self.store.status(self.sid)['authorized_for_run'])
 def test_launch_clears_old_stop_and_continue_markers(self):
  import io
  from types import SimpleNamespace
  from pro_login_recovery import launch
  for name in ('login-stop','login-verify-continue'):(self.store.root/self.sid/name).touch()
  class Keep(io.BytesIO):
   def close(self):pass
  with patch('pro_executor.task_installation',return_value={'root':str(PRO),'python':sys.executable}),patch('pro_executor.binding_for',return_value={}),patch('pro_login_recovery.subprocess.Popen',return_value=SimpleNamespace(pid=999999,stdin=Keep())):launch(self.store,self.sid,'bili',self.recovery)
  self.assertFalse((self.store.root/self.sid/'login-stop').exists());self.assertFalse((self.store.root/self.sid/'login-verify-continue').exists())
 def test_redirect_refused_before_second_http(self):
  with self.assertRaises(VerificationFailure):self.go(status=302)
  self.assertEqual(len(self.calls),1)
if __name__=='__main__':unittest.main()
