import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
import local_cookiebridge as B
class Tests(unittest.TestCase):
 def setUp(self):self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name).resolve();self.value={'schema':'crowd-local-cookiebridge-v1','source_root':'/licensed/bridge','python':'/selected/python','python_sha256':'0'*64,'lock_sha256':'1'*64}
 def tearDown(self):self.t.cleanup()
 def record(self):p=self.root/'pro-cookiebridge.json';p.write_text(json.dumps(self.value));p.chmod(0o600)
 def test_existing_original_service_reused_zero_install_or_launch(self):
  with patch.object(B,'listening',return_value=True),patch.object(B,'original_accounts')as read,patch.object(B.subprocess,'Popen',side_effect=AssertionError('duplicate')):
   self.assertEqual(B.ensure(self.root),{'state':'reused'});read.assert_called_once();self.assertEqual(list(self.root.iterdir()),[])
 def test_foreign_or_invalid_loopback_service_refused(self):
  with patch.object(B,'listening',return_value=True),patch.object(B,'original_accounts',side_effect=ValueError('cookiebridge_existing_service_unverified')),patch.object(B.subprocess,'Popen',side_effect=AssertionError('duplicate')):
   with self.assertRaisesRegex(ValueError,'unverified'):B.ensure(self.root)
 def test_missing_licensed_service_clear_error_no_daemon(self):
  with patch.object(B,'listening',return_value=False),patch.object(B.subprocess,'Popen',side_effect=AssertionError('daemon')):
   with self.assertRaisesRegex(ValueError,'run_install_with_local_bridge'):B.ensure(self.root)
 def test_native_app_exact_loopback_environment_no_browser(self):
  self.record();child=MagicMock();child.poll.return_value=None;child.pid=42
  with patch.object(B,'listening',side_effect=[False,False,True]),patch.object(B,'validate'),patch.object(B,'original_accounts'),patch.object(B.subprocess,'Popen',return_value=child)as launch:
   self.assertEqual(B.ensure(self.root)['state'],'started_original_server');args=launch.call_args
   self.assertEqual(args.args[0],['/selected/python','-B','app.py']);self.assertEqual(args.kwargs['cwd'],Path('/licensed/bridge/server'));env=args.kwargs['env'];self.assertEqual((env['APP_HOST'],env['APP_PORT'],env['IS_DEBUG']),('127.0.0.1','8274',''));self.assertFalse(any('VOX_'in k for k in env))
 def test_native_start_failure_finite_no_success(self):
  self.record();child=MagicMock();child.poll.return_value=1
  with patch.object(B,'listening',return_value=False),patch.object(B,'validate'),patch.object(B.subprocess,'Popen',return_value=child):
   with self.assertRaisesRegex(ValueError,'start_failed'):B.ensure(self.root)
 def test_timeout_terminates_only_owned_child(self):
  self.record();child=MagicMock();child.poll.return_value=None
  with patch.object(B,'listening',return_value=False),patch.object(B,'validate'),patch.object(B.time,'sleep'),patch.object(B.subprocess,'Popen',return_value=child):
   with self.assertRaisesRegex(ValueError,'start_timeout'):B.ensure(self.root)
  child.terminate.assert_called_once();child.wait.assert_called_once_with(timeout=5)
if __name__=='__main__':unittest.main()
