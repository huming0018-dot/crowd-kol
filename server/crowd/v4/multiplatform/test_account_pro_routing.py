import json,os,tempfile,unittest,uuid,copy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
from dashboard import Application
from account_sessions import AccountSessions

def uid():return str(uuid.uuid4())
class Tests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.root=Path(self.t.name);self.sid,self.task,self.child,self.local=[uid() for _ in range(4)];self.session=self.root/'sessions'/self.sid;self.session.mkdir(parents=True);(self.session/'identity.json').write_text('{"platform":"bili"}');(self.session/'pro-binding.json').write_text('{}');self.path=self.root/'cloud-state.json';self.wait={'outcome':'login_required','session_id':self.sid,'local_run_id':self.local,'account_context':{'session_id':self.sid},'lease':{'platform':'bili','local_run_id':self.local,'task_id':self.task,'child_id':self.child,'request':{'source_executor':'pro','session_id':self.sid}}};self.save([self.wait]);self.app=Application.__new__(Application);self.app.cloud_worker=SimpleNamespace(path=self.path,recover_cloud_login=Mock(return_value={'ok':True,'browser_started':False}));self.app.cloud_client=object();self.app.mc_root='not-used';self.app._roots=lambda:[self.root]
 def save(self,wait):self.path.write_text(json.dumps({'waiting_logins':wait}))
 def test_list_projects_exact_server_task_scope_no_credential_fields(self):
  row=self.app.accounts('list',{})['sessions'][0];self.assertEqual(row['login_recovery'],{'kind':'cloud_pro','task_id':self.task,'child_id':self.child,'platform':'bili'});self.assertNotIn('cookies',json.dumps(row))
 def test_list_connection_is_metadata_only_and_keeps_existing_route(self):
  before={str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
  with patch('subprocess.run',side_effect=AssertionError('list cannot start source')):
   row=self.app.accounts('list',{})['sessions'][0]
  self.assertEqual(row['pro_connection'],{'status':'configuration_required','missing':['installation','binding','identity'],'authentication_checked':False,'source_collection_started':False})
  self.assertEqual(row['login_recovery']['task_id'],self.task)
  self.assertEqual(before,{str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
  self.app.cloud_worker.recover_cloud_login.assert_not_called()
 def test_old_open_login_exact_pro_wait_routes_strict_existing_endpoint(self):
  before=self.path.read_bytes()
  with patch.object(AccountSessions,'open_login') as mc:
   self.assertFalse(self.app.accounts('open_login',{'session_id':self.sid,'platform':'bili'})['browser_started']);mc.assert_not_called()
  call=self.app.cloud_worker.recover_cloud_login.call_args;self.assertEqual(call.args[:2],(self.task,self.child));self.assertEqual(before,self.path.read_bytes())
 def test_projection_is_hint_and_existing_authoritative_gate_rejection_propagates(self):
  self.app.cloud_worker.recover_cloud_login.side_effect=ValueError('cloud_login_context_changed')
  with patch.object(AccountSessions,'open_login') as mc,self.assertRaisesRegex(ValueError,'cloud_login_context_changed'):self.app.accounts('open_login',{'session_id':self.sid,'platform':'bili'})
  mc.assert_not_called()
 def test_disconnected_worker_does_not_lose_persisted_cloud_wait(self):
  self.app.root=self.root;(self.root/'cloud-worker').mkdir();(self.root/'cloud-worker/state.json').write_bytes(self.path.read_bytes());self.app.cloud_worker=None
  self.assertEqual(self.app.accounts('list',{})['sessions'][0]['login_recovery']['task_id'],self.task)
  with patch.object(AccountSessions,'open_login') as mc,self.assertRaisesRegex(ValueError,'cloud_not_connected'):self.app.accounts('open_login',{'session_id':self.sid,'platform':'bili'})
  mc.assert_not_called()
 def test_nonpro_cloud_and_noncloud_behavior_preserved(self):
  for waits in ([],[{**self.wait,'lease':{**self.wait['lease'],'request':{'session_id':self.sid}}}]):
   self.save(waits)
   with patch.object(AccountSessions,'open_login',return_value={'old':True}) as mc:self.assertTrue(self.app.accounts('open_login',{'session_id':self.sid,'platform':'bili'})['old']);mc.assert_called_once()
 def test_duplicate_mismatch_or_malformed_fail_closed_without_mc(self):
  cases=[[self.wait,copy.deepcopy(self.wait)],[{**self.wait,'lease':{**self.wait['lease'],'platform':'invalid'}}],[{**self.wait,'lease':None}],[{**self.wait,'session_id':False}]]
  for waits in cases:
   self.save(waits)
   with self.subTest(waits=waits),patch.object(AccountSessions,'open_login') as mc,self.assertRaises(ValueError):self.app.accounts('open_login',{'session_id':self.sid,'platform':'bili'})
   mc.assert_not_called()
 def test_unsafe_state_files_not_opened_or_blocking(self):
  self.path.unlink();target=self.root/'target';target.write_text('{}');self.path.symlink_to(target)
  self.assertEqual(self.app.accounts('list',{})['sessions'][0]['login_recovery']['kind'],'blocked');self.path.unlink();os.mkfifo(self.path)
  self.assertEqual(self.app.accounts('list',{})['sessions'][0]['login_recovery']['kind'],'blocked')
 def test_other_pro_cloud_platform_keeps_existing_original_window_behavior(self):
  self.wait['lease']['platform']='xhs';self.save([self.wait]);(self.session/'identity.json').write_text('{"platform":"xhs"}')
  row=self.app.accounts('list',{})['sessions'][0];self.assertNotIn('login_recovery',row)
  with patch.object(AccountSessions,'open_login',return_value={'legacy':True}) as mc:self.assertTrue(self.app.accounts('open_login',{'session_id':self.sid,'platform':'xhs'})['legacy']);mc.assert_called_once()
 def test_corrupt_state_does_not_block_unbound_legacy_account(self):
  (self.session/'pro-binding.json').unlink();self.path.write_bytes(b'[')
  with patch.object(AccountSessions,'open_login',return_value={'legacy':True}) as mc:self.assertTrue(self.app.accounts('open_login',{'session_id':self.sid,'platform':'bili'})['legacy']);mc.assert_called_once()
if __name__=='__main__':unittest.main()
