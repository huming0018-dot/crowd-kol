import asyncio,hashlib,json,os,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
import native_subtitles as subtitles
from test_bili_subtitles import Response
class Client:
 def __init__(self,raw):self.raw=raw;self.calls=[]
 def stream(self,*args,**kwargs):
  self.calls.append((args,kwargs))
  response=Response({});response.raw=self.raw;return response
class Tests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
  self.detail={'aweme_id':'123','video':{'duration':55000,'cla_info':{'caption_infos':[{'lang':'zh-CN','url':'https://v.douyincdn.com/caption.vtt','Format':'webvtt'}]}}}
  self.raw=b'WEBVTT\n\n00:00:01.000 --> 00:00:54.000\n'+ '真实字幕'.encode()+b'\n\n'
 def tearDown(self):self.temp.cleanup()
 def test_official_discovery_has_no_network_fallback(self):
  tracks,pending=subtitles.discover(self.detail);self.assertEqual(pending,[]);self.assertEqual(tracks['zh-CN'][0]['ext'],'vtt')
  tracks,pending=subtitles.discover({'aweme_id':'123','video':{'duration':55000}});self.assertEqual(tracks,{});self.assertEqual(pending,[])
 def test_only_one_caption_no_cookie_or_video(self):
  client=Client(self.raw);result=asyncio.run(subtitles.fetch_douyin_subtitles(self.detail,self.root,client))
  self.assertEqual(result['status'],'available');self.assertEqual(len(client.calls),1)
  self.assertNotIn('Cookie',client.calls[0][1]['headers'])
  saved=json.loads((self.root/'douyin/subtitles/123.json').read_text());self.assertEqual(saved['segments'][0]['text'],'真实字幕')
  self.assertEqual(saved['subtitle_provenance']['semantic_completeness'],'unknown');self.assertFalse(list(self.root.rglob('*.mp4')))
 def test_unsafe_domain_and_empty_no_request(self):
  for url in ['https://127.0.0.1/x','https://douyincdn.com.evil.test/x','http://v.douyincdn.com/x','https://user:pass@v.douyincdn.com/x']:
   self.detail['video']['cla_info']['caption_infos'][0]['url']=url;client=Client(self.raw)
   self.assertEqual(asyncio.run(subtitles.fetch_douyin_subtitles(self.detail,self.root,client))['status'],'unavailable');self.assertEqual(client.calls,[])
 def test_official_json_captions_and_partial(self):
  detail={'aweme_id':'123','video':{'duration':55000},'interaction_stickers':[{'auto_video_caption_info':{'auto_captions':[{'language':'zh','url':{'url_list':['https://v.douyincdn.com/caption.json']}}]}}]}
  raw=json.dumps({'utterances':[{'start_time':1000,'end_time':54000,'text':'原生JSON文字'}]}).encode()
  self.assertEqual(asyncio.run(subtitles.fetch_douyin_subtitles(detail,self.root,Client(raw)))['status'],'available')
 def test_partial_and_oversized_never_available(self):
  partial=b'WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nshort\n\n'
  self.assertEqual(asyncio.run(subtitles.fetch_douyin_subtitles(self.detail,self.root,Client(partial)))['status'],'partial')
  with tempfile.TemporaryDirectory() as folder:
   result=asyncio.run(subtitles.fetch_douyin_subtitles(self.detail,Path(folder).resolve(),Client(b'x'*(subtitles.MAX_BYTES+1))))
   self.assertEqual(result['status'],'failed')
 def test_json_normalization_identical_fetch_and_reload_whitespace_rounding(self):
  raw=json.dumps({'utterances':[{'start_time':1234.7,'end_time':54321.4,'text':'  时间与空白  '}]}).encode()
  rows=subtitles.normalize_source(raw,'json','123','zh')
  self.assertEqual(rows,subtitles.normalize_source(raw,'json','123','zh'))
  self.assertEqual(rows[0]['text'],'时间与空白');self.assertGreater(rows[0]['start'],1)
 def test_yt_dlp_clock_is_90000_ticks_per_second(self):
  rows=subtitles.parse_text('WEBVTT\n\n00:00:01.123 --> 00:00:54.456\ntext\n\n','vtt')
  self.assertEqual(rows,[{'start':1.123,'end':54.456,'text':'text'}])
 def test_json_actual_fetch_load_same_rows_and_metadata_hash(self):
  import test_media_native,mc_runner,light_transcripts
  f=test_media_native.Tests();f.setUp()
  try:
   detail={'aweme_id':'123','video':{'duration':55000},'interaction_stickers':[{'auto_video_caption_info':{'auto_captions':[{'language':'zh','url':{'url_list':['https://v.douyincdn.com/caption.json']}}]}}]}
   raw=json.dumps({'utterances':[{'start_time':1234.7,'end_time':54321.4,'text':'  时间与空白  '}]}).encode()
   mc_runner.write(f.folder/'manifest.json',{'run_id':f.run,'request':{'platform':'dy','media':True,'platform_options':{'transcript_only':True}}})
   self.assertEqual(asyncio.run(subtitles.fetch_douyin_subtitles(detail,f.folder/'output',Client(raw)))['status'],'available')
   jobs=SimpleNamespace(root=f.root/'media-processing',subtitle_run_folder=lambda run:f.folder)
   state=light_transcripts.LightTranscripts(f.root,jobs,lambda run:f.folder).enqueue(f.run)
   loaded=subtitles.load_job(jobs,state['subtitle_jobs'][0]['job_id'])
   caption=json.loads((f.folder/'output/douyin/subtitles/123.json').read_text())
   self.assertEqual(loaded['result'][0]['evidence']['segments'],caption['segments']);self.assertEqual(caption['segments'][0]['text'],'时间与空白')
   metadata=(f.folder/'output/douyin/subtitles/123.metadata.json').read_bytes()
   self.assertEqual(hashlib.sha256(metadata).hexdigest(),caption['subtitle_provenance']['source_metadata_sha256'])
   self.assertNotIn(b'https://',metadata)
  finally:f.tearDown()
 def test_source_bound_report_and_tamper_rejection(self):
  import test_media_native,mc_runner,light_transcripts
  f=test_media_native.Tests();f.setUp()
  try:
   mc_runner.write(f.folder/'manifest.json',{'run_id':f.run,'request':{'platform':'dy','media':True,'platform_options':{'transcript_only':True}}})
   result=asyncio.run(subtitles.fetch_douyin_subtitles(self.detail,f.folder/'output',Client(self.raw)));self.assertEqual(result['status'],'available')
   jobs=SimpleNamespace(root=f.root/'media-processing',subtitle_run_folder=lambda run:f.folder)
   queue=light_transcripts.LightTranscripts(f.root,jobs,lambda run:f.folder);queued=queue.enqueue(f.run)
   self.assertEqual(queued['state'],'completed');self.assertEqual(queued['assets'],[]);queue.tick()
   job=queued['subtitle_jobs'][0]['job_id'];_,report,_=subtitles.subtitle_report(jobs,job)
   self.assertEqual(report['schema'],'crowd-platform-subtitle-report-v1');self.assertEqual(report['platform'],'douyin')
   import bili_subtitles,transcript_artifact
   self.assertEqual(bili_subtitles.load_job(jobs,job)['platform'],'douyin')
   self.assertEqual(transcript_artifact.load_transcript(jobs,job)[1],report)
   original=(f.folder/'normalized.json').read_bytes();changed=json.loads(original);changed['records'][0]['body']='tampered'
   mc_runner.write(f.folder/'normalized.json',changed)
   with self.assertRaisesRegex(ValueError,'subtitle_source_changed'):subtitles.load_job(jobs,job)
   (f.folder/'normalized.json').write_bytes(original)
   metadata=f.folder/'output/douyin/subtitles/123.metadata.json';original_metadata=metadata.read_bytes();tampered=json.loads(original_metadata)
   for key,value in [('content_id','999'),('native_duration_ms',54000),('track_url_sha256','a'*64)]:
    changed_metadata={**tampered,key:value};metadata.write_text(json.dumps(changed_metadata))
    with self.assertRaisesRegex(ValueError,'subtitle_source_changed'):subtitles.load_job(jobs,job)
   metadata.write_bytes(original_metadata)
   raw=f.folder/'output/douyin/subtitles/123.source.json';raw.write_bytes(b'changed')
   with self.assertRaisesRegex(ValueError,'subtitle_source_changed'):subtitles.load_job(jobs,job)
  finally:f.tearDown()
class EngineTests(unittest.TestCase):
 def test_new_queue_prefers_configured_mlx_failure_never_cpu_retry(self):
  import test_light_transcripts,mc_runner
  from unittest.mock import patch
  fixture=test_light_transcripts.Tests();fixture.setUp()
  try:
   calls=[]
   def start(*args,**kwargs):calls.append(kwargs);raise ValueError('local_asr_failed')
   with patch.object(fixture.jobs,'capabilities',return_value={'asr':True,'asr_engines':['cpu','mlx']}):
    state=fixture.queue.enqueue(fixture.f.run)
   self.assertEqual(state['assets'][0]['asr_engine'],'mlx')
   with patch.object(fixture.jobs,'start',side_effect=start):fixture.queue.tick();fixture.queue.tick()
   self.assertEqual(len(calls),1);self.assertEqual(calls[0]['asr_engine'],'mlx')
   self.assertEqual(fixture.queue.status(fixture.f.run)['state'],'needs_attention')
   before=fixture.queue._path(fixture.f.run).read_bytes()
   with patch.object(fixture.jobs,'capabilities',return_value={'asr':True,'asr_engines':['cpu']}):fixture.queue.enqueue(fixture.f.run)
   self.assertEqual(fixture.queue._path(fixture.f.run).read_bytes(),before)
  finally:fixture.tearDown()
if __name__=='__main__':unittest.main()
