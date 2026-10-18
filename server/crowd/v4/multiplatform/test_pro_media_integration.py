import copy,json,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import patch
import pro_media_integration as p
from shared_request_budget import request_fingerprint
class Tests(unittest.TestCase):
 def test_observer_scope_and_headers(self):
  import httpx
  stage=p.MediaStage({'source_executor':'pro','media':True})
  view={'aid':123,'cid':456,'bvid':'BV1popx6zEe1','duration':60}
  def response(host='api.bilibili.com',code=0,status=200):return httpx.Response(status,json={'code':code,'data':{'View':view}},request=httpx.Request('GET','https://'+host+'/x/web-interface/view/detail',headers={'Cookie':'SYNTHETIC','User-Agent':'FIXTURE'}))
  stage.observe(response());self.assertEqual(stage.headers[view['bvid']]['Cookie'],'SYNTHETIC')
  stage.headers.clear()
  for r in (response(code=1),response(status=403),response(host='attacker.invalid')):stage.observe(r)
  self.assertEqual(stage.headers,{})
  stage=p.MediaStage({'media':True});stage.observe(response());self.assertFalse(stage.headers)
 def fixture(self,d):
  rid=str(uuid.uuid4());run=Path(d);m={'run_id':rid,'request':{'source_executor':'pro','media':True,'max_api_requests':12}};asset={'path':'output/bili/media/BV1popx6zEe1/audio.m4a','bytes':12,'sha256':'a'*64,'platform':'bilibili','content_id':'123','source_media_id':'BV1popx6zEe1','bilibili_view_cid':'456','bilibili_media_identity_sha256':'b'*64,'kind':'audio','source_kind':'mediacrawler_api','reward_eligible':False,'content_engine':'mediacrawler_pro','media_engine':'native_mc_media_only'}
  result={'schema_version':1,'api_attempts':3,'run_id':rid,'request_hash':request_fingerprint(m['request']),'state':'completed','cloud_ack':False,'content_engine':'mediacrawler_pro','media_engine':'native_mc_media_only','assets':[asset]};(run/'hybrid-media-result.json').write_text(json.dumps(result));return run,m,asset,result
 def test_annotations_and_source_immutable(self):
  with tempfile.TemporaryDirectory(dir='/private/tmp') as d:
   run,m,a,r=self.fixture(d);items=[dict(a)];p.annotate_import(run,m,items);self.assertEqual(items[0]['status'],'downloaded_by_hybrid_media_executor');self.assertEqual(a['kind'],'audio')
 def test_bindings_typed_reject(self):
  with tempfile.TemporaryDirectory(dir='/private/tmp') as d:
   run,m,a,r=self.fixture(d)
   for field,value in [('bytes',True),('sha256','c'*64),('content_id','999'),('bilibili_view_cid','999'),('kind','video'),('cloud_ack',True)]:
    bad=copy.deepcopy(r)
    if field=='cloud_ack':bad[field]=value
    else:bad['assets'][0][field]=value
    (run/'hybrid-media-result.json').write_text(json.dumps(bad))
    with self.subTest(field=field),self.assertRaises(ValueError):p.annotate_import(run,m,[dict(a)])
 def test_missing_result_preserves_source_and_orphan_reject(self):
  with tempfile.TemporaryDirectory(dir='/private/tmp') as d:
   run,m,a,r=self.fixture(d);(run/'hybrid-media-result.json').unlink();items=[];p.annotate_import(run,m,items);self.assertEqual(items,[])
   (run/'hybrid-media-result.json').write_text(json.dumps(r))
   with self.assertRaises(ValueError):p.annotate_import(run,m,[])
   with self.assertRaises(ValueError):p.annotate_import(run,m,[dict(a),{'path':'extra'}])
 def test_no_media_no_action(self):
  s=p.MediaStage({'source_executor':'mc','media':True});self.assertIsNone(s.run(None,{},[],mc_root=None,remaining=0))
if __name__=='__main__':unittest.main()
