import json,os,tempfile,unittest,uuid
from pathlib import Path
import pro_xhs_media as x
class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.run=Path(self.tmp.name).resolve()/str(uuid.uuid4());self.run.mkdir();self.m={'run_id':self.run.name,'request':{'platform':'xhs','media':True,'source_executor':'pro'}}
  self.v={'schema':'crowd-xhs-media-failure-v2','stage':'stream','reason':'xhs_media_transport_failed','http_status':200,'transport_errno':'ECONNRESET','stream_bytes':7}
 def test_v2_durable_roundtrip(self):
  saved=x.record_node_failure(self.run,self.m,json.dumps(self.v).encode());self.assertEqual(x.read_failure(self.run,self.m),saved);self.assertEqual(saved['stream_bytes'],7);self.assertEqual((self.run/'pro-xhs-media-failure.json').stat().st_mode&0o777,0o600)
 def test_exact_types_ranges_shape(self):
  for change in [{'stream_bytes':True},{'stream_bytes':-1},{'stream_bytes':1.5},{'stream_bytes':9007199254740992},{'transport_errno':'secret'},{'transport_errno':[]},{'extra':'raw'},{'http_status':True}]:
   with self.subTest(change=change),self.assertRaises(ValueError):x.record_node_failure(self.run,self.m,json.dumps({**self.v,**change}).encode())
  self.assertFalse((self.run/'pro-xhs-media-failure.json').exists())
 def test_private_permissions_and_missing_scope(self):
  x.record_node_failure(self.run,self.m,json.dumps(self.v).encode());p=self.run/'pro-xhs-media-failure.json';p.chmod(0o644)
  with self.assertRaises(ValueError):x.read_failure(self.run,self.m)
  p.chmod(0o600);value=json.loads(p.read_bytes());del value['request_hash'];p.write_text(json.dumps(value))
  with self.assertRaises(ValueError):x.read_failure(self.run,self.m)
 def test_duplicate_extra_v1_not_upgraded(self):
  raw=json.dumps(self.v)[:-1]+',"stream_bytes":7}'
  with self.assertRaises(ValueError):x.record_node_failure(self.run,self.m,raw.encode())
  old={k:v for k,v in self.v.items() if k not in ('transport_errno','stream_bytes')};old['schema']='crowd-xhs-media-failure-v1';saved=x.record_node_failure(self.run,self.m,json.dumps(old).encode());before=(self.run/'pro-xhs-media-failure.json').read_bytes();self.assertEqual(x.read_failure(self.run,self.m),saved);self.assertEqual(before,(self.run/'pro-xhs-media-failure.json').read_bytes())
if __name__=='__main__':unittest.main()
