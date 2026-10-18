"""Same-issued public Douyin media references -> installed MC media-only downloader."""
import asyncio,contextlib,hashlib,json,os,stat,sys,uuid
from pathlib import Path
from urllib.parse import urlsplit
from bili_media_child import Quiet,install_watchdog

def validate_source(note,source):
 if type(source) is not dict or set(source)!={'aweme_id','images','video'} or source['aweme_id']!=note.get('aweme_id'):raise ValueError('hybrid_douyin_source_mismatch')
 # The package __init__ imports a browser crawler with cwd-relative JS. Load
 # the mature pure media extractor directly; never import that crawler.
 import importlib.util
 package=importlib.util.find_spec('media_platform')
 location=Path(next(iter(package.submodule_search_locations)))/'douyin/media.py'
 spec=importlib.util.spec_from_file_location('_installed_mc_douyin_media',location)
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 items=module.build_media_items(source)
 if not items or len(items)>100:raise ValueError('hybrid_douyin_media_missing')
 for item in items:
  for raw in (item.url,*item.backup_urls):
   u=urlsplit(raw)
   if u.scheme!='https' or not u.hostname or u.username or u.password or u.fragment or u.port not in (None,443) or not any(u.hostname==h or u.hostname.endswith('.'+h) for h in ('douyincdn.com','douyinpic.com','douyinstatic.com','byteimg.com','ibytedtos.com','pstatp.com','douyin.com')):raise ValueError('hybrid_douyin_url_invalid')
 return items

def verify_assets(run,note,source):
 from media_downloader import MediaType
 from analysis_artifact import _safe_ancestors
 from shared_request_budget import canonical
 items=validate_source(note,source);folder=Path(run)/'output/dy/media'/note['aweme_id'];result=[];total=0
 if not folder.exists():return []
 for path in folder.iterdir():
  if path.name.endswith(('.tmp','.part')):continue
  matched=[item for item in items if item.stem==path.stem]
  if len(matched)!=1:raise ValueError('hybrid_douyin_unregistered_asset')
  item=matched[0];_safe_ancestors(path);fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
  with os.fdopen(fd,'rb') as f:
   before=os.fstat(f.fileno())
   if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or not 0<before.st_size<=52428800:raise ValueError('hybrid_douyin_asset_invalid')
   digest=hashlib.file_digest(f,'sha256').hexdigest();after=os.fstat(f.fileno())
   if (before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns):raise ValueError('hybrid_douyin_asset_changed')
  total+=before.st_size
  if total>104857600:raise SystemExit(76)
  kind=str(item.media_type.value)
  if kind=='image':
   from PIL import Image
   with Image.open(path) as im:
    if im.format not in ('JPEG','PNG','WEBP') or getattr(im,'n_frames',1)!=1 or not 0<im.width*im.height<=16777216:raise ValueError('hybrid_douyin_image_invalid')
    im.load()
  elif kind=='video':
   import subprocess
   value=json.loads(subprocess.run(['ffprobe','-v','error','-show_entries','stream=codec_type','-of','json',str(path)],capture_output=True,check=True,timeout=15).stdout)
   if not any(s['codec_type']=='video' for s in value['streams']):raise ValueError('hybrid_douyin_video_invalid')
  else:raise ValueError('hybrid_douyin_kind_invalid')
  result.append({'path':str(path.relative_to(run)),'bytes':before.st_size,'sha256':digest,'platform':'douyin','content_id':note['aweme_id'],'kind':kind,'source_kind':'mediacrawler_api','reward_eligible':False,'content_engine':'mediacrawler_pro','media_engine':'native_mc_media_only','source_media_id':note['aweme_id'],'original_url':item.url,'douyin_observation_sha256':hashlib.sha256(canonical(note).encode()).hexdigest()})
 return sorted(result,key=lambda x:x['path'])

def install_media_bounds(httpx):
 # Keep the mature downloader; bound bytes before each block reaches its file.
 original_send=httpx.AsyncClient.send;original_bytes=httpx.Response.aiter_bytes;total=0
 async def send(client,request,*a,**kw):
  response=await original_send(client,request,*a,**kw)
  length=response.headers.get('content-length')
  if length is not None:
   if not length.isdecimal():raise ValueError('hybrid_douyin_length_invalid')
   if int(length)>52428800 or total+int(length)>104857600:raise SystemExit(76)
  return response
 async def bounded_bytes(response,*a,**kw):
  nonlocal total
  consumed=0
  async for block in original_bytes(response,*a,**kw):
   consumed+=len(block);total+=len(block)
   if consumed>52428800 or total>104857600:raise SystemExit(76)
   yield block
 httpx.AsyncClient.send,httpx.Response.aiter_bytes=send,bounded_bytes
 def restore():httpx.AsyncClient.send,httpx.Response.aiter_bytes=original_send,original_bytes
 return restore

async def execute_payload(payload):
 import httpx,requests
 try:import aiohttp
 except ImportError:aiohttp=None
 from media_downloader import MediaDownloader
 from shared_request_budget import RunRequestBudget,request_fingerprint,canonical,install_hybrid_transport_limits
 from pro_executor import observations,ProgressSink
 import mc_runner as m
 run=Path(payload['run']);manifest=m.read(run/'manifest.json');request=manifest['request'];rid=manifest['run_id']
 if run.name!=rid or str(uuid.UUID(rid))!=rid or request['platform']!='dy' or request['source_executor']!='pro' or request['media'] is not True or request['mode'] not in ('detail','homefeed','trending') or request['max_items']!=1 or request['platform_options']!={} or payload.get('headers')!={} or payload['request_hash']!=request_fingerprint(request):raise ValueError('hybrid_douyin_request_invalid')
 topics=[row for kind,entity,row in observations(run,manifest) if kind=='topic']
 if len(topics)!=1 or canonical(topics[0])!=canonical(payload['note']):raise ValueError('hybrid_douyin_observation_mismatch')
 source=m.read(run/'dy-media-source.json');note=topics[0]
 if source.get('observation_sha256')!=hashlib.sha256(canonical(note).encode()).hexdigest() or source.get('run_id')!=rid or canonical(payload['response'])!=canonical(source):raise ValueError('hybrid_douyin_source_mismatch')
 items=validate_source(note,source['source']);fd=os.open(run/'hybrid-media-intent.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'w') as f:json.dump({'run_id':rid,'request_hash':payload['request_hash'],'retry_unknown_forbidden':True},f)
 folder=run/'output/dy/media'
 if folder.exists() and any(folder.rglob('*')):raise ValueError('hybrid_media_output_not_empty')
 ledger=RunRequestBudget(run/'request-budget.json',rid,payload['request_hash'],request['max_api_requests']);sink=ProgressSink(run,manifest);install_hybrid_transport_limits(httpx,requests,aiohttp,request,sink,ledger)
 restore_bounds=install_media_bounds(httpx)
 original=httpx.AsyncClient.send;allowed={u for item in items for u in (item.url,*item.backup_urls)}
 async def exact_send(client,request,*a,**kw):
  if request.method!='GET' or str(request.url) not in allowed or 'cookie' in request.headers:raise ValueError('hybrid_douyin_transport_forbidden')
  return await original(client,request,*a,**kw)
 httpx.AsyncClient.send=exact_send
 downloader=MediaDownloader('dy',base_dir=run/'output',max_retries=0,max_candidates=1,overwrite=False,timeout=min(30,request['timeout_seconds']))
 try:
  with contextlib.redirect_stdout(Quiet()),contextlib.redirect_stderr(Quiet()):await downloader.download_all(items)
 except BaseException:
  # A failed media stage must retain verified bytes and previously committed
  # source, while preserving the original budget/cancellation exception.
  try:
   partial=verify_assets(run,note,source['source'])
   m.write(run/'hybrid-media-result.json',{'schema_version':1,'run_id':rid,'request_hash':payload['request_hash'],'state':'partial','assets':partial,'subtitle_available':False,'api_attempts':ledger.snapshot()['used'],'cloud_ack':False,'content_engine':'mediacrawler_pro','media_engine':'native_mc_media_only'})
  except (OSError,ValueError,TypeError):pass
  raise
 finally:
  httpx.AsyncClient.send=original;restore_bounds()
 assets=verify_assets(run,note,source['source']);result={'schema_version':1,'run_id':rid,'request_hash':payload['request_hash'],'state':'completed' if len(assets)==len(items) else 'partial','assets':assets,'subtitle_available':False,'api_attempts':ledger.snapshot()['used'],'cloud_ack':False,'content_engine':'mediacrawler_pro','media_engine':'native_mc_media_only'};m.write(run/'hybrid-media-result.json',result);return result

def main():
 raw=sys.stdin.buffer.read(131073)
 if len(raw)>131072:raise ValueError('hybrid_media_input_limit')
 payload=json.loads(raw);run=Path(payload['run']).resolve();os.chdir(run);manifest=json.loads((run/'manifest.json').read_text());stop=install_watchdog(run,manifest['request'])
 try:asyncio.run(execute_payload(payload))
 finally:stop.set()
if __name__=='__main__':
 try:main()
 except SystemExit:raise
 except BaseException:sys.stderr.write('hybrid_douyin_media_failed_or_unknown\n');raise SystemExit(87)
