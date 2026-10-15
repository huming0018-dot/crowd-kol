import json,sqlite3,tempfile,time,unittest,uuid
from pathlib import Path
from mc_source_steps import NativeSteps,read_steps
class NativeStepsTest(unittest.TestCase):
 def test_restart_binding_and_replay(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);rid=str(uuid.uuid4());a=NativeSteps(root,rid,'wb');a.emit('request_started',api_attempts=1);a.emit('request_failed',api_attempts=1);self.assertEqual(len(read_steps(root,rid)),2)
   b=NativeSteps(root,rid,'wb');b.emit('response_received',api_attempts=2,http_status=200);self.assertEqual([e['source_sequence'] for e in read_steps(root,rid)],[1,2,3])
   with self.assertRaises(ValueError):read_steps(root,str(uuid.uuid4()))
 def test_untrusted_values_not_emitted(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);rid=str(uuid.uuid4());a=NativeSteps(root,rid,'wb');a.emit('Cookie=SECRET');a.emit('page_saved',scope='url');a.emit('request_started',api_attempts=True);self.assertEqual(read_steps(root,rid),[])
 def test_store_failure_is_nonfatal_to_observation(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);rid=str(uuid.uuid4());a=NativeSteps(root,rid,'wb');a.path.unlink();a.path.mkdir();a.emit('request_started',api_attempts=1);self.assertEqual(a.error,'native_steps_store_failed')
 def test_local_busy_is_bounded_and_source_can_continue(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);a=NativeSteps(root,str(uuid.uuid4()),'wb');lock=sqlite3.connect(a.path);lock.execute('BEGIN IMMEDIATE');t=time.monotonic();a.emit('request_started',api_attempts=1);elapsed=time.monotonic()-t;lock.rollback();lock.close();self.assertLess(elapsed,.2);self.assertEqual(a.error,'native_steps_store_failed')
 def test_malformed_readback_is_fixed_status_error(self):
  import mc_runner as runner
  for raw in ('[]','null','['*1000+'0'+']'*1000,'{"source_stage":"request_started","scope":"request","api_attempts":true}'):
   with tempfile.TemporaryDirectory() as d:
    root=Path(d);rid=str(uuid.uuid4());run=root/'runs'/rid;run.mkdir(parents=True);monitor=NativeSteps(run,rid,'wb');monitor.emit('request_started',api_attempts=1)
    with sqlite3.connect(monitor.path) as db:db.execute('UPDATE events SET event=?',(raw,))
    with self.assertRaisesRegex(ValueError,'native_steps_observation_failed'):read_steps(run,rid)
    runner.write(run/'status.json',{'run_id':rid,'state':'completed','updated_at':time.time()})
    self.assertEqual(runner.status(root,{'run_id':rid})['source_monitor_error'],'native_steps_observation_failed')
 def test_selected_subset_is_partial_not_full_raw_page(self):
  from mc_source_steps import identity,digest
  with tempfile.TemporaryDirectory() as t:
   run=Path(t).resolve();rid=str(uuid.uuid4());monitor=NativeSteps(run,rid,'wb');monitor.page('root',{'data':[{'id':str(i)} for i in (1,2,3)]},'data','id',{})
   path=run/'output/comments.jsonl';path.parent.mkdir();rows=[{'comment_id':str(i)} for i in (1,2)];path.write_text('\n'.join(json.dumps(row) for row in rows)+'\n')
   for n,row in enumerate(rows,1):monitor.saved[identity(row['comment_id'])]=(path,digest(row),n)
   monitor.select_callback_page(monitor.pending[-1],[{'id':'1'},{'id':'2'}],'id');events=read_steps(run,rid);self.assertEqual([e['saved_rows'] for e in events if e['source_stage']=='page_partially_saved'],[2]);self.assertFalse(any(e['source_stage']=='page_saved' for e in events))
 def test_partial_stage_rejects_zero_and_nonpage_scope(self):
  with tempfile.TemporaryDirectory() as t:
   run=Path(t).resolve();rid=str(uuid.uuid4());monitor=NativeSteps(run,rid,'wb');monitor.emit('page_partially_saved',scope='root',saved_rows=0,page_sha256='a'*64);monitor.emit('page_partially_saved',scope='content',saved_rows=1,page_sha256='a'*64);self.assertEqual(read_steps(run,rid),[])
if __name__=='__main__':unittest.main()
