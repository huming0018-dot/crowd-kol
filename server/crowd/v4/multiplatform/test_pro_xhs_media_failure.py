"""Temp run + finite child metadata; no source, SDK, subprocess or cloud."""
import json,os,tempfile,unittest,uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pro_xhs_media as x
import pro_media_parent as parent
import mc_runner as m
from shared_request_budget import request_fingerprint
class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.run=Path(self.tmp.name).resolve()/str(uuid.uuid4());self.run.mkdir()
  self.manifest={'run_id':self.run.name,'request':{'platform':'xhs','source_executor':'pro','media':True}}
  (self.run/'manifest.json').write_text(json.dumps(self.manifest));self.diag={'schema':'crowd-xhs-media-failure-v1','stage':'get','reason':'xhs_media_http_rejected','http_status':403}
 def record(self):return x.record_node_failure(self.run,self.manifest,json.dumps(self.diag).encode())
 def test_finite_record_private_durable_same_run_no_retry(self):
  value=self.record();self.assertEqual(value['reason'],'xhs_media_http_rejected');self.assertEqual(value['run_id'],self.run.name);self.assertEqual(value['request_hash'],request_fingerprint(self.manifest['request']))
  path=self.run/'pro-xhs-media-failure.json';self.assertEqual(path.stat().st_mode&0o777,0o600);before=path.read_bytes();self.assertEqual(x.read_failure(self.run,self.manifest),value)
  with self.assertRaises(FileExistsError):self.record()
  self.assertEqual(path.read_bytes(),before)
 def test_invalid_child_metadata_cannot_persist_raw_error(self):
  for change in ({'reason':'https://token@private'},{'stage':'private URL'},{'http_status':True},{'http_status':99},{'extra':'secret'}):
   with self.subTest(change=change):
    with self.assertRaises(ValueError):x.record_node_failure(self.run,self.manifest,json.dumps({**self.diag,**change}).encode())
    self.assertFalse((self.run/'pro-xhs-media-failure.json').exists())
 def test_same_scope_or_symlink_required(self):
  self.record();bad={**self.manifest,'request':{**self.manifest['request'],'media':False}}
  with self.assertRaises(ValueError):x.read_failure(self.run,bad)
  p=self.run/'pro-xhs-media-failure.json';p.unlink();p.symlink_to(self.run/'manifest.json')
  with self.assertRaises((ValueError,OSError)):x.read_failure(self.run,self.manifest)
 def test_original_parent_propagates_finite_reason_not_retry_or_generic(self):
  self.record();proc=SimpleNamespace(pid=123456789,returncode=87,communicate=lambda **_:None,wait=lambda **_:87)
  with patch.object(parent.subprocess,'Popen',return_value=proc) as launch,patch.object(parent.os,'killpg'):
   with self.assertRaisesRegex(m.BridgeError,'xhs_media_http_rejected'):
    parent.run_media_child(self.run,[],{}, {},python='unused',mc_root='unused',runtime_root='unused',budget_module_root='unused')
   self.assertEqual(launch.call_count,1)
  self.assertTrue((self.run/'hybrid-media-dispatch.json').exists());self.assertFalse((self.run/'hybrid-media-result.json').exists())
if __name__=='__main__':unittest.main()
