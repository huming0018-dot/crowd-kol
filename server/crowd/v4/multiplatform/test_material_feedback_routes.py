from pathlib import Path
import hashlib,json,sys,tempfile,unittest
from types import SimpleNamespace
from unittest.mock import patch
HERE=Path(__file__).resolve().parent;MP=HERE;sys.path.insert(0,str(MP))
from owner_knowledge_publication_service import OwnerKnowledgePublicationService
from owner_knowledge_binding import BindingError
from dashboard import Application
from material_feedback import MaterialFeedback
import knowledge_review_call
class Routes(unittest.TestCase):
 def test_original_four_config_keys_compatible_optional_fifth_only(self):
  with tempfile.TemporaryDirectory()as tmp:
   path=Path(tmp).resolve()/'service.json';base={'review_config':'a','review_sha256':'b','publication_config':'c','publication_sha256':'d'}
   def construct(cfg):
    raw=json.dumps(cfg).encode();path.write_bytes(raw);path.chmod(0o600);fake=SimpleNamespace(binding=SimpleNamespace(config_sha256='e'*64))
    with patch('owner_knowledge_publication_service.OwnerKnowledgeService',return_value=fake),patch('owner_knowledge_publication_service.OwnerKnowledgePublication',return_value=fake):return OwnerKnowledgePublicationService(path,hashlib.sha256(raw).hexdigest(),object())
   self.assertIsNone(construct(base).material_root);self.assertEqual(construct({**base,'material_root':tmp}).material_root,tmp)
   with self.assertRaisesRegex(BindingError,'config_invalid'):construct({**base,'workspace':'arbitrary'})
 def test_normal_knowledge_service_entry_and_legacy_not_configured(self):
  s=object.__new__(OwnerKnowledgePublicationService);s._check=lambda:None;s.material_root=None
  with self.assertRaisesRegex(BindingError,'not_configured'):s.request({'action':'material_feedback_preview','payload':{'pro_key':'x'}})
  s.material_root='/tmp';s.review=SimpleNamespace(binding=object());s.client=object()
  with patch('material_feedback.MaterialFeedback')as cls:
   cls.return_value.request.return_value={'state':'feedback_preview'}
   self.assertEqual(s.request({'action':'material_feedback_preview','payload':{'pro_key':'x'}}),{'state':'feedback_preview'});cls.return_value.request.assert_called_once_with('material_feedback_preview',{'pro_key':'x'})
 def test_normal_cloud_owner_only_no_worker_or_source(self):
  app=object.__new__(Application);app.cloud_client=SimpleNamespace(role='owner');app.knowledge_request=lambda body:body
  for a in ('material_feedback_preview','material_feedback_submit','material_feedback_status'):
   self.assertEqual(app.cloud(a,{'x':1}),{'action':a,'payload':{'x':1}})
  app.cloud_client.role='participant'
  with self.assertRaisesRegex(ValueError,'owner_authorization'):app.cloud('material_feedback_submit',{})
 def test_subprocess_allowlist_precise_write_unknown_and_prewrite(self):
  with tempfile.TemporaryDirectory()as tmp:
   root=Path(tmp).resolve();p=root/'config.json';p.write_text(json.dumps({'python':'p','script':'s','script_sha256':'s','request':'r','request_sha256':'r'}));p.chmod(0o600)
   def run(argv,**kw):kw['stdout'].write(b'{"state":"feedback_preview"}');return SimpleNamespace(returncode=0)
   with patch.object(knowledge_review_call,'material_command',return_value=['python','-B','script']),patch.object(knowledge_review_call.subprocess,'run',side_effect=run):self.assertEqual(knowledge_review_call.call(p,root/'cloud',{'action':'material_feedback_preview','payload':{}})['state'],'feedback_preview')
   with patch.object(knowledge_review_call,'material_command',return_value=['python','-B','script']),patch.object(knowledge_review_call.subprocess,'run',side_effect=knowledge_review_call.subprocess.TimeoutExpired('cmd',25)):
    with self.assertRaisesRegex(ValueError,'outcome_unknown'):knowledge_review_call.call(p,root/'cloud',{'action':'material_feedback_submit','payload':{}})
   def denied(argv,**kw):kw['stdout'].write(b'{"error":"material_feedback_current_changed"}');return SimpleNamespace(returncode=2)
   with patch.object(knowledge_review_call,'material_command',return_value=['python','-B','script']),patch.object(knowledge_review_call.subprocess,'run',side_effect=denied):self.assertEqual(knowledge_review_call.call(p,root/'cloud',{'action':'material_feedback_submit','payload':{}})['state'],'not_submitted')
if __name__=='__main__':unittest.main()
