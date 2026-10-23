"""Fixed target selection reuses original review/publication routes and UNKNOWN handling."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json,tempfile,unittest
from owner_knowledge_publication_service import OwnerKnowledgePublicationService
from owner_knowledge_binding import BindingError
import knowledge_review_call as boundary

class TargetRoutes(unittest.TestCase):
 def service(self):
  service=object.__new__(OwnerKnowledgePublicationService);service._check=lambda:None
  service.review=SimpleNamespace(binding=SimpleNamespace(config={'target_version':'0.3.4','proposal_id':'prop:old'},authenticate=lambda _:None));service.client=object()
  service.target=SimpleNamespace(review=SimpleNamespace(binding=SimpleNamespace(config={'target_version':'0.1.2','proposal_id':'prop:new'})),request=lambda value:{'forwarded':value})
  return service
 def test_exact_target_routes_no_arbitrary_knowledge_or_feedback_forwarding(self):
  service=self.service()
  for action in ('preview','decide','status','publication_preview','publication_release','publication_pin','publication_rollback','publication_status','publication_read'):
   payload={'intent_id':'fixture'};result=service.request({'action':'target_'+action,'payload':payload})
   self.assertEqual(result,{'forwarded':{'action':action,'payload':payload}})
  for action in ('target_material_feedback_submit','target_target_decide','target_drop','target_material_releases'):
   with self.assertRaises(BindingError):service.request({'action':action,'payload':{}})
 def test_choices_are_owner_authenticated_and_no_paths_or_actor_inputs(self):
  service=self.service();result=service.request({'action':'proposal_choices','payload':{}})
  self.assertEqual(result['default_key'],'target');self.assertEqual([x['key']for x in result['items']],['original','target'])
  service.target=None;self.assertEqual(service.request({'action':'proposal_choices','payload':{}})['default_key'],'original')
  service.review.binding.authenticate=lambda _:(_ for _ in ()).throw(BindingError('denied'))
  with self.assertRaisesRegex(BindingError,'denied'):service.request({'action':'proposal_choices','payload':{}})
 def call(self,action,runner):
  with tempfile.TemporaryDirectory()as tmp:
   root=Path(tmp).resolve();config=root/'runtime.json';config.write_text(json.dumps({'python':'/python','script':'/runtime/service.py','script_sha256':'a'*64,'request':'/runtime/service.json','request_sha256':'b'*64}));config.chmod(0o600)
   with patch.object(boundary,'material_command',return_value=['/python','-B','/runtime/service.py']),patch.object(boundary.subprocess,'run',side_effect=runner):
    return boundary.call(config,root/'cloud.json',{'action':action,'payload':{}})
 def test_target_write_timeout_unknown_reads_read_failure(self):
  def timeout(*args,**kwargs):raise boundary.subprocess.TimeoutExpired('fixture',25)
  for action in ('target_prepare','target_decide','target_publication_release','target_publication_pin','target_publication_rollback'):
   with self.assertRaisesRegex(ValueError,'knowledge_outcome_unknown'):self.call(action,timeout)
  for action in ('target_prepare_status','target_preview','target_status','target_publication_preview','proposal_choices'):
   with self.assertRaisesRegex(ValueError,'knowledge_read_unavailable'):self.call(action,timeout)
 def test_target_known_prewrite_rejected_not_unknown(self):
  def runner(*args,**kwargs):kwargs['stdout'].write(b'{"error":"knowledge_owner_proposal_changed"}');return SimpleNamespace(returncode=2)
  result=self.call('target_decide',runner);self.assertEqual(result['state'],'not_submitted')

if __name__=='__main__':unittest.main()
