import importlib.util,tempfile,unittest,json,uuid
from pathlib import Path
from unittest.mock import patch
import pro_xhs_media as m
import saved_media_attachments as a
class SourceURL(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.run=Path(self.tmp.name).resolve()/str(uuid.uuid4());self.run.mkdir();self.manifest={'run_id':self.run.name,'request':{'platform':'xhs','source_executor':'pro','mode':'detail','media':True}}
  self.url='http://ci.xhscdn.com/test.png?q=synthetic';self.ref={'media_id':'a'*64,'content_id':'b'*24,'kind':'image','platform':'xiaohongshu','url':self.url};self.rows=[{'kind':'content'}];self.obs=[('topic','b'*24,{'type':'normal','image_list':self.url})]
 def planned(self):
  with patch('pro_executor.import_records',return_value=(self.rows,[self.ref],{})),patch('pro_executor.observations',return_value=self.obs):return m.plan(self.run,self.manifest)
 def test_fresh_native_plan_preserves_source_scheme(self):
  self.assertEqual(self.planned()[0]['url'],self.url)
 def test_old_unmarked_intent_keeps_https_transport(self):
  (self.run/'xhs-pro-media-intent.json').write_text('{}');self.assertEqual(self.planned()[0]['url'],self.url.replace('http:','https:'))
 def test_new_intent_policy_only_and_wrong_url_scope(self):
  (self.run/'xhs-pro-media-intent.json').write_text(json.dumps({'transport_policy':'native_source_url_v1'}));self.assertEqual(self.planned()[0]['url'],self.url)
  (self.run/'xhs-pro-media-intent.json').write_text(json.dumps({'transport_policy':'other'}))
  with self.assertRaises(ValueError):self.planned()
 def test_old_generic_reference_transport_unchanged(self):
  self.assertEqual(a.reference_transport(self.ref),self.url.replace('http:','https:'))
 def test_native_attachment_policy_requires_completed_proof(self):
  (self.run/'xhs-pro-media-intent.json').write_text(json.dumps({'transport_policy':'native_source_url_v1'}))
  with self.assertRaises((ValueError,OSError)):a.native_attachment_transport(self.run,self.ref)
if __name__=='__main__':unittest.main()
