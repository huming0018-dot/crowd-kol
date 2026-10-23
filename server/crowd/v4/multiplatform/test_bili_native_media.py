"""Execute installed SDK functions with synthetic transport; no browser/source."""
import ast,asyncio,contextlib,functools,hashlib,json,logging,os,shutil,tempfile,textwrap,threading,unittest,uuid
from pathlib import Path
from types import ModuleType,SimpleNamespace
from unittest.mock import AsyncMock,Mock,patch
import mc_runner as m
import native_media_scope as n

SDK=Path('/Users/hubowen/WorkBuddy/2026-10-08-22-53-19/MediaCrawler')

def installed_functions(path,names,namespace):
 tree=ast.parse(path.read_text());nodes=[node for node in tree.body if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in names]
 future=ast.parse('from __future__ import annotations').body
 exec(compile(ast.Module(body=future+nodes,type_ignores=[]),str(path),'exec'),namespace)

class Tests(unittest.TestCase):
 def executable(self,base):
  path=base/'ffmpeg';path.write_text('#!/bin/sh\nexit 0\n');path.chmod(0o700);return path
 def sdk_ffmpeg(self):
  module=ModuleType('media_downloader.ffmpeg');module.__dict__.update(asyncio=asyncio,contextlib=contextlib,functools=functools,shutil=shutil,Path=Path,DEFAULT_MERGE_TIMEOUT=300,MediaDownloadError=ValueError,logger=Mock())
  installed_functions(SDK/'media_downloader/ffmpeg.py',{'ffmpeg_path','is_available','merge_audio_video'},module.__dict__)
  package=ModuleType('media_downloader');package.ffmpeg_path=module.ffmpeg_path;package.is_ffmpeg_available=module.is_available;package.merge_audio_video=module.merge_audio_video;package.ffmpeg=module
  return package,module
 def test_actual_sdk_available_and_merge_use_configured_binary_not_path(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory).resolve();binary=self.executable(root);package,module=self.sdk_ffmpeg();output=root/'merged.mp4';output.write_bytes(b'existing synthetic merge output')
   with patch.object(shutil,'which',return_value=None):
    self.assertFalse(package.is_ffmpeg_available());self.assertTrue(n.install_ffmpeg_path(package,module,str(binary)))
    self.assertTrue(package.is_ffmpeg_available());self.assertEqual(package.ffmpeg_path(),str(binary))
    process=SimpleNamespace(returncode=0,communicate=AsyncMock(return_value=(b'',b'')))
    with patch('asyncio.create_subprocess_exec',new=AsyncMock(return_value=process)) as launch:
     asyncio.run(package.merge_audio_video(root/'video.part',root/'audio.part',output))
    args=launch.call_args.args;self.assertEqual(args[0],str(binary));self.assertEqual(args[args.index('-c')+1],'copy');self.assertNotIn('http',str(args))
 def test_path_validation_and_absent_config_preserve_native_behavior(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory).resolve();binary=self.executable(root);package,module=self.sdk_ffmpeg();original=module.ffmpeg_path
   with patch.dict(os.environ,{'CROWD_FFMPEG':''}):self.assertFalse(n.install_ffmpeg_path(package,module));self.assertIs(module.ffmpeg_path,original)
   for bad in ('relative',str(root/'missing'),str(root)):
    with self.assertRaisesRegex(ValueError,'invalid_native_ffmpeg_path'):n.install_ffmpeg_path(package,module,bad)
   binary.chmod(0o600)
   with self.assertRaises(ValueError):n.install_ffmpeg_path(package,module,str(binary))
   binary.chmod(0o777)
   with self.assertRaises(ValueError):n.install_ffmpeg_path(package,module,str(binary))
   binary.chmod(0o700);link=root/'link';link.symlink_to(binary)
   with self.assertRaises(ValueError):n.install_ffmpeg_path(package,module,str(link))
   link.unlink();os.link(binary,link)
   with self.assertRaises(ValueError):n.install_ffmpeg_path(package,module,str(binary))
 def test_actual_sdk_dash_decision_and_runner_context_reset(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory).resolve();binary=self.executable(root);package,module=self.sdk_ffmpeg();play_calls=[];limits=[]
   class Crawler:
    def _get_media_downloader(self):return SimpleNamespace(download=AsyncMock(side_effect=lambda *_:limits.append(n.response_limit('bili','video/mp4','cdn.bilivideo.com')) or root/'merged.mp4'))
    async def get_video_play_url_task(self,*args,**kwargs):play_calls.append(kwargs['fnval']);self.json_limit=n.response_limit('bili','application/json','api.bilibili.com');return {'dash':{}}
   method=next(node for node in ast.parse((SDK/'media_platform/bilibili/core.py').read_text()).body if isinstance(node,ast.ClassDef) and node.name=='BilibiliCrawler')
   body=[node for node in method.body if isinstance(node,ast.AsyncFunctionDef) and node.name=='_download_media'];namespace={'asyncio':asyncio,'Dict':dict,'Optional':__import__('typing').Optional,'config':SimpleNamespace(CRAWLER_MAX_SLEEP_SEC=0,BILI_QN=16),'utils':SimpleNamespace(logger=Mock()),'is_ffmpeg_available':package.is_ffmpeg_available,'bili_media':SimpleNamespace(DASH_FNVAL=4048,MP4_FNVAL=1,build_cover_item=lambda *_:None,build_dash_item=lambda *a,**k:object())}
   exec(compile(ast.Module(body=body,type_ignores=[]),str(SDK/'media_platform/bilibili/core.py'),'exec'),namespace);Crawler.download_media=namespace['_download_media']
   namespace['bili_media'].pick_audio_stream=lambda *_:None
   with patch.dict('sys.modules',{'media_downloader':package,'media_downloader.ffmpeg':module,'media_platform.bilibili':SimpleNamespace(media=namespace['bili_media'])}),patch.dict(os.environ,{'CROWD_FFMPEG':str(binary)}),patch.object(shutil,'which',return_value=None),patch.object(m.Path,'cwd',return_value=root):
    m.configure_platform_hooks(SimpleNamespace(CrawlerFactory=SimpleNamespace(CRAWLERS={'bili':Crawler})),{'platform':'bili','mode':'detail','media':True,'comments':False,'platform_options':{'quality':16}})
    crawler=Crawler()
    async def run():await crawler.download_media({'View':{'aid':1,'cid':2,'bvid':'BV1popx6zEe1'}},asyncio.Semaphore(1))
    asyncio.run(run())
   self.assertEqual(play_calls,[4048]);self.assertEqual(limits,[64*1024*1024]);self.assertEqual(crawler.json_limit,25*1024*1024);self.assertFalse(n.NATIVE_VIDEO_MEDIA_ACTIVE.get())
 def test_context_resets_limit_system_exit_and_other_errors_keeps_old_part(self):
  for error in (m.SingleResponseLimit(),SystemExit(73),SystemExit(76),SystemExit(77),ValueError('fixed')):
   with self.subTest(error=type(error)),tempfile.TemporaryDirectory() as directory:
    root=Path(directory).resolve();folder=root/'output/bili/media';folder.mkdir(parents=True);(folder/'old.part').write_bytes(b'old');package,module=self.sdk_ffmpeg()
    class Crawler:
     async def download_media(self):
      self.limit=n.response_limit('bili');(folder/'new.part').write_bytes(b'new');raise error
    with patch.dict('sys.modules',{'media_downloader':package,'media_downloader.ffmpeg':module}),patch.dict(os.environ,{'CROWD_FFMPEG':''}),patch.object(m.Path,'cwd',return_value=root):
     m.configure_platform_hooks(SimpleNamespace(CrawlerFactory=SimpleNamespace(CRAWLERS={'bili':Crawler})),{'platform':'bili','mode':'detail','media':True,'comments':False})
     crawler=Crawler()
     if isinstance(error,m.SingleResponseLimit):asyncio.run(crawler.download_media());self.assertFalse((folder/'new.part').exists())
     else:
      with self.assertRaises(type(error)):asyncio.run(crawler.download_media())
    self.assertEqual(crawler.limit,64*1024*1024);self.assertFalse(n.NATIVE_VIDEO_MEDIA_ACTIVE.get());self.assertEqual((folder/'old.part').read_bytes(),b'old');self.assertEqual(n.response_limit('bili'),25*1024*1024)
 def test_json_and_audio_scope_response_limits(self):
  token=n.NATIVE_VIDEO_MEDIA_ACTIVE.set(True)
  try:
   for platform in ('dy','ks','bili'):
    self.assertEqual(n.response_limit(platform,'application/json; charset=UTF-8'),25*1024*1024);self.assertEqual(n.response_limit(platform,'application/problem+json'),25*1024*1024)
   self.assertEqual(n.response_limit('bili','text/plain','api.bilibili.com'),25*1024*1024)
   self.assertEqual(n.response_limit('bili','video/mp4','cdn.bilivideo.com'),64*1024*1024)
   self.assertEqual(n.response_limit('bili','application/json',None,True),25*1024*1024)
  finally:n.NATIVE_VIDEO_MEDIA_ACTIVE.reset(token)
  self.assertEqual(n.response_limit('bili','audio/mp4',None,True),64*1024*1024)
 def test_actual_runner_byte_guard_json_native_and_total_boundaries(self):
  import bili_audio
  node=next(v for v in ast.walk(ast.parse(Path(m.__file__).read_text())) if isinstance(v,ast.AsyncFunctionDef) and v.name=='bounded_bytes')
  source=textwrap.dedent(ast.get_source_segment(Path(m.__file__).read_text(),node));namespace={'SingleResponseLimit':m.SingleResponseLimit}
  exec('def factory(old_bytes,budget_lock,p,event):\n response_bytes=0\n'+textwrap.indent(source,' ')+'\n return bounded_bytes\n',namespace)
  class Chunk:
   def __init__(self,size):self.size=size
   def __len__(self):return self.size
  async def old_bytes(response,*a,**k):
   for size in response.sizes:yield Chunk(size)
  def response(sizes,mime='video/mp4',host='cdn.bilivideo.com'):return SimpleNamespace(sizes=sizes,headers={'content-type':mime},request=SimpleNamespace(url=SimpleNamespace(host=host)))
  async def consume(fn,r):return [len(value) async for value in fn(r)]
  token=n.NATIVE_VIDEO_MEDIA_ACTIVE.set(True)
  try:
   fn=namespace['factory'](old_bytes,threading.Lock(),{'platform':'bili'},lambda _:None)
   self.assertEqual(asyncio.run(consume(fn,response([64*1024*1024]))),[64*1024*1024])
   for r in (response([64*1024*1024+1]),response([25*1024*1024+1],mime='application/json'),response([25*1024*1024+1],mime='text/plain',host='api.bilibili.com')):
    fn=namespace['factory'](old_bytes,threading.Lock(),{'platform':'bili'},lambda _:None)
    with self.assertRaises(m.SingleResponseLimit):asyncio.run(consume(fn,r))
   fn=namespace['factory'](old_bytes,threading.Lock(),{'platform':'bili'},lambda _:None)
   asyncio.run(consume(fn,response([50*1024*1024])));asyncio.run(consume(fn,response([50*1024*1024])))
   with self.assertRaises(SystemExit) as hard:asyncio.run(consume(fn,response([1])))
   self.assertEqual(hard.exception.code,76)
  finally:n.NATIVE_VIDEO_MEDIA_ACTIVE.reset(token)
  token=bili_audio.AUDIO_RESPONSE_ACTIVE.set(True)
  try:
   fn=namespace['factory'](old_bytes,threading.Lock(),{'platform':'bili','platform_options':{'long_audio':True}},lambda _:None)
   self.assertEqual(asyncio.run(consume(fn,response([64*1024*1024],mime='audio/mp4'))),[64*1024*1024])
  finally:bili_audio.AUDIO_RESPONSE_ACTIVE.reset(token)
 def test_bili_same_view_mapping_preserves_record_and_cloud_identity(self):
  from media_native import _identity
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory).resolve();rid=str(uuid.uuid4());run=root/'runs'/rid;raw=run/'output/bili/jsonl';raw.mkdir(parents=True);source=raw/'detail_contents_fixture.jsonl';source.write_text(json.dumps({'video_id':'123','title':'same native view','desc':'original body'})+'\n');folder=run/'output/bili/media/BV1popx6zEe1';folder.mkdir(parents=True);asset=folder/'video.mp4';asset.write_bytes(b'\0\0\0\x10ftypisom'+b'x'*100);asha=hashlib.sha256(asset.read_bytes()).hexdigest()
   m.write(run/'manifest.json',{'run_id':rid,'request':{'platform':'bili','media':True},'source':{}});m.write(run/'status.json',{'run_id':rid,'state':'completed'});before=m.import_output(root,{'run_id':rid});record=before['records'][0]
   n.save_bilibili_identity({'View':{'aid':123,'cid':234,'bvid':'BV1popx6zEe1'}},run/'output',m.read,m.write);after=m.import_output(root,{'run_id':rid});item=after['media'][0]
   self.assertEqual(after['records'][0],record);self.assertEqual(item['content_id'],'123');self.assertEqual(item['path'],before['media'][0]['path']);self.assertEqual(item['source_media_id'],'BV1popx6zEe1');self.assertEqual(item['content_identity_basis'],'same_native_bilibili_view')
   selected=_identity(run,'123',asha,None);self.assertEqual(selected[1]['entity_ref'],'bilibili:content:123')
   n.save_bilibili_identity({'View':{'aid':999,'cid':234,'bvid':'BV1popx6zEe1'}},run/'output',m.read,m.write);ambiguous=m.import_output(root,{'run_id':rid});self.assertEqual(ambiguous['media'][0]['content_id'],'BV1popx6zEe1')
   with self.assertRaises(ValueError):_identity(run,'123',asha,None)
 def test_long_audio_wrapper_keeps_play_json_outside_native_scope(self):
  import bili_audio
  seen=[]
  class Crawler:
   async def download_media(self,*a,**k):raise AssertionError('native video should not run')
  async def play(**kwargs):seen.append(('play',n.NATIVE_VIDEO_MEDIA_ACTIVE.get(),n.response_limit('bili')));return {'dash':{'audio':[]}}
  async def audio(*args,**kwargs):
   seen.append(('audio_entry',n.NATIVE_VIDEO_MEDIA_ACTIVE.get()))
   token=bili_audio.AUDIO_RESPONSE_ACTIVE.set(True)
   try:seen.append(('audio_limit',n.response_limit('bili',audio_response_active=bili_audio.AUDIO_RESPONSE_ACTIVE.get())))
   finally:bili_audio.AUDIO_RESPONSE_ACTIVE.reset(token)
   return {'status':'unavailable'}
  with tempfile.TemporaryDirectory() as directory,patch.object(m.Path,'cwd',return_value=Path(directory)),patch('bili_audio.download_audio',audio),patch.dict('sys.modules',{'media_platform.bilibili.media':SimpleNamespace(DASH_FNVAL=4048)}):
   m.configure_platform_hooks(SimpleNamespace(CrawlerFactory=SimpleNamespace(CRAWLERS={'bili':Crawler})),{'platform':'bili','mode':'detail','media':True,'comments':False,'platform_options':{'long_audio':True}})
   crawler=Crawler();crawler.bili_client=SimpleNamespace(get_video_play_url=play,headers={})
   async def run():await crawler.download_media({'View':{'aid':1,'cid':2,'bvid':'BV1popx6zEe1'}},asyncio.Semaphore(1))
   asyncio.run(run())
  self.assertEqual(seen,[('play',False,25*1024*1024),('audio_entry',False),('audio_limit',64*1024*1024)]);self.assertFalse(n.NATIVE_VIDEO_MEDIA_ACTIVE.get());self.assertFalse(bili_audio.AUDIO_RESPONSE_ACTIVE.get())
if __name__=='__main__':unittest.main()
