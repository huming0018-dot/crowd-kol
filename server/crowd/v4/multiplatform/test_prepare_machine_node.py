import json,tempfile,unittest
from pathlib import Path
import prepare_machine_node as P
class Tests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name).resolve();self.root=self.base/'node';self.sources={}
  for name in ('pro','signer'):
   source=self.base/name;source.mkdir();(source/'pyproject.toml').write_text('fixture');(source/'uv.lock').write_text('fixture');self.sources[name]=source
  self.tool=self.base/'uv';self.tool.write_text('fixture');self.tool.chmod(0o700);self.python=Path(__import__('sys').executable);self.calls=[]
 def tearDown(self):self.temp.cleanup()
 def execute(self,args,**kwargs):
  self.calls.append((args,kwargs))
  if args[1]=='venv':
   path=Path(args[2])/'bin/python';path.parent.mkdir(parents=True);path.write_text('fixture');path.chmod(0o700)
 def prepare(self):return P.prepare(self.root,self.sources,self.python,self.tool,run=self.execute,validate=lambda paths:None)
 def test_original_frozen_sync_used_and_no_sdk_copy_or_server_start(self):
  value=self.prepare();self.assertEqual(value['state'],'prepared');self.assertEqual(len(self.calls),4)
  for args,options in self.calls[1::2]:self.assertEqual(args[1:5],['sync','--frozen','--no-dev','--no-install-project']);self.assertIn('UV_PROJECT_ENVIRONMENT',options['env']);self.assertNotIn('app.py',args)
  self.assertFalse((self.root/'collector/sessions').exists());self.assertTrue(Path(value['python']).is_file())
 def test_native_volume_dependencies_use_independent_copy(self):
  self.prepare()
  for args,options in self.calls:self.assertEqual(options['env'].get('UV_LINK_MODE'),'copy')
  result=json.loads(next(self.root.rglob('RESULT.json')).read_bytes());self.assertEqual(result['input']['link_mode'],'copy')
 def test_completed_prepare_reused_without_new_commands(self):
  first=self.prepare();self.calls=[];second=self.prepare();self.assertEqual(first,second);self.assertFalse(self.calls)
 def test_unknown_install_intent_not_reexecuted(self):
  def failed(*args,**kwargs):raise OSError('install interrupted')
  with self.assertRaises(OSError):P.prepare(self.root,self.sources,self.python,self.tool,run=failed,validate=lambda paths:None)
  with self.assertRaisesRegex(ValueError,'dependency_attempt_unknown'):self.prepare()
  self.assertFalse(self.calls)
 def test_unverified_environment_not_marked_prepared(self):
  with self.assertRaisesRegex(ValueError,'probe fail'):P.prepare(self.root,self.sources,self.python,self.tool,run=self.execute,validate=lambda paths:(_ for _ in ()).throw(ValueError('probe fail')))
  self.assertFalse(list(self.root.rglob('RESULT.json')))
if __name__=='__main__':unittest.main()
