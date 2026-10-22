import json,os,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import Mock,patch
import machine_node as N
from test_cloud_sync import FakeCloud,lease
class Tests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name).resolve();self.root=self.base/'node';self.collector=self.base/'collector';self.collector.mkdir();(self.collector/'sessions').mkdir();(self.collector/'runs').mkdir();self.sdk=self.base/'sdk';self.sdk.mkdir()
 def tearDown(self):self.temp.cleanup()
 def node(self,client,runner=None):return N.MachineNode(self.root,self.sdk,[self.collector],client=client,runner=runner)
 def test_worker_only_construct_never_owner_scheduler_or_watchlists(self):
  cloud=FakeCloud(None)
  with patch('cloud_sync.CloudOwnerAdapter',side_effect=AssertionError('Owner')),patch('watchlists.Watchlists',side_effect=AssertionError('Watchlists')):
   n=self.node(cloud);self.assertIs(n.cloud_client,cloud);self.assertFalse(n.cloud_worker.scheduler_started);self.assertEqual(n._roots(),[self.root/'collector',self.collector]);n.cloud_worker.close()
 def test_original_cloudworker_start_status_finish_and_outbox(self):
  value=lease();value['request']['session_id']=str(uuid.uuid4());cloud=FakeCloud(value);run=str(uuid.uuid4());actions=[]
  def runner(action,payload):
   actions.append(action)
   if action=='start':return {'run_id':run}
   if action=='status':return {'run_id':run,'state':'completed','api_attempts':0}
   if action=='import':return {'records':[]}
   raise AssertionError(action)
  n=self.node(cloud,runner);self.assertIsInstance(n.cloud_worker,N.CloudWorker);self.assertEqual(n.cloud_worker.tick()['state'],'finished');self.assertEqual(actions,['start','status','import']);calls=[a for a,_ in cloud.calls];self.assertEqual(calls.count('claim'),1);self.assertEqual(calls.count('finish'),1);self.assertTrue(set(calls)<={'worker_capability_status','claim','heartbeat','finish'});self.assertIsNone(n.cloud_worker.postprocessing_callback);n.cloud_worker.close()
 def test_normal_application_runner_callback_preserved(self):
  n=self.node(FakeCloud(None));self.assertEqual(n.cloud_worker.runner,n.task_run)
  with patch.object(n,'run',return_value={'ok':True,'result':{'state':'running'}})as run:self.assertEqual(n.task_run('status',{'run_id':str(uuid.uuid4())})['result']['state'],'running');run.assert_called_once()
  n.cloud_worker.close()
 def test_worker_key_only_normal_cloudclient(self):
  self.root.mkdir(mode=0o700);config=self.root/'cloud-config.json';config.write_text(json.dumps({'endpoint':'https://example.supabase.co/functions/v1/crowd-machine','worker_key':'1'*64,'project_key':'sb_publishable_fixture'}));config.chmod(0o600)
  n=N.MachineNode(self.root,self.sdk,[self.collector]);self.assertEqual(n.cloud_client.role,'worker');self.assertNotIn('owner_key',n.cloud_client.config);n.cloud_worker.close()
 def test_owner_key_not_accepted_by_worker_only_entry(self):
  self.root.mkdir(mode=0o700);config=self.root/'cloud-config.json';config.write_text(json.dumps({'endpoint':'https://example.supabase.co/functions/v1/crowd-machine','worker_key':'1'*64,'owner_key':'2'*64,'project_key':'sb_publishable_fixture'}));config.chmod(0o600)
  with self.assertRaisesRegex(ValueError,'worker_only_config_required'):N.MachineNode(self.root,self.sdk,[self.collector])
 def test_existing_identity_progress_outbox_preserved_on_restart(self):
  import sqlite3
  from test_cloud_sync import row
  cloud=FakeCloud(None);n=self.node(cloud);outbox=n.cloud_worker.outbox
  outbox.stage_imported([row()],cloud.lease);self.assertEqual(outbox.flush()['acknowledged'],1)
  outbox.stage_imported([{**row(),'content_id':'1123456789abcdef01234567'}],cloud.lease)
  self.assertEqual(outbox.stats()['pending'],1);self.assertEqual(outbox.stats()['acknowledged'],1)
  n.cloud_worker._save({'phase':'dispatching','claim_id':str(uuid.uuid4()),'lease':cloud.lease,'waiting_logins':[],'sequence':1})
  state_path=n.cloud_worker.path;state_before=state_path.read_bytes();n.cloud_worker.close()
  marker=self.root/'original-progress.json';marker.write_text('untouched');identity=self.collector/'sessions'/str(uuid.uuid4())/'identity.json';identity.parent.mkdir();identity.write_text(json.dumps({'platform':'xhs'}));identity_before=identity.read_bytes()
  self.assertEqual(outbox.path,self.root/'cloud-outbox/outbox.sqlite3');self.assertTrue(outbox.path.is_file())
  with sqlite3.connect(outbox.path)as db:before='\n'.join(db.iterdump());captures_before=db.execute('select *from captures order by id').fetchall();self.assertEqual(len(captures_before),2)
  again=self.node(FakeCloud(None));again.cloud_worker.close();self.assertEqual(marker.read_text(),'untouched');self.assertEqual(identity.read_bytes(),identity_before);self.assertEqual(state_path.read_bytes(),state_before)
  with sqlite3.connect(outbox.path)as db:self.assertEqual('\n'.join(db.iterdump()),before);self.assertEqual(db.execute('select *from captures order by id').fetchall(),captures_before)
 def test_unregistered_collector_rejected(self):
  (self.collector/'sessions').rmdir()
  with self.assertRaisesRegex(ValueError,'collector_root_required'):self.node(FakeCloud(None))
if __name__=='__main__':unittest.main()
