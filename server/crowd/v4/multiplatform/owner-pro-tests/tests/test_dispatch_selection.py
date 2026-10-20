import json,os,unittest,tempfile,sqlite3
from pathlib import Path
import mc_runner,pro_executor
from owner_tasks import OwnerTasks,plan
class Dispatch(unittest.TestCase):
 def test_machine_selection(self):
  data=json.loads(Path(os.environ['G14_REQUESTS']).read_text())
  for r in data['machine_requests']:
   validated=mc_runner.validate(dict(r));self.assertEqual(validated['source_executor'],'pro')
   selected=pro_executor.selection(validated,environ={},installation={'root':'/offline-pro-fixture','python':'/offline-python-fixture'})
   self.assertEqual(selected['backend'],'pro')
  for r in data['legacy_requests']:self.assertEqual(pro_executor.selection(r,environ={})['backend'],'mc')
 def test_history_and_new_durable(self):
  # Same real local service; no scheduler or source runner is allowed in this fixture.
  with tempfile.TemporaryDirectory()as d:
   calls=[];s=OwnerTasks(d,lambda *a:(_ for _ in ()).throw(AssertionError('no source')));s._ensure_thread=lambda:None
   try:
    raw={'platforms':['dy','bili','wb'],'mode':'search','targets':['offline-fixture'],'desired_items':60,'max_api_requests':60,'comments':False,'replies':False,'media':False,'purpose':'noncommercial_research','idempotency_key':'legacy'}
    old=s.create(raw);again=s.create(raw);self.assertEqual(old['task']['task_id'],again['task']['task_id'])
    with sqlite3.connect(s.path)as db:old_bytes=db.execute('select data from tasks where idem=?',('legacy',)).fetchone()[0]
    new={**raw,'source_executor':'pro','idempotency_key':'new'};fresh=s.create(new);again=s.create(new);self.assertEqual(fresh['task']['task_id'],again['task']['task_id'])
    with sqlite3.connect(s.path)as db:
     self.assertEqual(old_bytes,db.execute('select data from tasks where idem=?',('legacy',)).fetchone()[0]);record=json.loads(db.execute('select data from tasks where idem=?',('new',)).fetchone()[0])
    self.assertTrue(all(c['request']['source_executor']=='pro'for c in record['children']))
    with self.assertRaisesRegex(ValueError,'idempotency_conflict'):s.create({**raw,'source_executor':'pro'})
    for platform in ('ks','tieba'):
     with self.assertRaisesRegex(ValueError,'pro_operation_platform_not_adapted'):s.create({**raw,'platforms':[platform],'source_executor':'pro','idempotency_key':'reject-'+platform})
    with sqlite3.connect(s.path)as db:self.assertEqual(db.execute('select count(*)from tasks').fetchone()[0],2)
   finally:s.close()
if __name__=='__main__':unittest.main()
