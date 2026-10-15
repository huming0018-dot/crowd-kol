import importlib.util,json,tempfile,threading,time,unittest,uuid,sys
from pathlib import Path
from types import SimpleNamespace
F=Path(__file__).resolve().parent;sys.path.append(str(F))
import cloud_sync as c
from test_cloud_sync import FakeCloud,lease,row
class Tests(unittest.TestCase):
 def fixture(self,module=c):
  t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);cloud=FakeCloud();box=module.CloudOutbox(Path(t.name),cloud);ids=box.stage_imported([row()],cloud.lease);return box,cloud,ids[0]
 def test_fresh_direct_one_guard_and_one_capture(self):
  box,cloud,cid=self.fixture();guards=[];r=box.flush(before_send=lambda:guards.append('renew'));self.assertEqual([x[0] for x in cloud.calls],['capture']);self.assertEqual(len(guards),1);self.assertEqual(r['acknowledged'],1)
 def test_lost_response_retry_lookup_only_no_second_payload(self):
  box,cloud,cid=self.fixture();real=cloud.call
  def lost(action,payload):
   result=real(action,payload)
   if action=='capture':raise c.CloudError('cloud_outcome_unknown')
   return result
  cloud.call=lost;box.flush();cloud.call=real;box.flush();self.assertEqual([x[0] for x in cloud.calls],['capture','receipt']);self.assertEqual(box.stats()['acknowledged'],1)
 def test_zeroed_history_cannot_restore_consumed_proof(self):
  box,cloud,cid=self.fixture();real=cloud.call
  cloud.call=lambda a,p: (_ for _ in ()).throw(c.CloudError('cloud_outcome_unknown'));box.flush()
  with box._db() as db:db.execute('UPDATE capture_delivery SET attempts=0,total_attempts=0,last_attempt_at=0,next_attempt_at=0,requeues=0,last_error=NULL,attempt_token=NULL');db.execute('UPDATE captures SET error=NULL')
  cloud.call=real;box.flush();self.assertEqual([x[0] for x in cloud.calls],['receipt','capture'])
 def test_legacy_missing_proof_or_history_uses_lookup(self):
  for missing in ('proof','history','both'):
   box,cloud,cid=self.fixture()
   with box._db() as db:
    if missing in ('proof','both'):db.execute('DELETE FROM capture_first_delivery')
    if missing in ('history','both'):db.execute('DELETE FROM capture_delivery')
   box.flush();self.assertEqual([x[0] for x in cloud.calls],['receipt','capture'],missing)
 def test_denied_lease_no_payload_and_keeps_unused_proof(self):
  box,cloud,cid=self.fixture()
  def deny():raise c.DeliveryLeaseError('delivery_paused')
  with self.assertRaises(c.DeliveryLeaseError):box.flush(before_send=deny)
  self.assertEqual(cloud.calls,[])
  with box._db() as db:self.assertEqual(db.execute('SELECT pristine FROM capture_first_delivery').fetchone()[0],1)
 def test_attempt_error_or_requeue_history_even_with_proof_must_lookup(self):
  updates=["total_attempts=1","attempts=1","last_attempt_at=1","requeues=1","last_error='old_unknown'","attempt_token='old-token'"]
  for update in updates:
   box,cloud,cid=self.fixture()
   with box._db() as db:db.execute('UPDATE capture_delivery SET '+update)
   box.flush();self.assertEqual([x[0] for x in cloud.calls],['receipt','capture'],update)
 def test_concurrent_same_capture_only_once(self):
  box,cloud,cid=self.fixture();barrier=threading.Barrier(2);errors=[]
  def run():
   try:box.flush(before_send=lambda:barrier.wait(timeout=3))
   except BaseException as e:errors.append(type(e).__name__)
  threads=[threading.Thread(target=run) for _ in range(2)]
  for t in threads:t.start()
  for t in threads:t.join(5)
  self.assertFalse(errors);self.assertEqual([x[0] for x in cloud.calls],['capture']);self.assertEqual(box.stats()['acknowledged'],1)
 def test_repeat_stage_does_not_mint_new_proof(self):
  box,cloud,cid=self.fixture();box.flush();before=box.path.read_bytes();box.stage_imported([row()],cloud.lease)
  with box._db() as db:self.assertEqual(db.execute('SELECT pristine FROM capture_first_delivery').fetchone()[0],0)
if __name__=='__main__':unittest.main()
