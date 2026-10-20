"""Real 065 owner proposals in disposable stores; only CloudClient auth is stubbed."""
from pathlib import Path
import hashlib,json,os,tempfile,unittest,uuid
from unittest.mock import patch
from toolbox.knowledge import KnowledgeStore,AuthContext,_candidate_hash
from owner_knowledge_binding import OwnerKnowledgeBinding,BindingError,canonical
from cloud_sync import CloudClient

class OwnerTarget(unittest.TestCase):
 def setUp(self):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name).resolve()
  manifest=json.loads(Path(os.environ['CROWD_KNOWLEDGE_DRAFT_MANIFEST']).read_bytes());candidate=self.root/'candidate';candidate.mkdir()
  for name,ref in manifest['files'].items():
   raw=Path(ref['path']).read_bytes();self.assertEqual(hashlib.sha256(raw).hexdigest(),ref['sha256']);(candidate/name).write_bytes(raw)
  self.hash=_candidate_hash(candidate);self.scope={'tenant':'fixture','project':'target','space':'private'};self.sid=str(uuid.uuid4());self.pid='prop:'+self.sid
  self.config={'schema':'crowd-owner-knowledge-binding-v1','endpoint':'https://fixture.supabase.co/functions/v1/crowd-machine','owner_scope':'crowd-owner-main','scope':list(self.scope.values()),'authorization_ref':'fixture-target','workspace':str(self.root/'knowledge'),'candidate':str(candidate),'proposal_id':self.pid,'candidate_hash':self.hash,'intents':str(self.root/'intents'),'target_version':'0.1.2','manager_actor':'service:manager','reviewer_actor':'service:reviewer','proposal_channel':'owner'}
  self.path=self.root/'binding.json';self.save()
  self.client=object.__new__(CloudClient);self.client.role='owner';self.client.endpoint=self.config['endpoint']
  self.cloud=patch.object(CloudClient,'call',return_value={'tasks':[]});self.cloud.start();self.addCleanup(self.cloud.stop)
 def save(self):self.path.write_bytes(canonical(self.config));self.path.chmod(0o600);self.sha=hashlib.sha256(self.path.read_bytes()).hexdigest()
 def binding(self):return OwnerKnowledgeBinding(self.path,self.sha)
 def propose(self,actor='service:manager',version='0.1.2'):
  payload={'candidate_hash':self.hash};h=hashlib.sha256(canonical(payload)).hexdigest()
  env={'contract_version':'ctfs-knowledge-envelope/0.1','submission_id':self.sid,'project_id':'target','pack_ref':{'pack_id':'social-observations','version':version,'hash':self.hash},'channel':'owner','actor':{'ref':actor},'purpose':'owner_target_review','consent_ref':None,'consent':{'scope':'private','granted_at':'2026-10-20T00:00:00Z','granted_by':actor},'source_refs':[{'category':'crowd_observation','locator':'fixture-public-source','version':'1','hash':h}],'payload_ref':{'store':'inline','key':self.sid,'type':'proposal','hash':h},'operation':'propose','idempotency_key':self.sid}
  store=KnowledgeStore(self.root/'knowledge',AuthContext(**self.scope,role='owner',actor_ref=actor))
  try:store.propose(env,payload)
  finally:store.close()
 def decide(self,intent=None):return self.binding().decide(self.client,decision='approved',reason='Explicit fixture review only',expected_candidate_hash=self.hash,intent_id=intent or str(uuid.uuid4()))
 def counts(self):
  store=KnowledgeStore(self.root/'knowledge',AuthContext(**self.scope,role='admin',actor_ref='service:manager'),read_only=True)
  try:return{t:store._conn.execute('SELECT count(*) FROM '+t).fetchone()[0]for t in ('review_grants','review_decisions','package_releases','pin_history')}
  finally:store.close()
 def test_real_owner_proposal_distinct_service_reviewer_not_release(self):
  self.propose();result=self.decide();self.assertFalse(result['human_identity_claimed']);self.assertFalse(result['release_or_pin_performed']);self.assertEqual(result['decision']['decision'],'approved')
  self.assertEqual(self.counts(),{'review_grants':1,'review_decisions':1,'package_releases':0,'pin_history':0})
 def test_wrong_owner_or_version_refused_before_intent_and_grant(self):
  for change in ('owner','version'):
   with self.subTest(change=change):
    # A fresh proposal/workspace per mismatch proves no earlier side effect masks the test.
    self.sid=str(uuid.uuid4());self.config['proposal_id']='prop:'+self.sid;self.save()
    self.propose(actor='service:foreign'if change=='owner'else'service:manager',version='0.1.1'if change=='version'else'0.1.2')
    with self.assertRaisesRegex(BindingError,'knowledge_owner_proposal_changed'):self.decide()
    self.assertEqual(self.counts()['review_grants'],0);self.assertEqual(self.counts()['review_decisions'],0)
    self.assertEqual(list((self.root/'intents').glob('*.json')),[])
 def test_channel_only_from_fixed_mapping_and_legacy_default_preserved(self):
  self.config.pop('proposal_channel');self.save();self.assertEqual(self.binding().config.get('proposal_channel','model'),'model')
  self.config['proposal_channel']='admin';self.save()
  with self.assertRaises(BindingError):self.binding()
 def test_same_manager_reviewer_rejected(self):
  self.config['reviewer_actor']=self.config['manager_actor'];self.save()
  with self.assertRaises(BindingError):self.binding()
 def test_completed_exact_intent_replay_does_not_require_proposed_again(self):
  self.propose();intent=str(uuid.uuid4());result=self.decide(intent)
  with patch.object(KnowledgeStore,'grant_review',side_effect=AssertionError('must not regrant')):self.assertEqual(self.decide(intent),result)
  self.assertEqual(self.counts()['review_grants'],1);self.assertEqual(self.counts()['review_decisions'],1)
 def test_unknown_after_grant_blocks_new_intent_and_no_repeat(self):
  self.propose()
  with patch.object(KnowledgeStore,'review',side_effect=OSError('fixture lost outcome')):
   with self.assertRaises(OSError):self.decide()
  before=self.counts();self.assertEqual(before['review_grants'],1);self.assertEqual(before['review_decisions'],0)
  with patch.object(KnowledgeStore,'grant_review',side_effect=AssertionError('no unknown replay')):
   with self.assertRaisesRegex(BindingError,'knowledge_decision_outcome_unknown'):self.decide()
  self.assertEqual(self.counts(),before)

if __name__=='__main__':unittest.main()
