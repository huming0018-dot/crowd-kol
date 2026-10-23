"""Actual saved feedback/ACKs and original065, copied before every business write."""
from pathlib import Path
import hashlib,json,os,shutil,sqlite3,tempfile,unittest
from unittest.mock import patch
from owner_knowledge_binding import OwnerKnowledgeBinding,canonical,BindingError
from owner_target_intake import OwnerTargetIntake
from toolbox.knowledge import KnowledgeStore,AuthContext
from cloud_sync import CloudClient
from material_feedback import MaterialFeedback

class Intake(unittest.TestCase):
 def setUp(self):
  saved=Path(os.environ['CROWD_TARGET_TEST_FIXTURE']);meta=json.loads((saved/'RESULT.PRIVATE.json').read_bytes())
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name).resolve();self.scope=meta['scope']
  self.workspace=self.root/'knowledge';db=self.workspace.joinpath(*self.scope,'knowledge.sqlite3');db.parent.mkdir(parents=True)
  before=Path(os.environ['CROWD_KNOWLEDGE_PRETARGET_DATABASE'])
  with sqlite3.connect(before.as_uri()+'?mode=ro',uri=True)as old,sqlite3.connect(db)as new:old.backup(new)
  self.database=db;self.before_sha=hashlib.sha256(before.read_bytes()).hexdigest();self.before=before
  config={**meta['binding']}
  path=self.root/'original-binding.json';path.write_bytes(canonical(config));path.chmod(0o600)
  self.source=OwnerKnowledgeBinding(path,hashlib.sha256(path.read_bytes()).hexdigest())
  target=json.loads((saved/'PREVIEW-CONFIG.PRIVATE.json').read_bytes())
  config.update(workspace=str(self.workspace),candidate=target['candidate_pack'],candidate_hash=target['candidate_hash'],proposal_id=target['proposal_id'],target_version='0.1.2',proposal_channel='owner',intents=str(self.root/'target-intents'))
  path=self.root/'target-binding.json';path.write_bytes(canonical(config));path.chmod(0o600)
  self.target=OwnerKnowledgeBinding(path,hashlib.sha256(path.read_bytes()).hexdigest())
  shutil.copytree(saved/'feedback-root',self.root/'materials')
  self.client=object.__new__(CloudClient);self.client.role='owner';self.client.endpoint=config['endpoint']
  auth=patch.object(CloudClient,'call',return_value={'tasks':[]});auth.start();self.addCleanup(auth.stop)
  workspace=self.workspace
  class Feedback(MaterialFeedback):
   # Preserve the saved feedback actor/binding identity; redirect only its SDK store to the copy.
   def store(self,readonly=False):return KnowledgeStore(workspace,AuthContext(**self.scope,role='consumer',actor_ref=self.actor),read_only=readonly)
  feedback=patch('owner_target_intake.MaterialFeedback',Feedback);feedback.start();self.addCleanup(feedback.stop)
  self.intake=OwnerTargetIntake(self.source,self.target,self.client,self.root/'materials',meta['manifest'],meta['manifest_sha256'],meta['feedback_intent'])
  self.old=self.rows()
 def tearDown(self):self.assertEqual(hashlib.sha256(self.before.read_bytes()).hexdigest(),self.before_sha)
 def rows(self):
  with sqlite3.connect(self.database.as_uri()+'?mode=ro',uri=True)as db:
   return{n:db.execute('SELECT *FROM "'+n+'"ORDER BY rowid').fetchall()for n, in db.execute("SELECT name FROM sqlite_master WHERE type='table'AND name NOT LIKE 'sqlite_%'")}
 def test_real_native_single_submit_readback_and_exact_replay_no_new_audit(self):
  self.assertEqual(self.intake.status()['state'],'not_prepared');value=self.intake.submit();self.assertEqual(value['state'],'target_proposal_recorded')
  after=self.rows();delta={key:len(after[key])-len(rows)for key,rows in self.old.items()}
  self.assertEqual({k:v for k,v in delta.items()if v},{'submissions':1,'evidence_refs':3,'proposals':1,'audit_events':2})
  for name,old in self.old.items():self.assertEqual(after[name][:len(old)],old,name)
  with patch.object(KnowledgeStore,'propose',side_effect=AssertionError('never replay')):
   self.assertEqual(self.intake.submit(),value);self.assertEqual(self.intake.status(),value)
  self.assertEqual(self.rows(),after)
 def test_unknown_before_commit_remains_unknown_without_second_call(self):
  with patch.object(KnowledgeStore,'propose',side_effect=OSError('before commit')):self.assertEqual(self.intake.submit()['state'],'outcome_unknown')
  with patch.object(KnowledgeStore,'propose',side_effect=AssertionError('never replay')):
   self.assertEqual(self.intake.submit()['state'],'outcome_unknown');self.assertEqual(self.intake.status()['state'],'outcome_unknown')
  self.assertEqual(self.rows(),self.old)
 def test_unknown_after_commit_reconciles_original_receipt_no_replay(self):
  original=KnowledgeStore.propose
  def committed(store,*args,**kwargs):original(store,*args,**kwargs);raise OSError('lost response')
  with patch.object(KnowledgeStore,'propose',committed):self.assertEqual(self.intake.submit()['state'],'outcome_unknown')
  before=self.rows()
  with patch.object(KnowledgeStore,'propose',side_effect=AssertionError('never replay')):self.assertEqual(self.intake.status()['state'],'target_proposal_recorded')
  self.assertEqual(self.rows(),before)
 def test_final_journal_write_failure_never_returns_recorded_until_status_reconciles(self):
  with patch('owner_target_intake.write',side_effect=OSError('durability failure')):
   with self.assertRaises(OSError):self.intake.submit()
  before=self.rows();self.assertEqual(json.loads(self.intake.path.read_bytes())['state'],'attempted_no_retry')
  with patch.object(KnowledgeStore,'propose',side_effect=AssertionError('never replay')):self.assertEqual(self.intake.status()['state'],'target_proposal_recorded')
  self.assertEqual(self.rows(),before)
 def test_manifest_or_journal_drift_refuses_without_new_sdk_write(self):
  self.intake.submit();before=self.rows();value=json.loads(self.intake.path.read_bytes());value['identity']['feedback_intent']='other';self.intake.path.write_bytes(canonical(value))
  with patch.object(KnowledgeStore,'propose',side_effect=AssertionError('no write')):
   with self.assertRaisesRegex(BindingError,'intake_changed'):self.intake.submit()
  self.assertEqual(self.rows(),before)
 def test_auth_failure_precedes_journal_or_sdk_access(self):
  self.source.authenticate=lambda _:(_ for _ in ()).throw(BindingError('owner_denied'))
  with patch.object(self.intake,'owner',side_effect=AssertionError('no store')):
   with self.assertRaisesRegex(BindingError,'owner_denied'):self.intake.submit()
  self.assertFalse(self.intake.path.exists())

if __name__=='__main__':unittest.main()
