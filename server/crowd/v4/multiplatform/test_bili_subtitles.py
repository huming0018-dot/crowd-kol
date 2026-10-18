import asyncio,hashlib,json,math,tempfile,unittest
from pathlib import Path
from bili_subtitles import parse_caption,subtitle_url,fetch_subtitles
class Response:
 status_code=200
 def __init__(self,body):self.raw=json.dumps(body).encode()
 async def __aenter__(self):return self
 async def __aexit__(self,*args):pass
 async def aiter_bytes(self,size):yield self.raw
class Client:
 def __init__(self,player,body):self.responses=[player,body];self.calls=[]
 def stream(self,*args,**kwargs):self.calls.append((args,kwargs));return Response(self.responses.pop(0))
class Tests(unittest.TestCase):
 def setUp(self):
  self.identity={'aid':123,'cid':456,'bvid':'BV1ocaW6rETo','duration':55}
  self.track={'id':7,'lan':'zh-CN','type':0,'subtitle_url':'https://i0.hdslb.com/bfs/subtitle/test.json'}
  self.body={'body':[{'from':1,'to':54,'content':'真正的字幕'}]}
 def parse(self,body=None):return parse_caption(self.track,body or self.body,self.identity,'a'*64,'b'*64)
 def test_complete_track_is_candidate_not_semantic_proof(self):
  result=self.parse();self.assertEqual(result['status'],'available');self.assertEqual(result['subtitle_provenance']['semantic_completeness'],'unknown')
 def test_partial_timeline_falls_back(self):
  self.assertEqual(self.parse({'body':[{'from':1,'to':5,'content':'截断'}]})['status'],'partial')
 def test_empty_nan_order_and_negative_rejected(self):
  for body in ({'body':[]},{'body':[{'from':math.nan,'to':2,'content':'x'}]},{'body':[{'from':-1,'to':2,'content':'x'}]}, {'body':[{'from':2,'to':3,'content':'x'},{'from':1,'to':2,'content':'y'}]}):
   with self.assertRaises(ValueError):self.parse(body)
 def test_urls_only_platform_cdn(self):
  for value in ['http://i0.hdslb.com/x','https://127.0.0.1/x','https://hdslb.com.evil.test/x','https://u:p@i0.hdslb.com/x','https://i0.hdslb.com/x#x']:
   self.assertIsNone(subtitle_url(value))
  self.assertEqual(subtitle_url('//i0.hdslb.com/x'),'https://i0.hdslb.com/x')
 def test_fetch_uses_session_only_api_and_keeps_raw_no_model(self):
  client=Client({'code':0,'data':{'subtitle':{'subtitles':[self.track]}}},self.body)
  with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
   value=asyncio.run(fetch_subtitles(self.identity,{'Cookie':'fixture'},Path(directory),client))
   self.assertEqual(value['status'],'available');self.assertEqual(len(client.calls),2)
   self.assertNotIn('Cookie',client.calls[1][1]['headers'])
   raw=(Path(directory)/'bili/subtitles/123.source.json').read_bytes()
   result=json.loads((Path(directory)/'bili/subtitles/123.json').read_text())
   self.assertEqual(hashlib.sha256(raw).hexdigest(),result['subtitle_provenance']['source_body_sha256'])
 def test_login_and_empty_no_second_request(self):
  for data,status in [({'need_login_subtitle':True},'login_required'),({'subtitle':{'subtitles':[]}},'unavailable')]:
   client=Client({'code':0,'data':data},self.body)
   with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
    self.assertEqual(asyncio.run(fetch_subtitles(self.identity,{},directory,client))['status'],status);self.assertEqual(len(client.calls),1)
if __name__=='__main__':unittest.main()

class Integration(unittest.TestCase):
 def test_caption_suppresses_audio_and_load_export_preserves_binding(self):
  import test_media_native,mc_runner,light_transcripts
  from types import SimpleNamespace
  from bili_subtitles import load_job,subtitle_report
  fixture=test_media_native.Tests();fixture.setUp();fixture.seed('bili')
  try:
   run=fixture.run;folder=fixture.folder
   fixture.item['kind']='audio';fixture.save()
   mc_runner.write(folder/'manifest.json',{'run_id':run,'request':{'platform':'bili','media':True,'platform_options':{'long_audio':True,'transcript_only':True}}})
   track={'id':7,'lan':'ai-zh','type':1,'subtitle_url':'https://i0.hdslb.com/bfs/subtitle/test.json'}
   view={'aid':123,'cid':456,'bvid':'BV1ocaW6rETo','duration':55}
   body={'body':[{'from':1,'to':54,'content':'测试字幕'}]}
   client=Client({'code':0,'data':{'subtitle':{'subtitles':[track]}}},body)
   self.assertEqual(asyncio.run(fetch_subtitles(view,{},folder/'output',client))['status'],'available')
   mc_runner.write(folder/'output/bili/media-identities.json',{'bindings':[{'aid':'123','cid':'456','bvid':view['bvid']}]})
   jobs=SimpleNamespace(root=fixture.root/'media-processing',subtitle_run_folder=lambda identity:folder)
   queue=light_transcripts.LightTranscripts(fixture.root,jobs,lambda identity:folder)
   state=queue.enqueue(run);self.assertEqual(state['assets'],[]);self.assertEqual(state['state'],'completed')
   queue.tick();job_id=state['subtitle_jobs'][0]['job_id'];job=load_job(jobs,job_id)
   self.assertEqual(job['kind'],'subtitle');self.assertEqual(job['result'][0]['evidence']['segments'][0]['text'],'测试字幕')
   _,report,raw=subtitle_report(jobs,job_id);self.assertEqual(report['schema'],'crowd-subtitle-report-v1');self.assertNotIn('audio_source_job_id',report)
   self.assertEqual(report['subtitle_source_run_id'],run)
   original=(folder/'normalized.json').read_bytes()
   changed=json.loads(original);changed['records'][0]['body']='tampered but hash unchanged'
   mc_runner.write(folder/'normalized.json',changed)
   with self.assertRaisesRegex(ValueError,'source_changed'):load_job(jobs,job_id)
   changed=json.loads(original);changed['records'][0]['origin']['run_id']='00000000-0000-0000-0000-000000000000'
   mc_runner.write(folder/'normalized.json',changed)
   with self.assertRaisesRegex(ValueError,'source_changed'):load_job(jobs,job_id)
   (folder/'normalized.json').write_bytes(original)
   source_path=folder/fixture.normalized['files'][0]['path'];source_original=source_path.read_bytes();source_path.write_bytes(b'changed source')
   with self.assertRaisesRegex(ValueError,'source_changed'):load_job(jobs,job_id)
   source_path.write_bytes(source_original)
   path=folder/'output/bili/subtitles/123.source.json';path.write_bytes(b'{}')
   with self.assertRaisesRegex(ValueError,'source_changed'):load_job(jobs,job_id)
  finally:fixture.tearDown()
