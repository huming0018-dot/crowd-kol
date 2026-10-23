import json,tempfile,unittest,uuid
from pathlib import Path
from cloud_sync import CloudOutbox,CloudError
from test_cloud_sync import lease,row,FakeCloud
class BatchCloud(FakeCloud):
 def __init__(self):super().__init__();self.transport_calls=[]
 def capture_batch(self,payload):return self.call('capture_batch',payload)
 def call(self,action,payload=None):
  self.transport_calls.append(action)
  if action!='capture_batch':return super().call(action,payload)
  self.calls.append((action,payload));receipts=[]
  for i,item in enumerate(payload['items']):
   if i==getattr(self,'stop_after',-1):return {'schema':'crowd-machine-capture-batch-result-v1','run_id':payload['run_id'],'lease_epoch':payload['lease_epoch'],'receipts':receipts,'error':{'capture_id':item['envelope']['capture_id'],'envelope_hash':item['envelope_hash'],'code':'cloud_delivery_lease_denied'}}
   ack=super().call('capture',{'run_id':payload['run_id'],'lease_epoch':payload['lease_epoch'],'envelope':item['envelope'],'envelope_hash':item['envelope_hash']})['receipt'];receipts.append(ack)
  if getattr(self,'lose_batch',False):raise CloudError('cloud_outcome_unknown')
  if getattr(self,'bad_batch',False):receipts[-1]={**receipts[-1],'envelope_hash':'0'*64}
  return {'schema':'crowd-machine-capture-batch-result-v1','run_id':payload['run_id'],'lease_epoch':payload['lease_epoch'],'receipts':receipts,'error':None}
class Tests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.cloud=BatchCloud();self.lease=self.cloud.lease;self.box=CloudOutbox(Path(self.t.name).resolve(),self.cloud);self.prepared=[]
 def stage(self,n=4):
  self.box.stage_imported([{**row(),'content_id':str(i).zfill(24)}for i in range(n)],self.lease)
 def prepare(self,n):
  self.prepared.append(n);return {k:self.lease[k]for k in ('run_id','task_id','child_id','worker_id','lease_epoch')}|{'local_run_id':str(uuid.uuid4()),'sequences':list(range(1,n+1))}
 def test_four_pristine_one_http_all_exact_receipts(self):
  self.stage();s=self.box.flush_pristine(self.lease,self.prepare);self.assertEqual((s['acknowledged'],s['pending']),(4,0));self.assertEqual(self.prepared,[4]);self.assertEqual([a for a,p in self.cloud.calls].count('capture_batch'),1);self.assertNotIn('receipt',[a for a,p in self.cloud.calls])
 def test_lost_whole_batch_response_only_receipt_recovery_never_rebatch(self):
  self.stage();self.cloud.lose_batch=True;s=self.box.flush_pristine(self.lease,self.prepare);self.assertEqual(s['pending'],4);self.assertIsNone(self.box.flush_pristine(self.lease,self.prepare));self.box.flush(self.lease['run_id'],before_send=lambda:None);self.assertEqual(self.box.stats()['pending'],0);self.assertEqual([a for a,p in self.cloud.calls].count('capture_batch'),1);self.assertEqual([a for a,p in self.cloud.calls].count('capture'),4);self.assertEqual([a for a,p in self.cloud.calls].count('receipt'),4)
 def test_prefix_two_receipts_kept_suffix_pending_nonpristine(self):
  self.stage();self.cloud.stop_after=2;s=self.box.flush_pristine(self.lease,self.prepare);self.assertEqual((s['acknowledged'],s['pending']),(2,2));self.assertIsNone(self.box.flush_pristine(self.lease,self.prepare));self.assertEqual([a for a,p in self.cloud.calls].count('capture'),2)
 def test_wrong_ack_never_acknowledges_batch_or_rebatches(self):
  self.stage();self.cloud.bad_batch=True;s=self.box.flush_pristine(self.lease,self.prepare);self.assertEqual(s['acknowledged'],0);self.assertIsNone(self.box.flush_pristine(self.lease,self.prepare));self.assertIn('invalid_cloud_ack',s['errors'])
 def test_cross_run_refused_without_io_or_consuming_proof(self):
  self.stage();self.assertIsNone(self.box.flush_pristine({**self.lease,'child_id':str(uuid.uuid4())},self.prepare));self.assertEqual(self.cloud.calls,[]);self.assertEqual(self.prepared,[]);self.assertEqual(self.box.flush_pristine(self.lease,self.prepare)['acknowledged'],4)
 def test_large_batch_splits_at_original_byte_budget(self):
  self.box.stage_imported([{**row(),'content_id':str(i).zfill(24),'body':'x'*80000}for i in range(4)],self.lease)
  result=self.box.flush_pristine(self.lease,self.prepare);self.assertEqual((result['acknowledged'],result['pending']),(3,1));self.assertEqual(self.prepared,[3]);self.assertLessEqual(len(__import__('cloud_sync').canonical({'action':'capture_batch','payload':self.cloud.calls[0][1]}).encode()),300000)
 def test_nonpristine_uses_old_receipt_then_second_guard(self):
  self.stage()
  with self.box._db()as db:db.execute('UPDATE capture_first_delivery SET pristine=0')
  self.assertIsNone(self.box.flush_pristine(self.lease,self.prepare));guards=[]
  self.box.flush(self.lease['run_id'],before_send=lambda:guards.append(True))
  self.assertEqual(len(guards),8);self.assertEqual(self.cloud.transport_calls,['receipt','capture']*4)
 def test_late_ack_cannot_overwrite_replaced_attempt_token(self):
  self.stage();original=self.cloud.capture_batch;replacement=str(uuid.uuid4());changed=[]
  def overlap(payload):
   result=original(payload);identity=payload['items'][1]['envelope']['capture_id'];changed.append(identity)
   with self.box._db()as db:db.execute('UPDATE capture_delivery SET attempt_token=? WHERE id=?',(replacement,identity))
   return result
  self.cloud.capture_batch=overlap;s=self.box.flush_pristine(self.lease,self.prepare)
  self.assertEqual((s['acknowledged'],s['pending']),(3,1))
  with self.box._db()as db:
   self.assertEqual(db.execute('SELECT state FROM captures WHERE id=?',(changed[0],)).fetchone(),('pending',))
   self.assertEqual(db.execute('SELECT attempt_token FROM capture_delivery WHERE id=?',(changed[0],)).fetchone(),(replacement,))
 def test_worker_96_records_24_batches_all_ack_no_source(self):
  from cloud_sync import CloudWorker
  import mc_runner
  worker=CloudWorker(Path(self.t.name).resolve(),self.cloud,lambda*a:(_ for _ in()).throw(AssertionError('no source')))
  worker.outbox.stage_imported([{**row(),'content_id':str(i).zfill(24)}for i in range(96)],self.lease)
  mc_runner.write(worker.path,{'phase':'delivering','lease':self.lease,'local_run_id':str(uuid.uuid4()),'outcome':'completed','api_attempts':0})
  for _ in range(24):worker.tick()
  self.assertEqual(worker.outbox.stats()['acknowledged'],96)
  self.assertEqual(self.cloud.transport_calls.count('capture_batch'),24)
  self.assertEqual(self.cloud.transport_calls.count('capture'),0)
  self.assertEqual(self.cloud.transport_calls.count('heartbeat'),25)
  self.assertEqual(self.cloud.transport_calls.count('finish'),1)
  self.assertEqual(mc_runner.read(worker.path)['phase'],'idle')
  batches=[p for a,p in self.cloud.calls if a=='capture_batch'];seq=[i['sequence']for p in batches for i in p['items']]
  self.assertEqual(len(set(seq)),96);self.assertTrue(all(b>a for a,b in zip(seq,seq[1:])))
 def test_import_keepalive_thread_is_joined_before_reserving_batch_sequence(self):
  import threading,time
  from unittest.mock import patch
  from cloud_sync import CloudWorker
  worker=CloudWorker(Path(self.t.name).resolve(),self.cloud,lambda*a:None)
  state={'phase':'importing','lease':self.lease,'local_run_id':str(uuid.uuid4()),'outcome':'completed'}
  entered=threading.Event();release=threading.Event();original=self.cloud.call
  def delayed(action,payload=None):
   if action=='heartbeat'and threading.current_thread().name=='cloud-delivery-lease':entered.set();self.assertTrue(release.wait(1))
   return original(action,payload)
  self.cloud.call=delayed
  with patch('cloud_sync.DELIVERY_RENEW_SECONDS',.001):
   with worker._delivery_keepalive(state):
    self.assertTrue(entered.wait(1));timer=threading.Timer(.02,release.set);timer.start()
  timer.join();self.assertFalse(any(t.name=='cloud-delivery-lease'and t.is_alive()for t in threading.enumerate()))
  prior=state['sequence'];p=worker._prepare_capture_batch(state,4)
  self.assertEqual(p['sequences'],list(range(prior+1,prior+5)))
 def test_real_http_lost_batch_recovers_receipts_and_finite_metrics(self):
  import socket,threading
  from http.server import BaseHTTPRequestHandler
  from test_cloud_http_reuse import ReuseTests
  fixture=ReuseTests('test_repeated_guard_requests_reuse_one_connection');fixture.setUp()
  try:
   server=fixture.server
   class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def log_message(self,*a):pass
    def do_POST(self):
     value=json.loads(self.rfile.read(int(self.headers['Content-Length'])));action=value['action'];p=value['payload'];server.seen.append((action,p,0))
     if action=='capture_batch':
      for item in p['items']:
       e=item['envelope'];receipt={k:e[k]for k in ('capture_id','task_id','child_id','run_id','lease_epoch')};receipt.update(envelope_hash=item['envelope_hash'],status='received',source_kind='machine_api',reward_eligible=False);server.receipts[e['capture_id']]=receipt
      self.close_connection=True;self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
     self.assert_receipt(action)
     raw=json.dumps({'ok':True,'result':{'receipt':server.receipts[p['capture_id']]}}).encode();self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def assert_receipt(self,action):
     if action!='receipt':raise AssertionError('unexpected mutation retry')
   server.RequestHandlerClass=Handler;box=CloudOutbox(fixture.root,fixture.client);l=server.lease
   box.stage_imported([{**row(),'content_id':str(i).zfill(24)}for i in range(4)],l)
   def prepare(n):return {k:l[k]for k in ('run_id','task_id','child_id','worker_id','lease_epoch')}|{'local_run_id':str(uuid.uuid4()),'sequences':list(range(1,n+1))}
   self.assertEqual(box.flush_pristine(l,prepare)['pending'],4);self.assertIsNone(box.flush_pristine(l,prepare));box.flush(l['run_id'],before_send=lambda:None)
   self.assertEqual(box.stats()['acknowledged'],4);self.assertEqual([a for a,p,c in server.seen],['capture_batch']+['receipt']*4)
   metrics=fixture.client.delivery_performance();self.assertEqual(set(metrics['actions']),{'capture_batch','receipt'});self.assertEqual(metrics['actions']['capture_batch']['requests'],1);self.assertEqual(metrics['actions']['capture_batch']['successful_responses'],0);self.assertEqual(metrics['actions']['receipt']['requests'],4)
   encoded=json.dumps(metrics);self.assertNotIn('capture_id',encoded);self.assertNotIn('endpoint',encoded);self.assertNotIn('worker_key',encoded)
  finally:fixture.tearDown()

if __name__=='__main__':unittest.main()
