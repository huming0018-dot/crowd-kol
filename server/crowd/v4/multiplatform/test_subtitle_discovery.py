import asyncio
import hashlib
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
from subtitle_discovery import discover,parse_saved_track,observe,install_hooks

class Tests(unittest.TestCase):
 def test_platform_transcript_option_is_explicit_boolean_and_requires_media(self):
  from mc_runner import validate_options,BridgeError
  for platform in ('ks','wb','xhs','zhihu','tieba'):
   validate_options({'platform':platform,'media':True,'platform_options':{'transcript_only':True}})
   for request in ({'platform':platform,'media':True,'platform_options':{'transcript_only':1}},
                   {'platform':platform,'media':False,'platform_options':{'transcript_only':True}},
                   {'platform':platform,'media':True,'platform_options':{'unrequested_option':True}}):
    with self.assertRaises(BridgeError):validate_options(request)
 def test_native_metadata_duration_units_and_conflicts(self):
  from subtitle_discovery import native_duration
  output=Path('/missing/output')
  for platform,detail,ctype,expected in [
      ('kuaishou',{'photo':{'id':'123','duration':15200}},None,15.2),
      ('xiaohongshu',{'video':{'media':{'stream':{'h264':[{'duration':28073},{'duration':28073}]}}}},None,28.073),
      ('zhihu',{'id':'123','video':{'duration':146.333}},'zvideo',146.333),
      ('zhihu',{'initialState':{'entities':{'zvideos':{'123':{'id':'123','video':{'duration':146.333}},'456':{'video':{'duration':10}}}}}},'zvideo',146.333),
      ('weibo',{'page_info':{'media_info':{'duration':60.443}}},None,60.443)]:
   self.assertEqual(native_duration(output,platform,detail,'123',ctype),expected)
  for value in (True,'1000',0,-1,float('nan'),float('inf'),7200001):
   self.assertIsNone(native_duration(output,'kuaishou',{'photo':{'duration':value}},'123'))
  self.assertIsNone(native_duration(output,'xiaohongshu',{'video':{'media':{'stream':{'h264':[{'duration':10000},{'duration':11000}]}}}},'123'))
  with patch('subtitle_discovery.subprocess.run') as probe:
   self.assertIsNone(native_duration(output,'tieba',{'duration':1000},'123'))
   probe.assert_not_called()
 def test_seven_explicit_no_track(self):
  for platform in ('kuaishou','weibo','xiaohongshu','zhihu','tieba','douyin','bilibili'):
   result,private=discover(platform,{'type':'video'},'123')
   self.assertEqual(result['status'],'unavailable');self.assertEqual(private,[]);self.assertEqual(result['source_requests'],0)
 def test_no_video(self):
  self.assertEqual(discover('xiaohongshu',{'type':'normal','image_list':[]},'123')[0]['status'],'not_video')
 def test_caption_title_not_subtitle(self):
  r,_=discover('kuaishou',{'photo':{'id':'123','photoUrl':'present','caption':'a title'}},'123')
  self.assertEqual(r['status'],'unavailable');self.assertIn('.photo.caption',r['unparsed_field_paths'])
 def test_html_declared_not_chapter(self):
  raw='<video><track kind="chapters" srclang="zh" src="https://video.zhihu.com/a.vtt"><track kind="captions" srclang="zh" src="https://video.zhihu.com/b.vtt"></video>'
  r,private=discover('zhihu',{'content':raw},'123','zvideo')
  self.assertEqual(len(private),1);self.assertEqual(r['status'],'track_candidate');self.assertNotIn('https:',json.dumps(r));self.assertTrue(private[0]['url'].endswith('b.vtt'))
 def test_safe_track_hosts(self):
  for bad in ('http://video.zhihu.com/a.vtt','https://video.zhihu.com.evil/a.vtt','https://evil/a.vtt','https://user:pass@video.zhihu.com/a.vtt','file:///tmp/a'):
   self.assertEqual(discover('zhihu',{'subtitles':{'zh':[{'url':bad,'ext':'vtt'}]}},'123')[1],[])
 def test_other_entity_track_rejected(self):
  r,_=discover('weibo',{'user':{'subtitles':{'zh':[{'url':'https://weibo.com/a.vtt','ext':'vtt'}]},'content':'<video><track kind="captions" srclang="zh" src="https://weibo.com/a.vtt"></video>'}},'123')
  self.assertEqual(r['track_candidates'],[]) # Body-scoped HTML enforced below.
 def test_zhihu_select_entity(self):
  d={'initialState':{'entities':{'zvideos':{'123':{'id':'123','type':'zvideo'},'456':{'id':'456','subtitles':{'zh':[{'url':'https://video.zhihu.com/a.vtt','ext':'vtt'}]}}}}}}
  r,_=discover('zhihu',d,'123','zvideo');self.assertEqual(r['track_candidates'],[])
 def test_inline_known_parser_binding(self):
  r,_=discover('weibo',{'subtitles':{'zh':[{'url':'https://weibo.com/a.vtt','ext':'vtt'}]}},'123')
  raw=b'WEBVTT\n\n00:00.000 --> 00:10.000\nhello\n';track=r['track_candidates'][0]
  with patch('native_subtitles.parse_text',return_value=[{'start':0.,'end':10.,'text':'hello'}]):
   result=parse_saved_track(raw,track,10,r)
  self.assertEqual(result['raw_subtitle_sha256'],hashlib.sha256(raw).hexdigest());self.assertEqual(result['status'],'available');self.assertEqual(result['semantic_completeness'],'unknown')
  with self.assertRaises(ValueError):parse_saved_track(raw,{**track,'track_url_sha256':'a'*64},10,r)
 def test_native_identity_mismatch(self):
  for platform,raw in [('kuaishou',{'photo':{'id':'456'}}),('weibo',{'id':'456'}),('xiaohongshu',{'note_id':'456'})]:
   with self.assertRaises(ValueError):discover(platform,raw,'123')
 def test_real_toolkit_formats_and_parser(self):
  runtime=Path(__file__).resolve().parents[5]/'outputs/subtitle-native-207/yt-dlp-runtime'
  with patch.dict(os.environ,{'CROWD_YTDLP_RUNTIME':str(runtime)}):
   r,_=discover('weibo',{'id':'123','page_info':{'media_info':{'playback_list':[{'play_info':{'url':'https://weibo.com/test.mp4','video_codecs':'h264','audio_codecs':'aac'}}]}}},'123')
   self.assertEqual(r['status'],'unavailable');self.assertTrue(any(x['value']=='aac' for x in r['reported_codec_fields']))
   r,_=discover('weibo',{'subtitles':{'zh':[{'url':'https://weibo.com/a.vtt','ext':'vtt'}]}},'123');t=r['track_candidates'][0]
   raw=b'WEBVTT\n\n00:00.000 --> 00:10.000\nhello\n';result=parse_saved_track(raw,t,10,r)
   self.assertEqual(result['segments'],[{'start':0.0,'end':10.0,'text':'hello'}])
   partial=parse_saved_track(b'WEBVTT\n\n00:00.000 --> 00:01.000\nhello\n',t,100,r);self.assertEqual(partial['status'],'partial')
   with self.assertRaises(ValueError):parse_saved_track(b'WEBVTT\n\n00:11.000 --> 00:12.000\nhello\n',t,10,r)
 def test_limits(self):
  with self.assertRaises(ValueError):discover('weibo',{'x':'x'*2_000_001},'123')
  d={};v=d
  for i in range(14):v['next']={};v=v['next']
  with self.assertRaises(ValueError):discover('weibo',d,'123')
 def test_original_media_call_preserved(self):
  events=[]
  class C:
   async def download_media(self,video_item):events.append(video_item);return 'kept'
  with tempfile.TemporaryDirectory() as t:
   output=Path(t).resolve()/'123'/'output';output.mkdir(parents=True)
   install_hooks({'ks':C},'ks',output)
   self.assertEqual(asyncio.run(C().download_media({'photo':{'id':'123','caption':'title'}})),'kept')
   self.assertEqual(len(events),1);saved=list(output.glob('kuaishou/subtitle-discovery/*.json'));self.assertEqual(len(saved),1)
   self.assertEqual(json.loads(saved[0].read_text())['source_requests'],0)
 def test_observer_io_failure_keeps_media(self):
  events=[]
  class C:
   async def download_media(self,video_item):events.append(video_item);return 'kept'
  install_hooks({'ks':C},'ks',Path('/missing/output'))
  with patch('subtitle_discovery.observe',side_effect=OSError('io')),patch('subtitle_discovery.observation_error'):
   self.assertEqual(asyncio.run(C().download_media({'photo':{'id':'123'}})),'kept')
  self.assertEqual(len(events),1)
 def test_assets_observer_io_failure_keeps_original(self):
  for platform in ('zhihu','tieba'):
   import importlib
   module=importlib.import_module(platform+'_media');events=[]
   async def original(*args,**kwargs):events.append(args);return 'assets_kept'
   with patch.object(module,'download_assets',original):
    install_hooks({},platform,Path('/missing/output'))
    with patch('subtitle_discovery.observe',side_effect=OSError('io')),patch('subtitle_discovery.observation_error'):
     args=({},'123','zvideo',Path('/missing/output')) if platform=='zhihu' else ({},'123',Path('/missing/output'))
     self.assertEqual(asyncio.run(module.download_assets(*args)),'assets_kept')
   self.assertEqual(len(events),1)
 def test_declared_fetch_keeps_original_and_order(self):
  events=[]
  class C:
   async def download_media(self,mblog):events.append('media');return 'kept'
  install_hooks({'wb':C},'wb',Path('/missing/output'))
  async def fetcher(*args,**kwargs):events.append('caption')
  with patch('subtitle_discovery.observe'),patch('subtitle_discovery.fetch_same_response',side_effect=fetcher):
   self.assertEqual(asyncio.run(C().download_media({'id':'123'})),'kept')
  self.assertEqual(events,['media','caption'])
 def test_transcript_preflight_available_skips_media_only_when_requested(self):
  for platform,name in [('ks','video_item'),('wb','mblog'),('xhs','note_detail')]:
   events=[]
   class C:
    async def download_media(self,*args,**kwargs):events.append('video');return 'video_result'
   async def fetcher(*args,**kwargs):events.append('caption');return {'status':'available'}
   install_hooks({platform:C},platform,Path('/missing/output'),transcript_only=True)
   detail={'photo':{'id':'123'}} if platform=='ks' else {'note_id':'123'} if platform=='xhs' else {'id':'123'}
   with patch('subtitle_discovery.observe'),patch('subtitle_discovery.fetch_same_response',side_effect=fetcher):
    self.assertIsNone(asyncio.run(C().download_media(**{name:detail})))
   self.assertEqual(events,['caption'])
 def test_transcript_preflight_partial_falls_back_without_skipping_video(self):
  events=[]
  class C:
   async def download_media(self,mblog):events.append('video');return 'kept'
  async def fetcher(*args,**kwargs):events.append('caption');return {'status':'partial'}
  install_hooks({'wb':C},'wb',Path('/missing/output'),transcript_only=True)
  with patch('subtitle_discovery.observe'),patch('subtitle_discovery.fetch_same_response',side_effect=fetcher):
   self.assertEqual(asyncio.run(C().download_media({'id':'123'})),'kept')
  self.assertEqual(events,['caption','video','caption'])
 def test_transcript_preflight_budget_stop_propagates(self):
  class C:
   async def download_media(self,mblog):raise AssertionError('must not download after source stop')
  install_hooks({'wb':C},'wb',Path('/missing/output'),transcript_only=True)
  with patch('subtitle_discovery.observe'),patch('subtitle_discovery.fetch_same_response',side_effect=SystemExit('budget')):
   with self.assertRaises(SystemExit):asyncio.run(C().download_media({'id':'123'}))
 def test_transcript_assets_preflight_available_skips_download(self):
  import importlib
  for platform in ('zhihu','tieba'):
   module=importlib.import_module(platform+'_media');events=[]
   async def original(*args,**kwargs):events.append('media')
   async def fetcher(*args,**kwargs):events.append('caption');return {'status':'available'}
   with patch.object(module,'download_assets',original):
    install_hooks({},platform,Path('/missing/output'),transcript_only=True)
    with patch('subtitle_discovery.observe'),patch('subtitle_discovery.fetch_same_response',side_effect=fetcher):
     args=({},'123','zvideo',Path('/missing/output')) if platform=='zhihu' else ({},'123',Path('/missing/output'))
     asyncio.run(module.download_assets(*args))
   self.assertEqual(events,['caption'])
 def test_declared_fetch_io_failure_keeps_original(self):
  events=[]
  class C:
   async def download_media(self,mblog):events.append('media');return 'kept'
  install_hooks({'wb':C},'wb',Path('/missing/output'))
  with patch('subtitle_discovery.observe'),patch('subtitle_discovery.fetch_same_response',side_effect=OSError('io')),patch('subtitle_discovery.observation_error'):
   self.assertEqual(asyncio.run(C().download_media({'id':'123'})),'kept')
  self.assertEqual(events,['media'])
 def test_real_saved_caption_preflight_replays_and_rejects_corruption(self):
  from subtitle_discovery import fetch_same_response
  from test_declared_subtitles import Client
  from declared_subtitles import fetch,_paths
  from mc_runner import write
  import uuid
  runtime=Path(__file__).resolve().parents[5]/'outputs/subtitle-native-207/yt-dlp-runtime'
  with tempfile.TemporaryDirectory() as t,patch.dict(os.environ,{'CROWD_YTDLP_RUNTIME':str(runtime)}):
   run=Path(t).resolve()/str(uuid.uuid4());output=run/'output';output.mkdir(parents=True)
   write(run/'manifest.json',{'run_id':run.name,'request':{'platform':'wb','media':True,'max_api_requests':2}})
   write(run/'phase.json',{'api_attempts':1})
   write(run/'status.json',{'run_id':run.name,'state':'running'})
   detail={'id':'123','subtitles':{'zh':[{'url':'https://weibo.com/fixture.vtt','ext':'vtt'}]},'page_info':{'media_info':{'duration':10}}}
   client=Client()
   asyncio.run(fetch('weibo',detail,output,'123',10,client=client))
   self.assertEqual(asyncio.run(fetch_same_response(output,'weibo',detail,'123'))['status'],'available')
   self.assertEqual(client.calls,1)
   _paths(output,'weibo','123')['raw'].write_bytes(b'corrupted')
   with self.assertRaises(ValueError):asyncio.run(fetch_same_response(output,'weibo',detail,'123'))
   self.assertEqual(client.calls,1)
 def test_no_track_extra_fetch_zero(self):
  from subtitle_discovery import fetch_same_response
  with patch('declared_subtitles.fetch') as request:
   asyncio.run(fetch_same_response(Path('/missing/output'),'kuaishou',{'photo':{'id':'123','caption':'title'}},'123'))
   request.assert_not_called()
 def test_native_parser_failure_never_skips_original(self):
  for error in (AttributeError('native'),KeyError('native'),IndexError('native'),RuntimeError('native')):
   events=[]
   class C:
    async def download_media(self,mblog):events.append('media');return 'kept'
   install_hooks({'wb':C},'wb',Path('/missing/output'))
   with patch('subtitle_discovery.observe',side_effect=error),patch('subtitle_discovery.fetch_same_response',side_effect=error),patch('subtitle_discovery.observation_error'):
    self.assertEqual(asyncio.run(C().download_media({'id':'123'})),'kept')
   self.assertEqual(events,['media'])
 def test_official_weibo_fallback_missing_labels(self):
  runtime=Path(__file__).resolve().parents[5]/'outputs/subtitle-native-207/yt-dlp-runtime'
  detail={'id':'123','page_info':{'media_info':{'stream_url':'https://weibo.com/test.mp4?label=test&template=540x960','video_details':[]}}}
  with patch.dict(os.environ,{'CROWD_YTDLP_RUNTIME':str(runtime)}):
   result,_=discover('weibo',detail,'123')
  self.assertEqual(result['status'],'unavailable')
 def test_immutable_observation(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t).resolve()/'123'/'output';p.mkdir(parents=True);observe(p,'weibo',{'type':'video'},'123')
   f=p/'weibo/subtitle-discovery/123.json';first=f.read_bytes();observe(p,'weibo',{},'123');self.assertEqual(first,f.read_bytes())

if __name__=='__main__':unittest.main()
