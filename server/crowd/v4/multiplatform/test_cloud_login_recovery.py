import copy,json,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import Mock,patch
from types import SimpleNamespace
from cloud_sync import CloudWorker,CloudError
from account_sessions import AccountSessions
from dashboard import Application

def uid():return str(uuid.uuid4())
class RecoveryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve();self.task,self.child,self.run,self.local,self.sid,self.worker=[uid() for _ in range(6)]
  self.ref='a'*64;self.account={'session_id':self.sid,'generation':1,'account_ref':self.ref}
  self.lease={'task_id':self.task,'child_id':self.child,'run_id':self.run,'lease_epoch':1,'local_run_id':self.local,'platform':'bili','worker_id':self.worker,'request':{'session_id':self.sid}}
  self.wait={'outcome':'login_required','session_id':self.sid,'local_run_id':self.local,'account_context':self.account,'lease':self.lease}
  self.state={'phase':'idle','waiting_logins':[self.wait]};self.path=self.root/'state.json';self.path.write_text(json.dumps(self.state));self.lock=self.root/'worker.lock';self.lock.touch()
  self.w=CloudWorker.__new__(CloudWorker);self.w.path=self.path;self.w.lock_path=self.lock
  self.c={'child_id':self.child,'platform':'bili','state':'waiting','reason_code':'login_required','local_run_id':self.local,'worker_id':self.worker,'lease_epoch':1,'runs':[self.run],'request_quota':12,'requests_spent':1,'requests_reserved':0}
  self.c['attempts']=[{'run_id':self.run,'lease_epoch':1,'local_run_id':self.local,'worker_id':self.worker,'outcome':'login_required'}]
  self.taskrow={'task_id':self.task,'desired_state':'paused','children':[self.c]};self.owner=SimpleNamespace(role='owner',call=Mock(side_effect=lambda a,p:{'task':copy.deepcopy(self.taskrow)}))
  self.w._runner=Mock(side_effect=lambda a,p:{'run_id':self.local,'state':'login_required','exit_code':77,'platform':'bili','session_id':self.sid} if a=='status' else {**self.account,'state':'authenticated','authorized_for_run':uid()})
  self.open=Mock(return_value={'ok':True});self.before=self.path.read_bytes()
 def tearDown(self):self.tmp.cleanup()
 def call(self):return self.w.recover_cloud_login(self.task,self.child,self.owner,self.open)
 def test_existing_early_bridge_wait_binds_exact_original_not_old_pending(self):
  out=self.call();self.assertTrue(out['owner_continue_required']);self.open.assert_called_once_with(self.sid,'bili',{'run_id':self.local,'generation':1,'account_ref':self.ref},'mc');self.assertEqual(self.before,self.path.read_bytes());self.assertEqual(self.owner.call.call_args.args[0],'task_status')
 def test_running_task_preserves_existing_automatic_resume_intent(self):
  self.taskrow['desired_state']='running';self.assertFalse(self.call()['owner_continue_required'])
  self.assertEqual([call.args[0] for call in self.owner.call.call_args_list],['task_status'])
 def test_negative_remote_bindings_no_account_write(self):
  for key,value in [('local_run_id',uid()),('worker_id',uid()),('lease_epoch',True),('runs',[uid()]),('state','running'),('reason_code','unknown'),('requests_reserved',1),('requests_spent',12),('request_quota',True),('platform','wb')]:
   old=copy.deepcopy(self.c);self.c[key]=value
   with self.subTest(key=key),self.assertRaises(CloudError):self.call()
   self.c.clear();self.c.update(old)
  self.open.assert_not_called()
 def test_multiple_historical_attempts_latest_only(self):
  self.lease['lease_epoch']=2;self.c['lease_epoch']=2;self.c['attempts'][0]['lease_epoch']=2;self.path.write_text(json.dumps(self.state))
  previous={'run_id':uid(),'lease_epoch':1,'local_run_id':uid(),'worker_id':self.worker,'outcome':'login_required'}
  self.c['attempts'].insert(0,previous);self.c['runs'].insert(0,previous['run_id']);self.call()
  self.open.reset_mock();self.c['attempts'][0]['lease_epoch']=3
  with self.assertRaises(CloudError):self.call()
  self.open.assert_not_called()
 def test_stopped_task_and_unknown_source_rejected(self):
  self.taskrow['desired_state']='stopped'
  with self.assertRaises(CloudError):self.call()
  self.taskrow['desired_state']='paused';self.w._runner=Mock(return_value={'run_id':self.local,'state':'unknown'})
  with self.assertRaises(CloudError):self.call()
  self.open.assert_not_called()
 def test_source_terminal_scope_strict(self):
  for key,value in [('exit_code',78),('exit_code',True),('exit_code',None),('platform','wb'),('session_id',uid()),('account_generation',True),('account_generation',2)]:
   status={'run_id':self.local,'state':'login_required','exit_code':77,'platform':'bili','session_id':self.sid};status[key]=value
   self.w._runner=Mock(return_value=status)
   with self.subTest(key=key,value=value),self.assertRaises(CloudError):self.call()
  self.open.assert_not_called()
 def test_local_context_ambiguity_rejected(self):
  self.state['waiting_logins'].append(copy.deepcopy(self.wait));self.path.write_text(json.dumps(self.state))
  with self.assertRaises(CloudError):self.call()
  self.owner.call.assert_not_called()
 def test_generation_mismatch_and_busy_rejected(self):
  for value in ({**self.account,'generation':2},{**self.account,'login_in_progress':True},{**self.account,'account_ref':'b'*64}):
   self.w._runner=Mock(side_effect=[{'run_id':self.local,'state':'login_required','exit_code':77,'platform':'bili','session_id':self.sid},value])
   with self.assertRaises(CloudError):self.call()
  self.open.assert_not_called()
 def test_malformed_shapes_fixed_error_no_write(self):
  for bad in ([],{'waiting_logins':None},{'waiting_logins':[None]},{'waiting_logins':[{'lease':[],'account_context':{}}]}, {'waiting_logins':[{'lease':{'request':{}},'account_context':[]}]}):
   self.path.write_text(json.dumps(bad))
   with self.assertRaises(CloudError):self.call()
  self.path.write_text(json.dumps(self.state))
  for response in (None,[],{'task':None},{'task':[]},{'task':{'children':None}},{'task':{'children':[None]}}):
   self.owner.call=Mock(return_value=response)
   with self.assertRaises(CloudError):self.call()
  self.open.assert_not_called()
 def test_api_has_no_caller_run_setter(self):
  app=Application.__new__(Application);app.cloud_worker=self.w;app.cloud_client=self.owner;app.mc_root='unused';app._roots=Mock(return_value=[])
  with self.assertRaises(ValueError):app.accounts('recover_cloud_login',{'task_id':self.task,'child_id':self.child,'run_id':uid()})
 def test_account_atomic_scope_then_actual_official_same_subject(self):
  root=self.root/'collector';session=root/'sessions'/self.sid;session.mkdir(parents=True);(session/'identity.json').write_text(json.dumps({'platform':'bili'}));(session/'browser_data').mkdir()
  store=AccountSessions(root);old=uid();store.observe(self.sid,'bili','checking',old);a=store.observe(self.sid,'bili','authenticated',old,'original-subject');ref=a['account_ref'];new=uid()
  mc=self.root/'mc';(mc/'.venv/bin').mkdir(parents=True);(mc/'.venv/bin/python').touch();(mc/'main.py').touch()
  with patch('account_sessions.subprocess.Popen',return_value=SimpleNamespace(pid=123456)):
   store.open_login(self.sid,'bili',mc,_recovery={'run_id':new,'generation':1,'account_ref':ref})
  checking=store.status(self.sid);self.assertEqual(checking['pending_run_id'],new);self.assertIsNone(checking['authorized_for_run']);self.assertFalse(checking['login_verified'])
  done=store.observe(self.sid,'bili','authenticated',account_id='original-subject');self.assertEqual(done['authorized_for_run'],new);self.assertEqual(done['generation'],1)
 def test_account_mismatch_rejected_before_spawn_unchanged(self):
  root=self.root/'collector';session=root/'sessions'/self.sid;session.mkdir(parents=True);(session/'identity.json').write_text(json.dumps({'platform':'bili'}));(session/'browser_data').mkdir();store=AccountSessions(root);store.observe(self.sid,'bili','authenticated',account_id='original-subject');before=store.status(self.sid)
  mc=self.root/'mc';(mc/'.venv/bin').mkdir(parents=True);(mc/'.venv/bin/python').touch();(mc/'main.py').touch()
  with patch('account_sessions.subprocess.Popen') as spawn:
   with self.assertRaises(ValueError):store.open_login(self.sid,'bili',mc,_recovery={'run_id':uid(),'generation':2,'account_ref':before['account_ref']})
   spawn.assert_not_called()
  self.assertEqual(before,store.status(self.sid))
if __name__=='__main__':unittest.main()
