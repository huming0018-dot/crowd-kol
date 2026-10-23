"""Pure temporary journal and fake normal RPC; no production locks or network."""
import copy,datetime,json,tempfile,unittest,uuid
from pathlib import Path
from cloud_sync import CloudError,canonical
import worker_readiness as W

def sample(now=1000,ready=True):
 scope={'schema':'crowd-pro-source-readiness-v1','engine':'mediacrawler_pro','protocol':'vox-acquisition-v1','platform':'xhs','mode':'detail','scope':'xhs_detail_body_comments_v1','comments':True,'replies':True,'media':False,'max_items':1,'max_comments':200,'source_commit':'d32dd565277116ba4880c28ccd417a7c376cb62d','identity_basis':'cached_authenticated_self_id','identity_verified_at_ms':1,'session_generation':1,'session_ref':'1'*64,'binding_sha256':'2'*64}
 return {'observed_at_ms':int(now*1000),'host':{'os':'darwin','arch':'arm64'},'state':'ready'if ready else'not_ready','reason_code':'ready'if ready else'identity_unverified','source_readiness':[scope]if ready else[]}
class Client:
 def __init__(self):self.calls=[];self.rows={};self.worker=str(uuid.uuid4());self.timeout=False
 def call(self,action,payload):
  self.calls.append((action,copy.deepcopy(payload)))
  if action=='worker_capability_status':
   key=payload.get('report_id');row=self.rows.get(key)if key else next(reversed(self.rows.values()),None)
   if key and row is None:raise CloudError('capability_report_not_found')
   return {'schema':'crowd-worker-capability-status-v1','worker_id':self.worker,'latest_sequence':max((v['sequence']for v in self.rows.values()),default=0),'latest_report_id':next(reversed(self.rows),None),'report_receipt':{**row,'replayed':True}if row else None}
  report=payload;received=datetime.datetime.fromtimestamp(report['observed_at_ms']/1000,datetime.timezone.utc);row={'schema':'crowd-worker-capability-receipt-v1','worker_id':self.worker,'report_id':report['report_id'],'sequence':report['sequence'],'report_hash':W.report_hash(report),'received_at':received.isoformat(),'expires_at':(received+datetime.timedelta(seconds=120)).isoformat(),'replayed':False};self.rows[report['report_id']]=row
  if self.timeout:raise CloudError('cloud_outcome_unknown')
  return row
class Tests(unittest.TestCase):
 def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve();self.client=Client();self.value=sample();self.reporter=W.ReadinessReporter(self.root,self.client,lambda:copy.deepcopy(self.value))
 def tearDown(self):self.temp.cleanup()
 def test_report_once_cache_then_refresh_sequence(self):
  first=self.reporter.current(now=1000);self.assertIsInstance(first,str);self.value=sample(1005);self.assertEqual(self.reporter.current(now=1005),first);self.assertEqual(sum(a=='worker_capability_report'for a,_ in self.client.calls),1)
  self.value=sample(1061);second=self.reporter.current(now=1061);self.assertNotEqual(first,second);self.assertEqual(self.client.rows[second]['sequence'],2)
 def test_changed_proof_immediate_notready_supersedes(self):
  self.reporter.current(now=1000);self.value=sample(1001,False);self.assertIsNone(self.reporter.current(now=1001));self.assertEqual(len(self.client.rows),2);last=self.client.calls[-1][1];self.assertEqual(last['state'],'not_ready');self.assertEqual(last['source_readiness'],[])
 def test_unknown_only_status_no_repeat_report(self):
  self.client.timeout=True;self.assertIsNone(self.reporter.current(now=1000));self.client.timeout=False;self.assertIsInstance(self.reporter.current(now=1001),str);self.assertEqual(sum(a=='worker_capability_report'for a,_ in self.client.calls),1)
 def test_unknown_notfound_no_new_id_or_write(self):
  self.client.timeout=True;self.reporter.current(now=1000);self.client.rows.clear();self.client.timeout=False;self.assertIsNone(self.reporter.current(now=1001));self.assertEqual(sum(a=='worker_capability_report'for a,_ in self.client.calls),1)
 def test_final_write_failure_reconciles_same_receipt(self):
  from unittest.mock import patch
  original=W.write
  def failed(path,row):
   if row.get('state')=='recorded':raise OSError('disk')
   return original(path,row)
  with patch.object(W,'write',side_effect=failed):self.assertIsNone(self.reporter.current(now=1000))
  self.assertIsInstance(self.reporter.current(now=1001),str);self.assertEqual(sum(a=='worker_capability_report'for a,_ in self.client.calls),1)
 def test_invalid_source_or_stale_observation_never_report(self):
  for changed in('wrongengine','emptyready','old'):
   self.value=sample()
   if changed=='wrongengine':self.value['source_readiness'][0]['engine']='mc'
   elif changed=='emptyready':self.value['source_readiness']=[]
   else:self.value['observed_at_ms']=1
   with self.assertRaises(ValueError):self.reporter.current(now=1000)
  self.assertFalse(self.client.calls)
 def test_restart_recovers_sequence_without_reposting_old(self):
  first=self.reporter.current(now=1000);other=W.ReadinessReporter(self.root,self.client,lambda:sample(1002));self.assertEqual(other.current(now=1002),first);self.assertEqual(sum(a=='worker_capability_report'for a,_ in self.client.calls),1)
 def test_execution_session_or_changed_proof_does_not_match(self):
  import hashlib
  sid=str(uuid.uuid4());self.value['source_readiness'][0]['session_ref']=hashlib.sha256(sid.encode()).hexdigest();report=self.reporter.current(now=1000)
  self.assertTrue(self.reporter.matches(report,sid,now=1001));self.assertFalse(self.reporter.matches(report,str(uuid.uuid4()),now=1001))
  self.value['source_readiness'][0]['binding_sha256']='3'*64;self.assertFalse(self.reporter.matches(report,sid,now=1001))
 def test_cloudworker_claim_reference_replay_and_legacy_tokens(self):
  from cloud_sync import CloudWorker
  from unittest.mock import Mock
  client=Mock();client.call.side_effect=[CloudError('cloud_outcome_unknown'),{'lease':None}];worker=CloudWorker(self.root/'worker',client,Mock(),capability_provider=lambda:['pro_tieba_detail_v1']);report=str(uuid.uuid4());worker.readiness_reporter=Mock();worker.readiness_reporter.current.return_value=report
  self.assertEqual(worker.tick()['state'],'claiming');self.assertEqual(worker.tick()['state'],'idle')
  claims=[x.args[1]for x in client.call.call_args_list if x.args[0]=='claim'];self.assertEqual(claims[0],claims[1]);self.assertEqual(claims[0]['capability_report_id'],report);self.assertEqual(claims[0]['source_capabilities'],['pro_tieba_detail_v1']);worker.readiness_reporter.current.assert_called_once()
 def test_cloudworker_changed_session_proof_finishes_without_start(self):
  from cloud_sync import CloudWorker
  from test_cloud_sync import FakeCloud,lease
  from unittest.mock import Mock
  selected=str(uuid.uuid4());value=lease();value['request']['source_executor']='pro';cloud=FakeCloud(value);runner=Mock();worker=CloudWorker(self.root/'changed',cloud,runner,session_selector=lambda _:selected);worker.readiness_reporter=Mock();worker.readiness_reporter.current.return_value=str(uuid.uuid4());worker.readiness_reporter.matches.return_value=False
  self.assertEqual(worker.tick()['state'],'finished');runner.assert_not_called();finish=next(p for a,p in cloud.calls if a=='finish');self.assertEqual(finish['api_attempts'],0);self.assertEqual(finish['outcome'],'failed');self.assertEqual(worker.readiness_reporter.matches.call_args.args[1],selected)
 def test_cloudworker_local_proof_read_errors_finish_without_start(self):
  from cloud_sync import CloudWorker
  from test_cloud_sync import FakeCloud,lease
  from unittest.mock import Mock
  for error in (ValueError('invalid local proof'),OSError('local proof unreadable')):
   with self.subTest(error=type(error).__name__):
    value=lease();value['request']['source_executor']='pro';cloud=FakeCloud(value);runner=Mock();worker=CloudWorker(self.root/type(error).__name__,cloud,runner,session_selector=lambda _:str(uuid.uuid4()));worker.readiness_reporter=Mock();worker.readiness_reporter.current.return_value=str(uuid.uuid4());worker.readiness_reporter.matches.side_effect=error
    self.assertEqual(worker.tick()['state'],'finished');runner.assert_not_called();finish=next(p for a,p in cloud.calls if a=='finish');self.assertEqual(finish['api_attempts'],0);self.assertEqual(finish['outcome'],'failed')
 def test_cloudworker_matching_scope_reaches_original_runner(self):
  from cloud_sync import CloudWorker
  from test_cloud_sync import FakeCloud,lease
  from unittest.mock import Mock
  selected=str(uuid.uuid4());value=lease();value['request']['source_executor']='pro';cloud=FakeCloud(value);actions=[]
  def runner(action,payload):
   actions.append(action)
   return {'run_id':str(uuid.uuid4())}if action=='start'else{'state':'running','api_attempts':0}
  worker=CloudWorker(self.root/'matching',cloud,runner,session_selector=lambda _:selected);worker.readiness_reporter=Mock();worker.readiness_reporter.current.return_value=str(uuid.uuid4());worker.readiness_reporter.matches.return_value=True
  self.assertEqual(worker.tick()['state'],'running');self.assertEqual(actions[0],'start');self.assertEqual(actions.count('start'),1);self.assertEqual(worker.readiness_reporter.matches.call_args.args[1],selected)
 def test_provider_observation_uses_clock_after_local_preflight(self):
  from unittest.mock import patch
  clock=[1000]
  def provider():clock[0]=1001;return sample(1001)
  reporter=W.ReadinessReporter(self.root/'clock',self.client,provider)
  with patch.object(W.time,'time',side_effect=lambda:clock[0]):self.assertIsInstance(reporter.current(),str)
if __name__=='__main__':unittest.main()
