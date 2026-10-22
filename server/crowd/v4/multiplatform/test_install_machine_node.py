import hashlib,json,os,tempfile,unittest
from pathlib import Path
import install_machine_node as I
class Tests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name).resolve();self.source=self.base/'source';self.source.mkdir();self.root=self.base/'root';self.cloud=self.base/'pair.json';self.cloud.write_text(json.dumps({'endpoint':'https://example.supabase.co/functions/v1/crowd-machine','project_key':'sb_publishable_fixture','worker_key':'1'*64}));self.cloud.chmod(0o600)
  for name in ('machine_node.py','cloud_sync.py','mc_runner.py','pro_executor.py','portable_node.py'):(self.source/name).write_text('# owned fixture\n')
  self.manifest={'schema':'crowd-machine-node-runtime-v1','files':{p.name:I.sha(p.read_bytes())for p in self.source.iterdir()}};self.raw=json.dumps(self.manifest,sort_keys=True).encode();(self.source/'NODE-RUNTIME.json').write_bytes(self.raw);self.pin=I.sha(self.raw)
  self.python=Path('/usr/local/bin/python') if Path('/usr/local/bin/python').exists()else Path(os.sys.executable)
  self.sdk=self.base/'sdk';self.sdk.mkdir();self.collector=self.base/'collector';(self.collector/'sessions').mkdir(parents=True);(self.collector/'runs').mkdir()
 def tearDown(self):self.temp.cleanup()
 def install(self):return I.install(self.source,self.pin,self.root,self.cloud,self.python,self.sdk,[self.collector])
 def test_install_reinstall_preserve_identity_and_outbox(self):
  result=self.install();self.assertEqual(result['state'],'installed');marker=self.root/'prior-outbox.sqlite3';marker.write_bytes(b'prior rows');before={p.relative_to(self.root):p.read_bytes()for p in self.root.rglob('*')if p.is_file()};self.assertEqual(self.install()['state'],'current');self.assertEqual(before,{p.relative_to(self.root):p.read_bytes()for p in self.root.rglob('*')if p.is_file()});self.assertFalse(result['execution_ready'])
 def test_source_hash_refused_before_root_write(self):
  (self.source/'mc_runner.py').write_text('drift')
  with self.assertRaises(ValueError):self.install()
  self.assertFalse(self.root.exists())
 def test_owner_key_never_installed(self):
  data=json.loads(self.cloud.read_text());data['owner_key']='2'*64;self.cloud.write_text(json.dumps(data))
  with self.assertRaisesRegex(ValueError,'worker_only_config_required'):self.install()
  self.assertFalse(self.root.exists())
 def test_manifest_cannot_escape_or_include_private_sdk(self):
  for name in ('../secret','licensed/private.py','cookies.json'):
   with self.subTest(name=name):
    value={**self.manifest,'files':{**self.manifest['files'],name:'0'*64}};raw=json.dumps(value).encode();(self.source/'NODE-RUNTIME.json').write_bytes(raw)
    with self.assertRaises(ValueError):I.install(self.source,I.sha(raw),self.root,self.cloud,self.python,self.sdk,[self.collector])
    self.assertFalse(self.root.exists())
 def test_conflicting_pairing_preserves_previous(self):
  self.install();before=(self.root/'cloud-config.json').read_bytes();self.cloud.write_text(json.dumps({**json.loads(before),'worker_key':'3'*64}))
  with self.assertRaisesRegex(ValueError,'existing_node_configuration_conflict'):self.install()
  self.assertEqual((self.root/'cloud-config.json').read_bytes(),before)
 def test_start_revalidates_runtime_before_execution(self):
  result=self.install();value=I.installed(self.root);self.assertEqual(Path(value['entry']).name,'machine_node.py');Path(value['entry']).write_text('drift')
  with self.assertRaises(ValueError):I.installed(self.root)
if __name__=='__main__':unittest.main()
