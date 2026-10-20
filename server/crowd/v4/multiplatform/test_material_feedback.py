from pathlib import Path
import os,copy,hashlib,json,shutil,sys,tempfile,unittest,uuid
from types import SimpleNamespace
from unittest.mock import patch
HERE=Path(__file__).resolve().parent;C=HERE;MP=HERE;ACTUAL=Path(os.environ['CROWD_MATERIAL_TEST_ROOT']).resolve()
sys.path.insert(0,str(C));sys.path.append(str(MP))
from material_feedback import MaterialFeedback,source,canonical,digest
from automatic_materials import private_json,write,material_context_key
from material_auto_worker import process
from toolbox.knowledge import KnowledgeStore,AuthContext,KnowledgeError
from owner_knowledge_binding import BindingError
class Feedback(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name).resolve();runtime=cls.root/'runtime';runtime.mkdir()
  for p in MP.iterdir():
   if p.is_file()and(p.suffix=='.py'or p.name.endswith('-SHA.json')or p.name=='DEPENDENCIES.json'):shutil.copyfile(p,runtime/p.name)
  for p in C.glob('*.py'):shutil.copyfile(p,runtime/p.name)
  sha=lambda p:digest(p.read_bytes());cfg=private_json(ACTUAL/'data-products/material-auto-runtime.json');cfg.update(runtime_root=str(runtime),runtime_cloud_sha256=sha(runtime/'cloud_sync.py'),bridge_path=str(runtime/'material_bridge.py'),bridge_sha256=sha(runtime/'material_bridge.py'),worker_script=str(runtime/'material_auto_worker.py'),worker_sha256=sha(runtime/'material_auto_worker.py'),pro_snapshot_sha256=sha(runtime/'pro_ack_snapshot.py'))
  if 'pro_comments_sha256'in cfg:cfg['pro_comments_sha256']=sha(runtime/'participant_pro_comments.py')
  ready=next(v for p in (ACTUAL/'data-products/material-auto').glob('pro-*.json')if not p.name.endswith('.config.json')for v in [private_json(p)]if v.get('state')=='ready'and v.get('context',{}).get('task_id')==29)
  ctx=copy.deepcopy(ready['context']);inputs=cls.root/'data-products/participant-pro-ack-inputs';inputs.mkdir(parents=True);p=inputs/(ctx['group_sha256']+'.json');p.write_bytes(Path(ctx['group_path']).read_bytes());p.chmod(0o600);ctx['group_path']=str(p);cls.key=material_context_key(ctx);cls.state=cls.root/'data-products/material-auto'/(cls.key+'.json');cls.state.parent.mkdir();write(cls.state,{'state':'waiting','context':ctx});write(cls.root/'data-products/material-auto-runtime.json',cfg);process(cls.root,cls.state,cfg)
  cls.real=source(cls.root,cls.key)
  ready19=next(v for p in (ACTUAL/'data-products/material-auto').glob('pro-*.json')if not p.name.endswith('.config.json')for v in [private_json(p)]if v.get('state')=='ready'and v.get('context',{}).get('task_id')==19)
  c19=copy.deepcopy(ready19['context']);p=inputs/(c19['group_sha256']+'.json');p.write_bytes(Path(c19['group_path']).read_bytes());p.chmod(0o600);c19['group_path']=str(p);cls.key19=material_context_key(c19);cls.state19=cls.state.parent/(cls.key19+'.json');write(cls.state19,{'state':'waiting','context':c19});process(cls.root,cls.state19,cfg);cls.real19=source(cls.root,cls.key19)
 @classmethod
 def tearDownClass(cls):cls.tmp.cleanup()
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.dir=Path(self.temp.name).resolve();self.binding=SimpleNamespace(config_sha256='a'*64,config={'workspace':str(self.dir/'knowledge'),'endpoint':'https://fixture.invalid','owner_scope':'crowd-owner-main','scope':['fixture','existing-authorized-space','private-feedback']},authenticate=lambda client:{'kind':'central_owner_service','human_uid':None})
  self.s=copy.deepcopy(self.real);self.service=MaterialFeedback(self.dir,self.binding,object(),resolver=lambda root,key:copy.deepcopy(self.s)if key==self.s['pro_key']else (_ for _ in()).throw(BindingError('foreign_scope')))
  self.request=next(iter(self.s['items']));cap=self.s['items'][self.request]['metadata']['capture'];self.p={'intent_id':str(uuid.uuid4()),'pro_key':self.s['pro_key'],'expected_job':self.s['job_id'],'request':self.request,'record_hash':cap['pro_payload']['record']['record_hash'],'kind':'want_to_know','reason':'isolated saved-input feedback test','quote':cap['pro_payload']['record'].get('body','')[:8],'experience_confirmed':False,'consent_private':True}
 def test_real_saved_jobs_consumer_sdk_feedback_receipt_payload_scope(self):
  view=self.service.preview({'pro_key':self.s['pro_key']});self.assertEqual(len(view['items']),2);self.assertEqual(view['pack_ref']['pack_id'],'social-observations');r=self.service.submit(self.p);self.assertEqual(r['state'],'pending_feedback');self.assertIsNone(r['human_uid']);self.assertFalse(r['reviewed']);self.assertNotEqual(r['source_project'],r['knowledge_scope']['project']);self.assertEqual(self.service.status({'intent_id':self.p['intent_id']}),r)
  store=self.service.store(True)
  try:
   receipt=store.get_receipt(self.p['intent_id']);payload=json.loads(store.get_payload(self.p['intent_id'])['payload_bytes']);self.assertEqual(receipt['channel'],'consumer');self.assertEqual(receipt['actor_ref'],self.service.actor);self.assertEqual(payload['source_scope'],self.s['source_scope']);self.assertEqual(payload['pack_ref'],self.s['pack_ref']);self.assertEqual(store._conn.execute('select count(*)from proposals').fetchone()[0],0);self.assertEqual(store._conn.execute('select count(*)from package_releases').fetchone()[0],0)
  finally:store.close()
 def test_same_uuid_no_rewrite_and_conflict(self):
  r=self.service.submit(self.p)
  with patch.object(self.service,'store',side_effect=AssertionError('no write replay')):self.assertEqual(self.service.submit(self.p),r)
  with self.assertRaisesRegex(BindingError,'conflict'):self.service.submit({**self.p,'reason':'changed'})
 def test_before_commit_unknown_blocks_same_and_new_id_even_reopen(self):
  with patch.object(self.service,'store',side_effect=OSError('unknown precommit')):r=self.service.submit(self.p)
  self.assertEqual(r['state'],'outcome_unknown');self.assertEqual(self.service.submit(self.p)['state'],'outcome_unknown')
  self.assertEqual(self.service.submit({**self.p,'intent_id':str(uuid.uuid4())})['intent_id'],self.p['intent_id']);self.assertEqual(len(self.service.journals()),1)
  again=MaterialFeedback(self.dir,self.binding,object(),resolver=lambda*a:self.s)
  self.assertEqual(again.submit({**self.p,'intent_id':str(uuid.uuid4())})['intent_id'],self.p['intent_id']);self.assertEqual(len(again.journals()),1)
  self.assertEqual(again.status({'intent_id':self.p['intent_id']})['state'],'outcome_unknown')
 def test_after_commit_unknown_status_reconciles_original_without_rewrite(self):
  original=KnowledgeStore.feedback
  def committed(store,*a,**kw):original(store,*a,**kw);raise OSError('lost response')
  with patch.object(KnowledgeStore,'feedback',committed):self.assertEqual(self.service.submit(self.p)['state'],'outcome_unknown')
  with patch.object(KnowledgeStore,'feedback',side_effect=AssertionError('no replay')):r=self.service.status({'intent_id':self.p['intent_id']})
  self.assertEqual(r['state'],'pending_feedback');self.assertEqual(len(self.service.preview({'pro_key':self.s['pro_key']})['feedback']),1)
 def test_old_job_record_quote_foreign_and_injected_privilege_rejected(self):
  for patch_,error in [({'expected_job':'b'*64},'current_changed'),({'record_hash':'b'*64},'record_changed'),({'quote':'not an actual quote'},'quote_mismatch'),({'request':str(uuid.uuid4())},'scope_mismatch'),({'actor':'reviewer'},'request_invalid'),({'consent_private':False},'request_invalid'),({'kind':'experienced'},'request_invalid')]:
   with self.subTest(patch_=patch_):
    with self.assertRaisesRegex(BindingError,error):self.service.submit({**self.p,**patch_})
  self.assertEqual(self.service.journals(),[])
 def test_explicit_experience_only_not_inferred(self):
  r=self.service.submit({**self.p,'kind':'experienced','experience_confirmed':True});self.assertEqual(r['kind'],'experienced');self.assertFalse(r['reviewed'])
 def test_cross_knowledge_scope_uuid_cannot_read(self):
  self.service.submit(self.p);other=copy.copy(self.binding);other.config_sha256='b'*64;other.config={**self.binding.config,'scope':['fixture','other','private-feedback']};s=MaterialFeedback(self.dir,other,object(),resolver=lambda*a:self.s);self.assertEqual(s.status({'intent_id':self.p['intent_id']})['state'],'not_found')
 def test_proposal_config_change_preserves_original_feedback_read_scope(self):
  result=self.service.submit(self.p);other=copy.copy(self.binding);other.config_sha256='c'*64;again=MaterialFeedback(self.dir,other,object(),resolver=lambda*a:self.s);self.assertEqual(again.status({'intent_id':self.p['intent_id']}),result)
 def test_utf8_2000_reason_roundtrip_no_commit_without_queryability(self):
  p={**self.p,'reason':'🌕'*2000,'quote':''};r=self.service.submit(p);self.assertEqual(r['state'],'pending_feedback');self.assertEqual(self.service.status({'intent_id':p['intent_id']}),r);self.assertEqual(self.service.submit(p),r);self.assertEqual(len(self.service.preview({'pro_key':p['pro_key']})['feedback']),1)
  journal=self.service.folder/(p['intent_id']+'.json');self.assertGreater(journal.stat().st_size,16384);self.assertLess(journal.stat().st_size,65536)
 def test_encoded_journal_limit_rejected_before_intent_and_sdk(self):
  import material_feedback
  with patch.object(material_feedback,'MAX_JOURNAL_BYTES',100),patch.object(KnowledgeStore,'feedback',side_effect=AssertionError('no write')):
   with self.assertRaisesRegex(BindingError,'journal_limit'):self.service.submit(self.p)
  self.assertEqual(self.service.journals(),[])
 def test_sdk_project_actor_pack_schema_not_relaxed(self):
  scope={'tenant':'fixture','project':'actual-project','space':'private-feedback'};store=KnowledgeStore(self.dir/'direct',AuthContext(**scope,role='consumer',actor_ref='service'));self.addCleanup(store.close)
  payload={'x':1};env={'contract_version':'ctfs-knowledge-envelope/0.1','submission_id':str(uuid.uuid4()),'project_id':'foreign','pack_ref':self.s['pack_ref'],'channel':'consumer','actor':{'ref':'service'},'purpose':'feedback_material','consent_ref':None,'consent':{'scope':'private','granted_at':'2026-10-19T00:00:00Z','granted_by':'service'},'source_refs':[],'payload_ref':{'store':'inline','key':'test','type':'feedback','hash':digest(canonical(payload))},'operation':'feedback','idempotency_key':'original-id'}
  with self.assertRaisesRegex(KnowledgeError,'project_id'):store.feedback(env,payload,'ignore','test')
  env['project_id']='actual-project';env['actor']['ref']='foreign'
  with self.assertRaisesRegex(KnowledgeError,'actor'):store.feedback(env,payload,'ignore','test')
  env['actor']['ref']='service';env['pack_ref']={**env['pack_ref'],'hash':'not-hash'}
  with self.assertRaises(Exception):store.feedback(env,payload,'ignore','test')
 def test_original_four_acks_both_scopes_feedback_stays_private(self):
  for src in (self.real19,self.real):
   self.s=copy.deepcopy(src)
   for request,item in self.s['items'].items():
    p={**self.p,'intent_id':str(uuid.uuid4()),'pro_key':src['pro_key'],'expected_job':src['job_id'],'request':request,'record_hash':item['metadata']['capture']['pro_payload']['record']['record_hash'],'quote':''}
    self.assertEqual(self.service.submit(p)['state'],'pending_feedback')
  self.assertEqual(len(self.service.journals()),4)
 def test_real_legal_other_scope_pointer_is_rejected(self):
  before=self.state.read_bytes();row=private_json(self.state);row['publication_pointer']=private_json(self.state19)['publication_pointer'];write(self.state,row)
  try:
   with self.assertRaisesRegex(BindingError,'scope_mismatch'):source(self.root,self.key)
  finally:self.state.write_bytes(before)
 def test_real_resolver_rejects_wrong_pointer_project(self):
  before=self.state.read_bytes();row=private_json(self.state);row['source_scope']['task_id']=19;write(self.state,row)
  try:
   with self.assertRaisesRegex(BindingError,'scope_mismatch'):source(self.root,self.key)
  finally:self.state.write_bytes(before)
if __name__=='__main__':unittest.main()
