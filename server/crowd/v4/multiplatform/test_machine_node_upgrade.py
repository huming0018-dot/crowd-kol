import json,sqlite3,fcntl,os,stat
from pathlib import Path
from unittest.mock import patch
import install_machine_node as I
import test_install_machine_node as Original
class Tests(Original.Tests):
 def setUp(self):
  super().setUp();self.patch=patch.object(I,'worker_running',return_value=False,create=True);self.patch.start()
 def tearDown(self):self.patch.stop();super().tearDown()
 def next_runtime(self):
  (self.source/'cloud_sync.py').write_text('# own new version\n');value={**self.manifest,'files':{p.name:I.sha(p.read_bytes())for p in self.source.iterdir()if p.name!='NODE-RUNTIME.json'}};raw=json.dumps(value,sort_keys=True).encode();(self.source/'NODE-RUNTIME.json').write_bytes(raw);return I.sha(raw)
 def upgrade(self,pin):return I.install(self.source,pin,self.root,self.cloud,self.python,self.sdk,[self.collector],upgrade=True)
 def fixture(self):
  self.install();worker=self.root/'cloud-worker';worker.mkdir(mode=0o700);(worker/'state.json').write_text(json.dumps({'phase':'idle','lease':None}));(worker/'state.json').chmod(0o600)
  db=self.root/'cloud-outbox/outbox.sqlite3';db.parent.mkdir()
  with sqlite3.connect(db)as conn:conn.execute('CREATE TABLE captures(id TEXT,state TEXT)');conn.execute("INSERT INTO captures VALUES('original','acknowledged')")
  session=self.collector/'sessions'/'original';session.mkdir();(session/'identity.json').write_text('{"original":true}');(session/'active.lock').touch()
  return {p:p.read_bytes()for p in [self.root/'cloud-config.json',worker/'state.json',db,session/'identity.json']}
 def test_upgrade_only_runtime_three_fields_preserves_original_data(self):
  protected=self.fixture();before=I.installed(self.root);pin=self.next_runtime();self.assertEqual(self.upgrade(pin)['state'],'upgraded');after=I.installed(self.root)
  self.assertEqual(sorted(k for k in before if before[k]!=after[k]),['entry','runtime','runtime_sha256']);self.assertEqual(protected,{p:p.read_bytes()for p in protected});self.assertTrue(Path(before['runtime']).is_dir());self.assertEqual(self.upgrade(pin)['state'],'current')
 def test_running_worker_refused_without_pointer_change(self):
  self.fixture();before=(self.root/'node-install.json').read_bytes();pin=self.next_runtime()
  with patch.object(I,'worker_running',return_value=True),self.assertRaisesRegex(ValueError,'must_be_stopped'):self.upgrade(pin)
  self.assertEqual((self.root/'node-install.json').read_bytes(),before)
 def test_busy_session_and_worker_lock_refused(self):
  self.fixture();pin=self.next_runtime()
  for path in [self.root/'cloud-worker/worker.lock',self.collector/'sessions/original/active.lock']:
   with self.subTest(path=path),open(path,'a+')as lock:
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    with self.assertRaisesRegex(ValueError,'busy'):self.upgrade(pin)
 def test_pending_or_unknown_state_and_outbox_refused(self):
  self.fixture();pin=self.next_runtime();state=self.root/'cloud-worker/state.json'
  for value in [{'phase':'claiming'},{'phase':'idle','lease':{'id':'unknown'}},{'phase':'idle','pending_deliveries':[{}]},{'phase':'idle','waiting_logins':[{}]},{'phase':'idle','lease':False},{'phase':'idle','local_run_id':''},{'phase':'idle','pending_deliveries':{}},{'phase':'idle','postprocessing_contexts':[]}]:
   state.write_text(json.dumps(value))
   with self.subTest(value=value),self.assertRaisesRegex(ValueError,'not_idle'):self.upgrade(pin)
  state.write_text('{"phase":"idle"}')
  with sqlite3.connect(self.root/'cloud-outbox/outbox.sqlite3')as db:db.execute("UPDATE captures SET state='pending'")
  with self.assertRaisesRegex(ValueError,'outbox_pending'):self.upgrade(pin)
 def test_intent_directory_sync_failure_never_replaces_pointer(self):
  self.fixture();pin=self.next_runtime();before=(self.root/'node-install.json').read_bytes();original=os.fsync
  def fail_directory(fd):
   if stat.S_ISDIR(os.fstat(fd).st_mode):raise OSError('directory sync failure')
   return original(fd)
  with patch.object(os,'fsync',side_effect=fail_directory),patch.object(os,'replace',wraps=os.replace)as replace:
   with self.assertRaises(OSError):self.upgrade(pin)
   replace.assert_not_called()
  self.assertEqual((self.root/'node-install.json').read_bytes(),before)
 def test_unknown_upgrade_intent_not_replayed(self):
  self.fixture();pin=self.next_runtime();(self.root/('node-upgrade-'+pin+'.INTENT.json')).write_text('original unknown');before=(self.root/'node-install.json').read_bytes()
  with self.assertRaises(FileExistsError):self.upgrade(pin)
  self.assertEqual((self.root/'node-install.json').read_bytes(),before)
