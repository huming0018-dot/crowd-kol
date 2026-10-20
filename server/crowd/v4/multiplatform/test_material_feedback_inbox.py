from pathlib import Path
import sys,os,uuid,copy,json,unittest
from unittest.mock import patch
HERE=Path(__file__).resolve().parent
MP=Path(os.environ.get('CROWD_MP_ROOT',str(HERE)));TARGET=Path(os.environ.get('CROWD_FEEDBACK_CANDIDATE',str(HERE/'candidate'if(HERE/'candidate').is_dir()else HERE)));sys.path[:0]=[str(TARGET),str(MP)]
import material_feedback as target
import test_material_feedback as original
from owner_knowledge_binding import BindingError
from toolbox.knowledge import KnowledgeError
class Inbox(original.Feedback):
 def hashes(self):
  from hashlib import sha256
  return {str(p):sha256(p.read_bytes()).hexdigest()for p in self.dir.rglob('*')if p.is_file()and not p.name.endswith(('-shm','-wal'))}
 def test_inbox_real_receipt_readonly_and_original_version_link(self):
  self.service.submit(self.p);before=self.hashes()
  with patch.object(self.service,'status',side_effect=AssertionError('no automatic reconcile')),patch.object(self.service,'resolver',side_effect=AssertionError('no source reader')):
   r=self.service.inbox({'after':None})
  self.assertEqual(self.hashes(),before);self.assertEqual(r['state'],'material_feedback_inbox');self.assertEqual(len(r['items']),1);v=r['items'][0]
  self.assertEqual(v['state'],'pending_feedback');self.assertEqual(v['reason'],self.p['reason']);self.assertEqual(v['job_id'],self.p['expected_job']);self.assertEqual(v['record_hash'],self.p['record_hash']);self.assertIsNone(v['human_uid']);self.assertFalse(v['reviewed']);self.assertFalse(v['published']);self.assertIsNone(r['next_cursor'])
 def test_inbox_pagination_twenty_and_original_cursor(self):
  ids=[str(uuid.UUID(int=i))for i in range(1,24)]
  for iid in ids:self.service.submit({**self.p,'intent_id':iid})
  before=self.hashes();r=self.service.inbox({'after':None});self.assertEqual([x['intent_id']for x in r['items']],ids[:20]);self.assertEqual(r['next_cursor'],ids[19])
  r2=self.service.inbox({'after':r['next_cursor']});self.assertEqual([x['intent_id']for x in r2['items']],ids[20:]);self.assertIsNone(r2['next_cursor']);self.assertEqual(self.hashes(),before)
 def test_inbox_unknown_no_store_and_no_write(self):
  with patch.object(self.service,'store',side_effect=OSError('unknown')):self.assertEqual(self.service.submit(self.p)['state'],'outcome_unknown')
  before=self.hashes()
  with patch.object(self.service,'store',side_effect=AssertionError('unknown cannot assert receipt')):r=self.service.inbox({'after':None})
  self.assertEqual(self.hashes(),before);self.assertEqual(r['items'][0]['state'],'outcome_unknown');self.assertNotIn('reason',r['items'][0]);self.assertNotIn('job_id',r['items'][0])
 def test_inbox_event_hash_or_submission_mismatch_rejected(self):
  self.service.submit(self.p)
  original_get=target.KnowledgeStore.get_feedback
  for field,value in [('payload_hash','f'*64),('submission_id',str(uuid.UUID(int=0)))]:
   def changed(store,*a,**kw):return {**original_get(store,*a,**kw),field:value}
   with self.subTest(field=field),patch.object(target.KnowledgeStore,'get_feedback',changed):
    with self.assertRaisesRegex(BindingError,'receipt_mismatch'):self.service.inbox({'after':None})
 def test_inbox_sdk_payload_mismatch_and_corrupt_journal_fail_closed(self):
  self.service.submit(self.p);path=self.service.folder/(self.p['intent_id']+'.json');old=path.read_bytes();v=json.loads(old);v['payload']['reason']='changed';v['payload_sha256']=target.digest(target.canonical(v['payload']));target.write(path,v)
  with self.assertRaises((BindingError,KnowledgeError)):self.service.inbox({'after':None})
  path.write_bytes(b'{');path.chmod(0o600)
  with self.assertRaises((ValueError,BindingError)):self.service.inbox({'after':None})
  path.write_bytes(old);path.chmod(0o600)
 def test_inbox_foreign_actor_and_invalid_cursor_rejected(self):
  self.service.submit(self.p);binding=copy.copy(self.binding);binding.config={**self.binding.config,'owner_scope':'different-owner'}
  other=target.MaterialFeedback(self.dir,binding,object(),resolver=lambda*a:self.s);path=other.folder/(self.p['intent_id']+'.json');path.write_bytes((self.service.folder/path.name).read_bytes());path.chmod(0o600)
  with self.assertRaises((BindingError,KnowledgeError)):other.inbox({'after':None})
  for p in ({},{'after':'../escape'},{'after':None,'workspace':'x'}):
   with self.assertRaises(BindingError):self.service.inbox(p)
if __name__=='__main__':unittest.main()
