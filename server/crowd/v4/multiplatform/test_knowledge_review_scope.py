"""Actual preview method in a temporary filesystem; no KnowledgeStore operation."""
from pathlib import Path
from types import SimpleNamespace
import hashlib,json,tempfile,unittest
from owner_knowledge_service import OwnerKnowledgeService
from owner_knowledge_binding import BindingError,canonical
sha=lambda b:hashlib.sha256(b).hexdigest()
class ReviewScope(unittest.TestCase):
 def service(self,directory,unresolved=(),denied=False):
  root=Path(directory).resolve();helper=root/'helper.py';pc=root/'preview.json';sc=root/'service.json'
  data={'proposal_id':'prop:fixture','candidate_hash':'a'*64,'role_state':{},'proposal_status':'proposed','review_scope':['untrusted','helper','claim']}
  helper.write_text('def preview(config):\n return '+repr(data)+'\n');pc.write_bytes(b'{}');sc.write_bytes(b'{}')
  for p in [helper,pc,sc]:p.chmod(0o600)
  s=object.__new__(OwnerKnowledgeService);s.config={'preview_helper':str(helper),'preview_helper_sha256':sha(helper.read_bytes()),'preview_config':str(pc),'preview_config_sha256':sha(pc.read_bytes())};s.config_path=str(sc);s.config_sha256=sha(sc.read_bytes());s.client=object();s.previews={}
  def auth(_):
   if denied:raise BindingError('denied')
   return {'kind':'central_owner_service'}
  s.binding=SimpleNamespace(config={'scope':['fixture','project','private'],'proposal_id':'prop:fixture','candidate_hash':'a'*64,'intents':str(root/'intents')},authenticate=auth,unresolved_decisions=lambda:list(unresolved))
  return s
 def test_only_authenticated_binding_scope_and_original_token_contract(self):
  with tempfile.TemporaryDirectory()as d:
   s=self.service(d);v=s.preview();self.assertEqual(v['review_scope'],s.binding.config['scope']);self.assertNotEqual(v['review_scope'],['untrusted','helper','claim']);self.assertTrue(v['decision_available']);self.assertEqual(len(v['preview_token']),43);self.assertEqual(s._get_preview(v['preview_token'])['fingerprint'],v['preview_fingerprint']);v['review_scope'][0]='mutated';self.assertEqual(s.binding.config['scope'][0],'fixture')
 def test_denied_auth_never_returns_scope_or_persists_preview(self):
  with tempfile.TemporaryDirectory()as d:
   s=self.service(d,denied=True)
   with self.assertRaisesRegex(BindingError,'denied'):s.preview()
   self.assertFalse((Path(d)/'intents').exists())
 def test_unresolved_decision_remains_disabled(self):
  with tempfile.TemporaryDirectory()as d:
   v=self.service(d,unresolved=('fixed-pending',)).preview();self.assertFalse(v['decision_available']);self.assertFalse(any(x['enabled']for x in v['actions'].values()));self.assertEqual(v['unresolved_decisions'],['fixed-pending'])
if __name__=='__main__':unittest.main()
