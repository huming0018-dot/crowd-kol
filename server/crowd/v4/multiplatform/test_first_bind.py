import json,tempfile,unittest,uuid,subprocess
from pathlib import Path
from unittest.mock import patch,MagicMock
import first_bind as F
import pro_bridge_enroll as E
from account_sessions import AccountSessions
class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve();self.collector=self.root/'collector';self.collector.mkdir();(self.collector/'sessions').mkdir();(self.collector/'runs').mkdir();self.client='synthetic_local_client';self.record={'runtime':str(Path(__file__).parent),'collector_roots':[str(self.collector)]};self.bound={'platform':'xhs','client_id':self.client,'cookiebridge_url':'http://127.0.0.1:8274','sign_url':'http://127.0.0.1:8990'};self.patches=[patch.object(F,'context',return_value=(self.root,self.record,self.collector)),patch('pro_executor.task_installation',return_value={'root':'/licensed/fixture','python':'/selected/pro/python'}),patch('pro_executor.probe',return_value={})]
  for p in self.patches:p.start()
 def tearDown(self):
  for p in self.patches:p.stop()
  self.tmp.cleanup()
 def authenticate(self,sid):
  E.register(self.collector,sid,self.bound);store=AccountSessions(self.collector);run=str(uuid.uuid4());store.observe(sid,'xhs','checking',run);store.observe(sid,'xhs','authenticated',run,'synthetic_official_self')
 def test_fresh_cli_uses_original_enroll_selected_python_and_private_plan(self):
  def invoke(args,**kw):
   self.assertEqual(args[:2],['/selected/pro/python','-B']);self.assertEqual(Path(args[2]).name,'pro_bridge_enroll.py');plan_path=Path(args[4]);self.assertEqual(plan_path.stat().st_mode&0o777,0o600);plan=json.loads(plan_path.read_bytes());self.assertEqual(plan['binding'],self.bound);self.authenticate(plan['session_id']);return subprocess.CompletedProcess(args,0,b'not emitted',b'not emitted')
  value=F.bind(self.root,self.client,invoke=invoke,connect=MagicMock());self.assertEqual(value['state'],'bound');self.assertFalse(value['reused']);self.assertNotIn('account_ref',value)
 def test_existing_authenticated_sid_no_auth_or_write(self):
  sid=str(uuid.uuid4());self.authenticate(sid);before={str(p):p.read_bytes()for p in self.root.rglob('*')if p.is_file()};invoke=MagicMock(side_effect=AssertionError('self again'));connect=MagicMock(side_effect=AssertionError('network'))
  value=F.bind(self.root,self.client,invoke=invoke,connect=connect);self.assertEqual(value['session_id'],sid);self.assertTrue(value['reused']);self.assertEqual(before,{str(p):p.read_bytes()for p in self.root.rglob('*')if p.is_file()})
 def test_status_empty_has_no_network_or_write(self):
  before=list(self.root.rglob('*'));value=F.bind(self.root,self.client,status=True,invoke=MagicMock(side_effect=AssertionError('auth')),connect=MagicMock(side_effect=AssertionError('network')));self.assertEqual(value['state'],'unbound_or_unverified');self.assertEqual(before,list(self.root.rglob('*')))
 def test_missing_bridge_actionable_before_plan(self):
  with self.assertRaisesRegex(ValueError,'cookiebridge_not_running'):F.bind(self.root,self.client,connect=MagicMock(side_effect=ConnectionRefusedError()))
  self.assertFalse((self.root/'binding-plans').exists())
 def test_unknown_intent_not_replayed_or_rekeyed(self):
  def invoke(args,**kw):
   plan=json.loads(Path(args[4]).read_bytes());base=self.collector/'enrollments';base.mkdir();(base/(plan['session_id']+'.json')).write_text('attempted');return subprocess.CompletedProcess(args,2,b'',b'')
  with self.assertRaisesRegex(ValueError,'failed_or_unknown'):F.bind(self.root,self.client,invoke=invoke,connect=MagicMock())
  plans={str(p):p.read_bytes()for p in(self.root/'binding-plans').iterdir()}
  with self.assertRaisesRegex(ValueError,'pending_or_unknown'):F.bind(self.root,self.client,invoke=MagicMock(side_effect=AssertionError('retry')),connect=MagicMock())
  self.assertEqual(plans,{str(p):p.read_bytes()for p in(self.root/'binding-plans').iterdir()})
 def test_unverified_existing_sid_not_recreated(self):
  sid=str(uuid.uuid4());E.register(self.collector,sid,self.bound)
  with self.assertRaisesRegex(ValueError,'unverified_do_not_rebind'):F.bind(self.root,self.client,connect=MagicMock())
  self.assertEqual([p.name for p in(self.collector/'sessions').iterdir()],[sid])
 def test_other_client_not_copied_or_silently_added(self):
  self.authenticate(str(uuid.uuid4()))
  with self.assertRaisesRegex(ValueError,'binding_conflict'):F.bind(self.root,'other',connect=MagicMock())
 def test_missing_dependencies_actionable_and_private_error_suppressed(self):
  with patch('pro_executor.probe',side_effect=OSError('/private/path')):
   with self.assertRaisesRegex(ValueError,'pro_dependencies_unavailable'):F.bind(self.root,self.client,connect=MagicMock())
  self.assertEqual(F.reason(ValueError('/private/path')),'local_binding_unavailable')
if __name__=='__main__':unittest.main()
