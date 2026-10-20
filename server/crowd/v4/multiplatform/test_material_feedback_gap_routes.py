"""G19 existing service/subprocess contract; no actual API/source/model or active-store writes."""
from pathlib import Path
import os,sys,json,tempfile,unittest
from types import SimpleNamespace
from unittest.mock import patch
HERE=Path(__file__).resolve().parent
MP=Path(os.environ['CROWD_MP_ROOT']);TARGET=Path(os.environ['CROWD_FEEDBACK_CANDIDATE'])
# Reuse the exact SDK fixture/assertions, targeting the assembled four-module combination.
oldargv=sys.argv[:];sys.argv=[sys.argv[0],str(TARGET)]
import test_material_feedback_gap as sdk
sys.argv=oldargv;sys.path.insert(0,str(TARGET))
from owner_knowledge_publication_service import OwnerKnowledgePublicationService
from owner_knowledge_binding import BindingError
import knowledge_review_call as boundary
ACTIONS=('material_feedback_gap_preview','material_feedback_gap_submit','material_feedback_gap_status','material_feedback_gap_list')
PREWRITE={'material_feedback_request_invalid','material_feedback_receipt_mismatch','material_feedback_gap_feedback_unsettled','material_feedback_gap_feedback_invalid','material_feedback_gap_feedback_changed','material_feedback_gap_receipt_mismatch','material_feedback_request_conflict','material_feedback_journal_limit','material_feedback_gap_feedback_not_found'}
class Routes(unittest.TestCase):
 def service(self):
  s=object.__new__(OwnerKnowledgePublicationService);s._check=lambda:None;s.material_root='/fixture-owned-root';s.review=SimpleNamespace(binding=object());s.client=object();return s
 def config(self,root):
  p=root/'runtime.json';p.write_text(json.dumps({'python':'/python','script':'/runtime/service.py','script_sha256':'a'*64,'request':'/runtime/service-config.json','request_sha256':'b'*64}));p.chmod(0o600);return p
 def call(self,action,run,payload=None):
  with tempfile.TemporaryDirectory()as tmp:
   root=Path(tmp).resolve();cfg=self.config(root)
   with patch.object(boundary,'material_command',return_value=['/python','-B','/runtime/service.py']),patch.object(boundary.subprocess,'run',side_effect=run):return boundary.call(cfg,root/'cloud-config.json',{'action':action,'payload':payload or {}})
 def response(self,value,rc=0):
  def run(argv,**kw):kw['stdout'].write(json.dumps(value).encode());return SimpleNamespace(returncode=rc)
  return run
 def test_all_four_service_exact_dispatch_without_new_intent_uuid(self):
  s=self.service()
  for action in ACTIONS:
   payload={'after':None}if action.endswith('_list')else {'feedback_intent':'00000000-0000-4000-8000-000000000001'}
   with patch('material_feedback.MaterialFeedback')as cls:
    cls.return_value.request.return_value={'state':'fixture'};self.assertEqual(s.request({'action':action,'payload':payload}),{'state':'fixture'});cls.assert_called_once_with(s.material_root,s.review.binding,s.client);cls.return_value.request.assert_called_once_with(action,payload)
 def test_missing_config_and_malformed_body_fail_before_construct(self):
  s=self.service();s.material_root=None
  with patch('material_feedback.MaterialFeedback',side_effect=AssertionError('not constructed')):
   for action in ACTIONS:
    with self.assertRaisesRegex(BindingError,'not_configured'):s.request({'action':action,'payload':{}})
   for body in ({'action':ACTIONS[0],'payload':[]},{'action':ACTIONS[0],'payload':{},'actor':'owner'}):
    with self.assertRaisesRegex(BindingError,'request_invalid'):s.request(body)
 def test_exact_frames_all_actions_no_correlation_or_source_side_channel(self):
  for action in ACTIONS:
   payload={'after':None};seen=[]
   def run(argv,**kw):
    seen.append((argv,json.loads(kw['input']),kw));kw['stdout'].write(b'{"state":"fixture"}');return SimpleNamespace(returncode=0)
   self.assertEqual(self.call(action,run,payload),{'state':'fixture'});argv,body,kw=seen[0];self.assertEqual(body,{'action':action,'payload':payload});self.assertEqual(argv[:3],['/python','-B','/runtime/service.py']);self.assertIn('--body-fd',argv);self.assertEqual(kw['timeout'],25);self.assertTrue(kw['close_fds']);self.assertEqual(kw['env']['PYTHONDONTWRITEBYTECODE'],'1')
 def test_submit_timeout_is_unknown_never_not_submitted_or_retry(self):
  calls=[]
  def timeout(*a,**kw):calls.append(1);raise boundary.subprocess.TimeoutExpired('fixture',25)
  with self.assertRaisesRegex(ValueError,'^knowledge_outcome_unknown$'):self.call(ACTIONS[1],timeout)
  self.assertEqual(len(calls),1)
 def test_three_read_timeouts_are_read_unavailable_not_unknown(self):
  for action in (ACTIONS[0],ACTIONS[2],ACTIONS[3]):
   with self.assertRaisesRegex(ValueError,'^knowledge_read_unavailable$'):self.call(action,lambda *a,**k:(_ for _ in ()).throw(boundary.subprocess.TimeoutExpired('fixture',25)))
 def test_exact_prewrite_error_only_rc2_single_known_string(self):
  for code in PREWRITE:self.assertEqual(self.call(ACTIONS[1],self.response({'error':code},2)),{'state':'not_submitted','error_code':code})
  for rc,value in ((1,{'error':'material_feedback_request_invalid'}),(2,{'error':'material_feedback_request_invalid','extra':True}),(2,{'error':'unlisted_raw_error'}),(0,{'error':'material_feedback_request_invalid'})):
   with self.subTest(rc=rc,value=value),self.assertRaises(ValueError):self.call(ACTIONS[1],self.response(value,rc))
 def test_malformed_error_value_refused_never_hash_error_or_not_submitted(self):
  for value in ({'error':{}},{'error':[]},{'error':None},{'error':True},{'error':42},[],None):
   for rc in (0,2):
    with self.subTest(value=value,rc=rc),self.assertRaises(ValueError):self.call(ACTIONS[1],self.response(value,rc))
 def test_read_server_error_never_empty_or_not_submitted(self):
  for action in (ACTIONS[0],ACTIONS[2],ACTIONS[3]):
   with self.assertRaisesRegex(ValueError,'^knowledge_request_unavailable$'):self.call(action,self.response({'error':'material_feedback_gap_feedback_invalid'},2))
class CombinedSDK(sdk.Gap):
 def test_real_temp_sdk_through_host_service_and_wrapper(self):
  s=object.__new__(OwnerKnowledgePublicationService);s._check=lambda:None;s.material_root=self.root;s.review=SimpleNamespace(binding=self.binding);s.client=None
  route=Routes()
  def run(argv,**kw):
   body=json.loads(kw['input'])
   try:out=s.request(body);rc=0
   except BindingError as e:out={'error':str(e)};rc=2
   kw['stdout'].write(json.dumps(out).encode());return SimpleNamespace(returncode=rc)
  view=route.call(ACTIONS[0],run,{'feedback_intent':self.fid});self.assertEqual(view['state'],'gap_preview')
  p=self.args();r=route.call(ACTIONS[1],run,p);self.assertEqual(r['state'],'pending_gap');self.assertEqual(route.call(ACTIONS[2],run,{'feedback_intent':self.fid}),r)
  listed=route.call(ACTIONS[3],run,{'after':None});self.assertEqual(len(listed['items']),1);self.assertEqual(listed['items'][0]['lineage']['feedback_id'],'fb:'+self.fid)
  wrong=route.call(ACTIONS[1],run,{**p,'description':'changed'});self.assertEqual(wrong,{'state':'not_submitted','error_code':'material_feedback_request_conflict'})
if __name__=='__main__':unittest.main()
