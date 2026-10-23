import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock
import mc_runner
from cloud_sync import CloudError, CloudWorker
from existing_saved_rejection import rejected_before_dispatch, PERMANENT_REJECTIONS
from test_cloud_sync import FakeCloud, lease, row

class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  self.cloud=FakeCloud(lease('existing_saved'))
  self.reader=Mock(side_effect=ValueError('existing_saved_target_mismatch'))
  self.runner=Mock(side_effect=AssertionError('no source permitted'))
 def tearDown(self):self.tmp.cleanup()
 def worker(self):return CloudWorker(self.root,self.cloud,self.runner,existing_reader=self.reader)
 def test_durable_failed_finish_restart_original_id_and_idle(self):
  w=self.worker();self.assertEqual(w.tick(),{'state':'finishing','error':'existing_saved_target_mismatch'})
  state=mc_runner.read(w.path);original=state['lease'];self.assertEqual(state['outcome'],'failed');self.assertEqual(state['api_attempts'],0)
  w=self.worker();r=w.tick();self.assertEqual(r['state'],'finished');self.assertEqual(r['task']['state'],'failed')
  p=next(p for a,p in self.cloud.calls if a=='finish')
  for k in ['run_id','lease_epoch']:self.assertEqual(p[k],original[k])
  self.assertEqual(p['capture_ids'],[]);self.assertEqual(p['api_attempts'],0);self.assertEqual(p['outcome'],'failed')
  final=mc_runner.read(w.path);self.assertEqual(final['phase'],'idle');self.assertEqual(final['last_validation_error'],'existing_saved_target_mismatch');self.assertEqual(final['last_finished_run_id'],original['run_id'])
  self.assertEqual(self.reader.call_count,1);self.runner.assert_not_called()
 def test_unknown_finish_exact_payload_after_restart_no_reader(self):
  w=self.worker();w.tick();original=self.cloud.call;requests=[]
  def call(a,p=None):
   if a=='finish':
    requests.append(dict(p))
    if len(requests)==1:
     original(a,p);raise CloudError('cloud_outcome_unknown')
   return original(a,p)
  self.cloud.call=call;self.assertEqual(w.tick()['error'],'cloud_outcome_unknown');self.assertEqual(mc_runner.read(w.path)['phase'],'finishing')
  w=self.worker();self.assertEqual(w.tick()['state'],'finished');self.assertEqual(requests[0],requests[1]);self.assertEqual(self.reader.call_count,1);self.runner.assert_not_called()
 def test_unknown_reader_never_failed_finish(self):
  for error in [OSError('unknown'),CloudError('cloud_outcome_unknown'),ValueError('unclassified')]:
   with tempfile.TemporaryDirectory() as tmp:
    w=CloudWorker(Path(tmp),self.cloud,self.runner,existing_reader=Mock(side_effect=error));w.tick();self.assertEqual(mc_runner.read(w.path)['phase'],'authorized')
  self.assertFalse(any(a=='finish' for a,_ in self.cloud.calls));self.runner.assert_not_called()
 def test_pending_ack_rows_preserved(self):
  for ack in [False,True]:
   with tempfile.TemporaryDirectory() as tmp:
    w=CloudWorker(Path(tmp),self.cloud,self.runner,existing_reader=self.reader);w.outbox.stage_imported([row()],self.cloud.lease)
    if ack:w.outbox.flush()
    before=w.outbox.stats(self.cloud.lease['run_id']);w.tick();self.assertEqual(mc_runner.read(w.path)['phase'],'authorized');self.assertEqual(w.outbox.stats(self.cloud.lease['run_id']),before)
  self.assertFalse(any(a=='finish' for a,_ in self.cloud.calls))
 def test_actual_dashboard_local_read_errors_finish_once_without_rereading(self):
  from dashboard import Application
  cases=[('invalid_results_revision',{'version_hash':'0'*64,'results_revision':1}),
         ('results_version_not_found',{'version_hash':'0'*64}),
         ('invalid_results_version',{'version_hash':'bad'}),
         ('existing_saved_selection_unavailable',{})]
  for expected,extra in cases:
   with self.subTest(error=expected),tempfile.TemporaryDirectory() as tmp:
    app=Application.__new__(Application);app.root=Path(tmp)
    cloud=FakeCloud(lease('existing_saved'));cloud.lease['record_refs']=[{'content_id':row()['content_id'],'kind':'content',**extra}]
    reader=Mock(wraps=app._cloud_existing)
    w=CloudWorker(Path(tmp),cloud,self.runner,existing_reader=reader)
    self.assertEqual(w.tick(),{'state':'finishing','error':expected})
    saved=mc_runner.read(w.path);self.assertEqual(saved['validation_error'],expected);self.assertEqual(saved['api_attempts'],0);self.assertEqual(w.outbox.stats()['capture_ids'],[])
    w=CloudWorker(Path(tmp),cloud,self.runner,existing_reader=reader)
    self.assertEqual(w.tick()['state'],'finished');self.assertEqual(reader.call_count,1)
    finish=next(p for a,p in cloud.calls if a=='finish');self.assertEqual(finish['outcome'],'failed');self.assertEqual(finish['api_attempts'],0);self.assertEqual(finish['capture_ids'],[])
    self.assertEqual(mc_runner.read(w.path)['last_validation_error'],expected)
  self.runner.assert_not_called()
 def test_finish_state_write_failure_keeps_original_authorization(self):
  w=self.worker();w._save({'phase':'authorized','lease':self.cloud.lease,'claim_id':'original','sequence':0})
  original=w._save
  def save(state):
   if state.get('phase')=='finishing':raise OSError('disk failure')
   return original(state)
  w._save=save;self.assertEqual(w.tick()['state'],'authorized')
  self.assertEqual(mc_runner.read(w.path)['phase'],'authorized');self.assertFalse(any(a=='finish' for a,_ in self.cloud.calls));self.runner.assert_not_called()
 def test_local_run_live_dispatch_quarantine_missing_stats_refused(self):
  s={'phase':'authorized','lease':{'delivery_basis':'existing_saved'}};empty={'capture_ids':[],'pending':0,'acknowledged':0,'quarantined':0}
  for code in PERMANENT_REJECTIONS:self.assertTrue(rejected_before_dispatch(s,code,empty))
  for state in [dict(s,local_run_id='run'),dict(s,phase='dispatching'),dict(s,lease={'delivery_basis':'live_capture'})]:self.assertFalse(rejected_before_dispatch(state,'existing_saved_selection_mismatch',empty))
  for stats in [{},dict(empty,quarantined=1),dict(empty,capture_ids=['old']),dict(empty,pending=False)]:self.assertFalse(rejected_before_dispatch(s,'existing_saved_selection_mismatch',stats))
  self.assertFalse(rejected_before_dispatch(s,'cloud_outcome_unknown',empty))
if __name__=='__main__':unittest.main()
