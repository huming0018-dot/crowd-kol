"""Offline future media preflight tests; no SDK/platform/Node process.
Run from this directory: python3 -B -m unittest test_pro_media_preflight
All accounts/runs are temporary fixtures; no private input or environment required.
"""
import json,sys,tempfile,types,unittest,uuid
from pathlib import Path
from unittest.mock import patch
import pro_executor as P
from shared_request_budget import request_fingerprint
class ProbeBoundary(Exception):pass
class Preflight(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve();self.run=self.root/'runs'/str(uuid.uuid4());self.run.mkdir(parents=True)
  self.request={'platform':'xhs','media':True,'source_executor':'pro','mode':'detail','max_api_requests':30,'session_id':str(uuid.uuid4())}
  self.manifest={'run_id':self.run.name,'request':self.request,'executor':{'backend':'pro','root':str(self.root/'licensed-source')}}
  self.probe=patch.object(P,'probe',side_effect=ProbeBoundary('SDK_PROBE_NOT_EXECUTED'));self.pp=self.probe.start();self.addCleanup(self.probe.stop)
  import pro_xhs_media
  self.dep=patch.object(pro_xhs_media,'dependency_binding',return_value={});self.dp=self.dep.start();self.addCleanup(self.dep.stop)
  self.node=types.ModuleType('portable_node');self.node.check=lambda _:self.root/'node'
 def execute(self):return P.execute(self.run,self.manifest)
 def witness(self):return json.loads((self.run/'pro-media-preflight.json').read_bytes())
 def check(self,stage,reason):
  v=self.witness();self.assertEqual(v,{'schema':'crowd-pro-media-preflight-v1','run_id':self.run.name,'request_hash':request_fingerprint(self.request),'executor':'pro','platform':'xhs','stage':stage,'state':'failed_before_source','reason':reason,'source_started':False,'api_attempts':0});self.assertIs(type(v['api_attempts']),int);self.assertIs(type(v['source_started']),bool);self.pp.assert_not_called()
 def test_missing_node_module_records_exact_failure_before_source(self):
  with patch.dict(sys.modules,{'portable_node':None}):
   with self.assertRaises(Exception):self.execute()
  self.check('node_import','portable_node_unavailable')
 def test_media_binding_failure_has_no_raw_private_error(self):
  self.dp.side_effect=ValueError('/private/path token=DO_NOT_RECORD')
  with self.assertRaises(Exception):self.execute()
  self.check('media_binding','media_dependency_unavailable');self.assertNotIn('DO_NOT_RECORD',(self.run/'pro-media-preflight.json').read_text())
 def test_node_resource_failure_is_distinct(self):
  self.node.check=lambda _:(_ for _ in ()).throw(ValueError('private node path'))
  with patch.dict(sys.modules,{'portable_node':self.node}):
   with self.assertRaises(Exception):self.execute()
  self.check('node_resource','node_resource_unavailable')
 def test_successful_preflight_never_writes_zero_or_calls_sdk_in_test(self):
  with patch.dict(sys.modules,{'portable_node':self.node}):
   with self.assertRaises(ProbeBoundary):self.execute()
  self.pp.assert_called_once();self.assertFalse((self.run/'pro-media-preflight.json').exists())
 def test_prior_budget_cannot_be_reclassified_as_zero(self):
  (self.run/'request-budget.json').write_text('{"used":4}')
  with patch.dict(sys.modules,{'portable_node':None}):
   with self.assertRaises(Exception):self.execute()
  self.assertFalse((self.run/'pro-media-preflight.json').exists());self.pp.assert_not_called()
 def test_prior_sdk_database_cannot_be_reclassified_as_zero(self):
  (self.run/P.DB_NAME).write_bytes(b'old database')
  with patch.dict(sys.modules,{'portable_node':None}):
   with self.assertRaises(Exception):self.execute()
  self.assertFalse((self.run/'pro-media-preflight.json').exists());self.pp.assert_not_called()
 def test_existing_witness_cannot_be_overwritten_or_start_source(self):
  old=b'{"old":"untrusted"}';(self.run/'pro-media-preflight.json').write_bytes(old)
  with patch.dict(sys.modules,{'portable_node':self.node}):
   with self.assertRaises(Exception):self.execute()
  self.pp.assert_not_called();self.assertEqual((self.run/'pro-media-preflight.json').read_bytes(),old)
 def test_nonmedia_existing_path_unchanged(self):
  self.request['media']=False
  with self.assertRaises(ProbeBoundary):self.execute()
  self.pp.assert_called_once();self.dp.assert_not_called();self.assertFalse((self.run/'pro-media-preflight.json').exists())
 def test_real_media_outputs_and_sqlite_residues_never_attest_zero(self):
  names=('hybrid-media-result.json','hybrid-media-dispatch.json',P.DB_NAME+'-wal',P.DB_NAME+'-shm',
         'mc-source-steps.sqlite3-wal','mc-source-steps.sqlite3-shm')
  for name in names:
   with self.subTest(artifact=name):
    path=self.run/name;path.write_bytes(b'{"state":"completed","assets":[]}')
    try:
     with patch.dict(sys.modules,{'portable_node':None}):
      with self.assertRaises(Exception):self.execute()
     self.assertFalse((self.run/'pro-media-preflight.json').exists());self.pp.assert_not_called()
    finally:
     path.unlink()
     witness=self.run/'pro-media-preflight.json'
     if witness.exists():witness.unlink()  # Temp fixture cleanup isolates each old/new counterexample.
if __name__=='__main__':unittest.main()
