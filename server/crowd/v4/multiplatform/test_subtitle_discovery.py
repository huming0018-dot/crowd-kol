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
 def test_immutable_observation(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t).resolve()/'123'/'output';p.mkdir(parents=True);observe(p,'weibo',{'type':'video'},'123')
   f=p/'weibo/subtitle-discovery/123.json';first=f.read_bytes();observe(p,'weibo',{},'123');self.assertEqual(first,f.read_bytes())

if __name__=='__main__':unittest.main()
