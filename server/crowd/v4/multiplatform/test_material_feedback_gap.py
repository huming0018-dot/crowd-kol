from pathlib import Path
import copy,json,os,sys,tempfile,unittest,uuid
from types import SimpleNamespace
from unittest.mock import patch
HERE=Path(__file__).resolve().parent
MP=Path(os.environ.get('CROWD_MP_ROOT',str(HERE)))
sys.path[:0]=[str(Path(sys.argv.pop(1)) if len(sys.argv)>1 else Path(os.environ.get('CROWD_FEEDBACK_CANDIDATE',str(HERE)))),str(MP)]
from material_feedback import MaterialFeedback,canonical,digest,read,write
from toolbox.knowledge import KnowledgeStore
from owner_knowledge_binding import BindingError
class Gap(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve()
  self.binding=SimpleNamespace(config_sha256='a'*64,config={'workspace':str(self.root/'knowledge'),'endpoint':'https://fixture.invalid','owner_scope':'crowd-owner-main','scope':['fixture','existing-authorized-space','private-feedback']},authenticate=lambda c:None)
  self.request=str(uuid.uuid4());self.fid=str(uuid.uuid4());record={'record_hash':'b'*64,'body':'isolated saved正文'}
  self.s={'pro_key':'pro-'+'c'*64,'job_id':'d'*64,'source_project':'participant-pro-fixture','source_scope':{'task_id':29},'group_sha256':'e'*64,'report_sha256':'f'*64,'pack_ref':{'pack_id':'social-observations','version':'1.0.0','hash':'1'*64},'items':{self.request:{'metadata':{'capture':{'proof_id':57,'pro_payload':{'record':record}}}}}}
  self.service=MaterialFeedback(self.root,self.binding,None,resolver=lambda *a:copy.deepcopy(self.s))
  self.feedback={'intent_id':self.fid,'pro_key':self.s['pro_key'],'expected_job':self.s['job_id'],'request':self.request,'record_hash':'b'*64,'kind':'want_to_know','reason':'what evidence is missing?','quote':'正文','experience_confirmed':False,'consent_private':True}
  self.assertEqual(self.service.submit(self.feedback)['state'],'pending_feedback')
 def view(self):return self.service.request('material_feedback_gap_preview',{'feedback_intent':self.fid})
 def args(self):return {'feedback_intent':self.fid,'expected_feedback_sha256':self.view()['feedback_sha256'],'gap_type':'regression-miss','title':'Missing original evidence','description':'Owner explicitly selected this pending gap','consent_private':True}
 def submit(self,p=None):return self.service.request('material_feedback_gap_submit',p or self.args())
 def status(self):return self.service.request('material_feedback_gap_status',{'feedback_intent':self.fid})
 def test_roundtrip_real_sdk_same_consumer_pack_and_lineage(self):
  p=self.args();r=self.submit(p);self.assertEqual(r['state'],'pending_gap');self.assertEqual(self.status(),r)
  items=self.service.request('material_feedback_gap_list',{'after':None})['items'];self.assertEqual(len(items),1);self.assertEqual(items[0]['description'],p['description']);self.assertEqual(items[0]['lineage']['feedback_id'],'fb:'+self.fid);self.assertEqual(items[0]['lineage']['record_hash'],'b'*64);self.assertEqual(items[0]['pack_ref'],self.s['pack_ref'])
  st=self.service.store(True)
  try:
   rr=st.get_receipt(r['gap_intent']);self.assertEqual(rr['channel'],'consumer');self.assertEqual(rr['actor_ref'],self.service.actor);self.assertEqual(rr['operation'],'gap')
   for t in ('proposals','package_releases','review_grants','review_decisions','project_package_pins'):self.assertEqual(st._conn.execute('select count(*) from '+t).fetchone()[0],0)
  finally:st.close()
 def test_changed_full_input_same_source_refused_and_no_replay(self):
  p=self.args();r=self.submit(p)
  with patch.object(KnowledgeStore,'gap',side_effect=AssertionError('no SDK replay')):self.assertEqual(self.submit(p),r)
  for k,v in [('description','changed'),('title','changed'),('gap_type','taxonomy-gap'),('expected_feedback_sha256','2'*64)]:
   with self.subTest(k=k),self.assertRaises(BindingError):self.submit({**p,k:v})
 def test_unknown_precommit_no_new_uuid_or_retry(self):
  p=self.args()
  with patch.object(KnowledgeStore,'gap',side_effect=OSError('unknown')):r=self.submit(p)
  self.assertEqual(r['state'],'outcome_unknown')
  with patch.object(KnowledgeStore,'gap',side_effect=AssertionError('no retry')):self.assertEqual(self.submit(p),r);self.assertEqual(self.status(),r)
  with self.assertRaises(BindingError):self.submit({**p,'intent_id':str(uuid.uuid4())})
 def test_unknown_after_commit_reconcile_readonly(self):
  p=self.args();original=KnowledgeStore.gap
  def lost(st,*a):original(st,*a);raise OSError('lost reply')
  with patch.object(KnowledgeStore,'gap',lost):r=self.submit(p)
  self.assertEqual(r['state'],'outcome_unknown')
  with patch.object(KnowledgeStore,'gap',side_effect=AssertionError('no rewrite')):self.assertEqual(self.status()['state'],'pending_gap')
 def test_full_event_db_tamper_refused(self):
  r=self.submit();st=self.service.store()
  try:st._conn.execute("UPDATE gaps SET description='tampered' WHERE gap_id=?",(r['gap_id'],))
  finally:st.close()
  with self.assertRaises(BindingError):self.status()
 def test_evidence_tamper_refused(self):
  r=self.submit();st=self.service.store()
  try:st._conn.execute("UPDATE gaps SET evidence_refs_json='[]' WHERE gap_id=?",(r['gap_id'],))
  finally:st.close()
  with self.assertRaises(BindingError):self.status()
 def test_invalid_type_consent_foreign_missing_notwant(self):
  p=self.args()
  for change in ({'gap_type':'new-auto'},{'consent_private':False},{'description':None},{'feedback_intent':str(uuid.uuid4())},{'actor':'model'}):
   with self.subTest(change=change),self.assertRaises((BindingError,FileNotFoundError)):self.submit({**p,**change})
  self.feedback.update(intent_id=str(uuid.uuid4()),kind='ignore');self.service.submit(self.feedback)
  with self.assertRaises(BindingError):self.service.request('material_feedback_gap_preview',{'feedback_intent':self.feedback['intent_id']})
 def test_saved_feedback_tamper_and_new_binding_refused(self):
  p=self.args();path=self.service.folder/(self.fid+'.json');row=read(path);row['payload']['reason']='changed';write(path,row)
  with self.assertRaises(BindingError):self.submit(p)
 def test_preview_status_list_are_readonly(self):
  before=(self.root/'knowledge').joinpath('knowledge.sqlite3')
  with patch.object(KnowledgeStore,'gap',side_effect=AssertionError('no write')):
   self.view();self.assertEqual(self.status()['state'],'not_found');self.assertEqual(self.service.request('material_feedback_gap_list',{'after':None})['items'],[])
 def test_pagination_twenty_and_uuid_cursor(self):
  for i in range(21):
   if i:
    self.fid=str(uuid.uuid4());self.feedback['intent_id']=self.fid;self.service.submit(self.feedback)
   self.submit()
  first=self.service.request('material_feedback_gap_list',{'after':None});second=self.service.request('material_feedback_gap_list',{'after':first['next_cursor']})
  self.assertEqual(len(first['items']),20);self.assertEqual(len(second['items']),1);self.assertIsNone(second['next_cursor']);self.assertEqual(len({x['gap_id']for x in first['items']+second['items']}),21)
 def test_sdk_full_event_hash_ref_blocks_same_uuid_changed_event(self):
  p=self.args();r=self.submit(p);row=read(self.service._gap_path(self.fid));changed=copy.deepcopy(row['event']);changed['description']='changed'
  env=copy.deepcopy(row['envelope']);env['source_refs'][-1]['hash']=digest(canonical(changed))
  st=self.service.store()
  try:
   with self.assertRaisesRegex(Exception,'idempotency'):st.gap(env,changed)
  finally:st.close()
 def test_journal_and_event_hash_changed_not_authorized(self):
  self.submit();path=self.service._gap_path(self.fid);row=read(path);row['event']['description']='changed';row['event_sha256']=digest(canonical(row['event']));write(path,row)
  with self.assertRaises(BindingError):self.status()
 def test_cross_binding_cannot_reuse_source_and_size_bound_before_intent(self):
  other=copy.copy(self.binding);other.config={**other.config,'owner_scope':'foreign'};service=MaterialFeedback(self.root,other,None)
  with self.assertRaisesRegex(BindingError,'gap_feedback_not_found'):service.gap_preview({'feedback_intent':self.fid})
  import material_feedback
  p=self.args();p['description']='x'*4000;limit=(self.service.folder/(self.fid+'.json')).stat().st_size+100
  with patch.object(material_feedback,'MAX_JOURNAL_BYTES',limit),self.assertRaisesRegex(BindingError,'journal_limit'):self.submit(p)
  self.assertFalse(self.service._gap_path(self.fid).exists())
 def test_original9705_payload_gap_lineage_not_cuisines(self):
  path=Path(os.environ['CROWD_FEEDBACK_FIXTURE']) if os.environ.get('CROWD_FEEDBACK_FIXTURE') else (_ for _ in ()).throw(AssertionError('CROWD_FEEDBACK_FIXTURE required; private evidence is not a skip'))
  if not path.exists():raise AssertionError('required private actual input absent')
  original=read(path);self.fid=original['intent_id'];v=original['payload'];self.feedback=original['input']
  h=original['payload_sha256'];now='2026-10-20T00:00:00Z';env={'contract_version':'ctfs-knowledge-envelope/0.1','submission_id':self.fid,'project_id':self.service.scope['project'],'pack_ref':v['pack_ref'],'channel':'consumer','actor':{'ref':self.service.actor},'purpose':'feedback_material','consent_ref':None,'consent':{'scope':'private','granted_at':now,'granted_by':'central_owner_service'},'source_refs':[{'category':'crowd_observation','locator':original['target_ref'],'version':v['job_id'],'hash':v['record_hash']}],'payload_ref':{'store':'inline','key':self.fid,'type':'feedback','hash':h},'operation':'feedback','idempotency_key':self.fid}
  st=self.service.store()
  try:st.feedback(env,v,'want_to_know',original['target_ref'])
  finally:st.close()
  from publication_pro_share import create
  create(self.service.folder/(self.fid+'.json'),original)
  p=self.args();r=self.submit(p);self.assertEqual(r['state'],'pending_gap');self.assertEqual(self.status(),r)
  item=next(x for x in self.service.gap_list({'after':None})['items']if x['feedback_intent']==self.fid)
  self.assertEqual(item['lineage']['feedback_sha256'],h);self.assertEqual(item['lineage']['record_hash'],v['record_hash']);self.assertNotEqual(h,v['record_hash']);self.assertEqual(item['pack_ref'],v['pack_ref']);self.assertEqual(item['pack_ref']['pack_id'],'social-observations')
 def test_old_feedback_inbox_status_stay_same(self):
  original=self.service.status({'intent_id':self.fid});items=self.service.inbox({'after':None})['items'];self.assertEqual(len(items),1)
  self.submit();self.assertEqual(self.service.status({'intent_id':self.fid}),original);self.assertEqual(self.service.inbox({'after':None})['items'],items)
if __name__=='__main__':unittest.main()
