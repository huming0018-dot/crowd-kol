"""Portable service and existing subprocess boundary; no network/store/source execution."""
from pathlib import Path
import importlib,os,json,sys,tempfile,unittest
from types import SimpleNamespace
from unittest.mock import patch
HERE=Path(__file__).resolve().parent
TARGET=Path(os.environ.get('CROWD_FEEDBACK_CANDIDATE',str(HERE/'candidate'if(HERE/'candidate').is_dir()else HERE)))
MP=Path(os.environ.get('CROWD_MP_ROOT',str(HERE)))
if not(MP/'owner_knowledge_binding.py').is_file():raise RuntimeError('Set CROWD_MP_ROOT to original multiplatform support; missing evidence is not a skip')
sys.path[:0]=[str(TARGET),str(MP)]
from owner_knowledge_publication_service import OwnerKnowledgePublicationService
from owner_knowledge_binding import BindingError
import knowledge_review_call
class InboxRoutes(unittest.TestCase):
 def test_service_dispatches_inbox_original_after_without_UUID_requirement(self):
  service=object.__new__(OwnerKnowledgePublicationService);service._check=lambda:None;service.material_root='/fixture-owned-root';service.review=SimpleNamespace(binding=object());service.client=object()
  with patch('material_feedback.MaterialFeedback')as cls:
   cls.return_value.request.return_value={'state':'material_feedback_inbox','items':[],'next_cursor':None}
   result=service.request({'action':'material_feedback_inbox','payload':{'after':None}})
   self.assertEqual(result['state'],'material_feedback_inbox');cls.assert_called_once_with(service.material_root,service.review.binding,service.client);cls.return_value.request.assert_called_once_with('material_feedback_inbox',{'after':None})
 def test_missing_config_and_invalid_outer_payload_refuse_before_dispatch(self):
  service=object.__new__(OwnerKnowledgePublicationService);service._check=lambda:None;service.material_root=None
  with patch('material_feedback.MaterialFeedback',side_effect=AssertionError('not dispatched')):
   with self.assertRaisesRegex(BindingError,'not_configured'):service.request({'action':'material_feedback_inbox','payload':{'after':None}})
   with self.assertRaisesRegex(BindingError,'request_invalid'):service.request({'action':'material_feedback_inbox','payload':'bad'})
 def config(self,root):
  p=root/'runtime.json';p.write_text(json.dumps({'python':'/python','script':'/runtime/service.py','script_sha256':'a'*64,'request':'/runtime/service-config.json','request_sha256':'b'*64}));p.chmod(0o600);return p
 def test_existing_subprocess_inbox_exact_allowlisted_frame_and_pagination(self):
  with tempfile.TemporaryDirectory()as tmp:
   root=Path(tmp).resolve();cfg=self.config(root);seen=[]
   def run(argv,**kw):
    seen.append((argv,json.loads(kw['input'])));kw['stdout'].write(b'{"state":"material_feedback_inbox","items":[],"next_cursor":null}');return SimpleNamespace(returncode=0)
   with patch.object(knowledge_review_call,'material_command',return_value=['/python','-B','/runtime/service.py']),patch.object(knowledge_review_call.subprocess,'run',side_effect=run):
    for after in (None,'00000000-0000-4000-8000-000000000001'):
     result=knowledge_review_call.call(cfg,root/'cloud-config.json',{'action':'material_feedback_inbox','payload':{'after':after}});self.assertEqual(result['items'],[]);self.assertEqual(seen[-1][1],{'action':'material_feedback_inbox','payload':{'after':after}});self.assertEqual(seen[-1][0][:3],['/python','-B','/runtime/service.py']);self.assertIn('--body-fd',seen[-1][0])
 def test_read_timeout_and_server_failure_are_not_empty_or_write_unknown(self):
  with tempfile.TemporaryDirectory()as tmp:
   root=Path(tmp).resolve();cfg=self.config(root);body={'action':'material_feedback_inbox','payload':{'after':None}}
   with patch.object(knowledge_review_call,'material_command',return_value=['/python','-B','/runtime/service.py']),patch.object(knowledge_review_call.subprocess,'run',side_effect=knowledge_review_call.subprocess.TimeoutExpired('fixture',25)):
    with self.assertRaisesRegex(ValueError,'knowledge_read_unavailable'):knowledge_review_call.call(cfg,root/'cloud-config.json',body)
   def denied(argv,**kw):kw['stdout'].write(b'{"error":"material_feedback_receipt_mismatch"}');return SimpleNamespace(returncode=2)
   with patch.object(knowledge_review_call,'material_command',return_value=['/python','-B','/runtime/service.py']),patch.object(knowledge_review_call.subprocess,'run',side_effect=denied):
    with self.assertRaisesRegex(ValueError,'knowledge_request_unavailable'):knowledge_review_call.call(cfg,root/'cloud-config.json',body)
if __name__=='__main__':unittest.main()
