"""Real SDK clone integration. CROWD_KNOWLEDGE_FIXTURE points to an existing saved fixture."""
from pathlib import Path
import hashlib,importlib.util,json,os,subprocess,sys,tempfile,unittest,uuid
from unittest.mock import patch
TARGET=Path(os.environ['CROWD_KNOWLEDGE_TARGET']).resolve()
sys.path.insert(0,str(TARGET))
sys.path.append(os.environ['CROWD_MP_ROOT'])
import owner_knowledge_binding as binding_module
import owner_knowledge_service as service_module
from cloud_sync import CloudClient
from toolbox.knowledge import KnowledgeStore
fixture=Path(os.environ['CROWD_KNOWLEDGE_FIXTURE']).resolve()
spec=importlib.util.spec_from_file_location('saved_knowledge_scope_fixture',fixture)
f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
assert Path(binding_module.__file__).parent.resolve()==TARGET
assert Path(service_module.__file__).parent.resolve()==TARGET
class Scope(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.cloud=patch.object(CloudClient,'call',return_value={'tasks':[]});self.cloud.start()
  self.case=f.Service();self.service,self.binding,self.source,self.before=self.case.setup_service(Path(self.tmp.name).resolve())
  # Production previews use an immutable seed, separate from the mutable SDK workspace.
  preview_path=Path(self.service.config['preview_config']);preview=json.loads(preview_path.read_text());preview.update(database=str(self.source),database_sha256=self.before);preview_path.write_bytes(binding_module.canonical(preview))
  config_path=Path(self.service.config_path);config=json.loads(config_path.read_text());config['preview_config_sha256']=hashlib.sha256(preview_path.read_bytes()).hexdigest();config_path.write_bytes(binding_module.canonical(config))
  self.service=service_module.OwnerKnowledgeService(config_path,hashlib.sha256(config_path.read_bytes()).hexdigest(),self.service.client)
 def tearDown(self):
  self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),self.before);self.cloud.stop();self.tmp.cleanup()
 def request(self):return self.case.payload(self.service.preview())
 def counts(self):return self.case.counts(self.binding)
 def test_new_preview_and_direct_binding_cannot_bypass_unknown(self):
  first=self.request()
  with patch.object(KnowledgeStore,'grant_review',side_effect=RuntimeError('fixture fault before write')):
   with self.assertRaises(RuntimeError):self.service.decide(first)
  preview=self.service.preview();self.assertFalse(preview['decision_available']);self.assertEqual(preview['unresolved_decisions'],[first['intent_id']]);self.assertTrue(all(not x['enabled']for x in preview['actions'].values()))
  second=self.case.payload(preview)
  with self.assertRaisesRegex(binding_module.BindingError,'knowledge_decision_outcome_unknown'):self.service.decide(second)
  direct={k:v for k,v in second.items()if k!='preview_token'}
  with self.assertRaisesRegex(binding_module.BindingError,'knowledge_decision_outcome_unknown'):self.service.binding.decide(self.service.client,**direct)
  self.assertEqual(set(self.counts().values()),{0});self.assertEqual(self.service.status({'intent_id':first['intent_id']})['state'],'outcome_unknown')
 def test_after_grant_unknown_does_not_add_another_grant_or_review(self):
  first=self.request()
  with patch.object(KnowledgeStore,'review',side_effect=RuntimeError('fixture after grant')):
   with self.assertRaises(RuntimeError):self.service.decide(first)
  before=self.counts();self.assertEqual(before['review_grants'],1);self.assertEqual(before['review_decisions'],0)
  with self.assertRaisesRegex(binding_module.BindingError,'knowledge_decision_outcome_unknown'):self.service.decide(self.request())
  self.assertEqual(self.counts(),before)
 def test_completed_exact_replay_and_status_unchanged(self):
  first=self.request();result=self.service.decide(first);self.assertEqual(result['state'],'accepted');self.assertEqual(result,self.service.decide(first));self.assertEqual(result,self.service.status({'intent_id':first['intent_id']}));self.assertEqual(self.counts()['review_decisions'],1);self.assertFalse(self.service.binding.unresolved_decisions())
 def test_same_intent_changed_reason_rejected(self):
  first=self.request();self.service.decide(first)
  with self.assertRaisesRegex(binding_module.BindingError,'knowledge_intent_conflict'):self.service.decide({**first,'reason':'different engineering reason'})
  self.assertEqual(self.counts()['review_decisions'],1)
 def test_corrupt_or_symlink_journal_fails_before_business_write(self):
  request=self.request();directory=Path(self.binding['intents']);path=directory/(str(uuid.uuid4())+'.json');path.write_text('{');path.chmod(0o600)
  with self.assertRaises(binding_module.BindingError):self.service.decide(request)
  self.assertEqual(set(self.counts().values()),{0});path.unlink();target=directory/'foreign';target.write_text('{}');target.chmod(0o600);path.symlink_to(target)
  with self.assertRaises(binding_module.BindingError):self.service.decide(request)
  self.assertEqual(set(self.counts().values()),{0})
 def test_cross_process_proposal_lock_and_known_busy_retry(self):
  request=self.request();code="import sys;sys.path.insert(0,sys.argv[1]);sys.path.append(__import__('os').environ['CROWD_MP_ROOT']);from owner_knowledge_binding import OwnerKnowledgeBinding; b=OwnerKnowledgeBinding(sys.argv[2],sys.argv[3]);\nwith b._decision_lock():\n print('locked',flush=True);sys.stdin.readline()"
  child=subprocess.Popen([sys.executable,'-B','-c',code,str(TARGET),str(self.service.binding.config_path),self.service.binding.config_sha256],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
  try:
   self.assertEqual(child.stdout.readline().strip(),'locked')
   with self.assertRaisesRegex(binding_module.BindingError,'knowledge_decision_in_progress'):self.service.decide(request)
   self.assertEqual(set(self.counts().values()),{0})
  finally:
   stdout,stderr=child.communicate('\n',timeout=10)
   self.assertEqual(child.returncode,0,stderr)
  self.assertEqual(self.service.decide(request)['state'],'accepted');self.assertEqual(self.counts()['review_decisions'],1)
if __name__=='__main__':unittest.main()
