"""Actual normal Owner/session selectors with only source-info metadata mocked; no SDK process."""
import unittest,tempfile,pathlib,json,uuid,sys,fcntl
from unittest.mock import patch
import pro_executor as pro
import mc_runner
from dashboard import Application
class Capability(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.temp.name).resolve();self.sid=str(uuid.uuid4());self.session=self.root/'sessions'/self.sid;self.session.mkdir(parents=True);(self.session/'identity.json').write_text(json.dumps({'platform':'tieba'}));self.state=self.root/'accounts'/self.sid/'state.json';self.state.parent.mkdir(parents=True);self.save_state({'session_id':self.sid,'platform':'tieba','state':'authenticated','generation':1,'account_ref':'a'*64,'identity_status':'authenticated_self_id','authorized_for_run':None});self.sdk=self.root/'sdk';self.sdk.mkdir();self.save(self.root/'pro-executor.json',{'root':str(self.sdk),'python':sys.executable});self.binding=self.session/'pro-binding.json';self.save(self.binding,{'platform':'tieba','client_id':'fixed-original-client','cookiebridge_url':'http://127.0.0.1:8274','sign_url':'http://127.0.0.1:8990'});self.app=object.__new__(Application);self.app.runner_root=self.root;self.app.collector_roots=[];self.app.preferred_session_by_platform={};self.pin=patch('mc_runner.source_info',return_value={'commit':pro.PINNED_COMMIT,'dirty':False});self.pin.start()
 def tearDown(self):self.pin.stop();self.temp.cleanup()
 def save(self,path,value):path.write_text(json.dumps(value));path.chmod(0o600)
 def save_state(self,value):self.save(self.state,value)
 def test_normal_source_capability_bootstrap_without_task(self):
  with patch('dy_task_scope.ready',side_effect=ValueError('no_dy_session')):self.assertEqual(self.app._source_capabilities(),['pro_tieba_detail_v1'])
 def test_preserves_existing_dy_capability(self):
  with patch('dy_task_scope.ready',return_value=['pro_dy_trending_v1']):self.assertEqual(self.app._source_capabilities(),['pro_dy_trending_v1','pro_tieba_detail_v1'])
 def test_missing_installation_is_no_capability_not_poll_error(self):
  (self.root/'pro-executor.json').unlink()
  with patch('dy_task_scope.ready',side_effect=ValueError('no_dy_session')):self.assertEqual(self.app._source_capabilities(),[])
 def test_changed_source_pin_is_ineligible(self):
  with patch('mc_runner.source_info',return_value={'commit':'foreign','dirty':False}):
   with self.assertRaises(ValueError):pro.tieba_source_capabilities(self.app)
 def test_loggedout_or_foreign_binding_ineligible(self):
  s=json.loads(self.state.read_text());s['state']='logged_out';self.save_state(s)
  with self.assertRaises(ValueError):pro.tieba_source_capabilities(self.app)
  s['state']='authenticated';self.save_state(s);b=json.loads(self.binding.read_text());b['platform']='wb';self.save(self.binding,b)
  with self.assertRaises(ValueError):pro.tieba_source_capabilities(self.app)
 def test_account_generation_and_reference_typed(self):
  s=json.loads(self.state.read_text());s['generation']=True;self.save_state(s)
  with self.assertRaises(ValueError):pro.tieba_source_capabilities(self.app)
  s['generation']=1;s['account_ref']='foreign';self.save_state(s)
  with self.assertRaises(ValueError):pro.tieba_source_capabilities(self.app)
 def test_busy_session_ineligible(self):
  with (self.session/'active.lock').open('w')as lock:
   fcntl.flock(lock,fcntl.LOCK_EX)
   with self.assertRaises(ValueError):pro.tieba_source_capabilities(self.app)
if __name__=='__main__':unittest.main()
