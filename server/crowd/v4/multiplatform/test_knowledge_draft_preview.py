"""Read-only actual-artifact contract. Missing local evidence must fail, never skip."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import copy,hashlib,json,os,tempfile,unittest
import knowledge_draft_preview as draft
from owner_knowledge_publication_service import OwnerKnowledgePublicationService
from owner_knowledge_binding import BindingError,canonical

class Draft(unittest.TestCase):
 def setUp(self):
  self.path=Path(os.environ['CROWD_KNOWLEDGE_DRAFT_MANIFEST'])
  self.sha=hashlib.sha256(self.path.read_bytes()).hexdigest()
  self.manifest=json.loads(self.path.read_bytes())
  # Packaging gives each reviewed artifact its own private inode; never chmod original evidence.
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);root=Path(tmp.name).resolve()
  for name,ref in [(key,self.manifest[key])for key in draft.ARTIFACTS]+[(key,ref)for key,ref in self.manifest['files'].items()]:
   raw=Path(ref['path']).read_bytes();self.assertEqual(hashlib.sha256(raw).hexdigest(),ref['sha256'])
   target=root/name;target.write_bytes(raw);target.chmod(0o600);ref['path']=str(target)
  self.rewritten(self.manifest)
  self.binding=SimpleNamespace(config={'scope':self.manifest['scope_tuple'],
    'manager_actor':self.manifest['actor_mapping']['manager'],
    'reviewer_actor':self.manifest['actor_mapping']['reviewer']},authenticate=lambda _:None)
 def read(self):return draft.preview(self.path,self.sha,self.binding,object())
 def rewritten(self,manifest):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
  self.path=Path(tmp.name).resolve()/'manifest.json';self.path.write_bytes(canonical(manifest));self.path.chmod(0o600)
  self.sha=hashlib.sha256(self.path.read_bytes()).hexdigest()
 def test_actual_snapshot_not_a_release_and_no_paths(self):
  result=self.read();self.assertFalse(result['live_database_changed']);self.assertFalse(result['decision_available'])
  row=result['items'][0];self.assertEqual(row['proposal_base_ref']['version'],'0.1.1');self.assertEqual(row['draft_target_ref']['version'],'0.1.2')
  self.assertFalse(row['published']);self.assertFalse(row['generation']['execution_verified']);self.assertEqual(row['same_input_impact']['original_ack_records'],4)
  self.assertNotIn('/Users/',json.dumps(result));self.assertNotIn('workspace',result);self.assertNotIn('actor_mapping',result)
 def test_owner_auth_before_any_artifact_read(self):
  self.binding.authenticate=lambda _:(_ for _ in ()).throw(BindingError('owner_denied'))
  with patch.object(draft,'protected_bytes',side_effect=AssertionError('must authenticate first')):
   with self.assertRaisesRegex(BindingError,'owner_denied'):self.read()
 def test_descriptor_sha_change(self):
  self.sha='0'*64
  with self.assertRaisesRegex(BindingError,'snapshot_invalid'):self.read()
 def test_scope_and_source_registration_cannot_become_candidate(self):
  for field,value in [('scope_tuple',['other','project','space']),('registry_candidates',[self.manifest['excluded_source_registration']])]:
   m=copy.deepcopy(self.manifest);m[field]=value;self.rewritten(m)
   with self.assertRaisesRegex(BindingError,'snapshot_invalid'):self.read()
 def test_all_pinned_files_fail_closed_before_return(self):
  m=copy.deepcopy(self.manifest);m['files']['fields.yaml']['sha256']='0'*64;self.rewritten(m)
  with self.assertRaisesRegex(BindingError,'snapshot_invalid'):self.read()
 def test_symlink_artifact_rejected(self):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);path=Path(tmp.name).resolve()/'linked';path.symlink_to(self.manifest['owner_view']['path'])
  m=copy.deepcopy(self.manifest);m['owner_view']['path']=str(path);self.rewritten(m)
  with self.assertRaisesRegex(BindingError,'path_invalid'):self.read()
 def test_rehashed_view_cannot_claim_publication_or_verified_generation(self):
  for field in ('published','reviewed','pin_changed','knowledge_live_submission'):
   m=copy.deepcopy(self.manifest);ref=m['owner_view'];value=json.loads(Path(ref['path']).read_bytes());value[field]=True
   raw=canonical(value);Path(ref['path']).write_bytes(raw);ref.update(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest());self.rewritten(m)
   with self.assertRaisesRegex(BindingError,'snapshot_invalid'):self.read()
   # Restore the private test view; original evidence has never been written.
   value[field]=False;raw=canonical(value);Path(ref['path']).write_bytes(raw)
   self.manifest['owner_view'].update(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
 def test_only_empty_payload_and_no_db_instantiation(self):
  service=object.__new__(OwnerKnowledgePublicationService);service._check=lambda:None;service.review=SimpleNamespace(binding=self.binding);service.client=object()
  service.draft={'draft_manifest':str(self.path),'draft_manifest_sha256':self.sha}
  with patch('toolbox.knowledge.KnowledgeStore',side_effect=AssertionError('no live database')):
   self.assertEqual(len(service.request({'action':'draft_preview','payload':{}})['items']),1)
   with self.assertRaisesRegex(BindingError,'request_invalid'):service.request({'action':'draft_preview','payload':{'path':str(self.path)}})
  service.draft=None;self.assertEqual(service.request({'action':'draft_preview','payload':{}})['items'],[])

if __name__=='__main__':unittest.main()
