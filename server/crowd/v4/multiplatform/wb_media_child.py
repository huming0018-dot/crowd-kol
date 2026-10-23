"""Owned MC downloader for one committed Pro Weibo image post; no browser or cookies."""
import asyncio,contextlib,hashlib,json,os,stat,sys,uuid,warnings
from pathlib import Path
from pro_hybrid_media import weibo_mblog,weibo_image_plan,download_weibo_images,supports_weibo_images
from bili_media_child import Quiet,install_watchdog
MAX_IMAGE=26214400

def verify_assets(run,note):
 from analysis_artifact import _safe_ancestors
 from shared_request_budget import canonical
 from PIL import Image
 mblog=weibo_mblog(note);items=weibo_image_plan(note);folder=Path(run)/'output/wb/media'/note['note_id'];_safe_ancestors(folder)
 if not folder.exists():return []
 paths=sorted(folder.iterdir());result=[];seen=set();total=0;observation=hashlib.sha256(canonical(note).encode()).hexdigest()
 for path in paths:
  if path.name.endswith(('.part','.tmp')):continue
  if path.suffix.lower() not in ('.jpg','.jpeg','.png','.webp','.gif') or not path.stem.isdigit():raise ValueError('hybrid_weibo_unregistered_asset')
  index=int(path.stem)
  if not 1<=index<=len(items) or index in seen or path.stem!=f'{index:03d}':raise ValueError('hybrid_weibo_unregistered_asset')
  seen.add(index);_safe_ancestors(path)
  fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
  with os.fdopen(fd,'rb') as f:
   before=os.fstat(f.fileno())
   if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or not 0<before.st_size<=MAX_IMAGE:raise ValueError('hybrid_weibo_asset_invalid')
   raw=f.read(MAX_IMAGE+1);after=os.fstat(f.fileno())
   if len(raw)!=before.st_size or (before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns):raise ValueError('hybrid_weibo_asset_changed')
  total+=len(raw)
  if total>104857600:raise ValueError('hybrid_media_total_limit')
  import io
  try:
   with warnings.catch_warnings():
    warnings.simplefilter('error',Image.DecompressionBombWarning)
    with Image.open(io.BytesIO(raw)) as image:
     if image.format not in ('JPEG','PNG','WEBP','GIF') or getattr(image,'n_frames',1)!=1 or not 0<image.width*image.height<=16777216:raise ValueError('hybrid_weibo_image_invalid')
     image.load();width,height=image.size;rgba=hashlib.sha256(image.convert('RGBA').tobytes()).hexdigest()
  except (OSError,ValueError,Image.DecompressionBombError,Image.DecompressionBombWarning):
   raise ValueError('hybrid_weibo_image_invalid') from None
  result.append({'path':str(path.relative_to(run)),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'platform':'weibo','content_id':note['note_id'],'source_media_id':note['note_id'],'kind':'image','status':'downloaded_by_hybrid_media_executor','source_kind':'mediacrawler_api','reward_eligible':False,'content_engine':'mediacrawler_pro','media_engine':'native_mc_media_only','original_url':mblog['pics'][index-1]['url'],'transport_url':items[index-1]['transport_url'],'image_index':index,'weibo_observation_sha256':observation,'width':width,'height':height,'rgba_sha256':rgba})
 return result

async def execute_payload(payload):
 import httpx,requests
 try:import aiohttp
 except ImportError:aiohttp=None
 from media_downloader import MediaDownloader
 from media_platform.weibo import media as wb_media
 from shared_request_budget import RunRequestBudget,request_fingerprint,canonical,install_hybrid_transport_limits
 from pro_executor import observations,ProgressSink
 from analysis_artifact import _safe_ancestors
 import mc_runner as m
 run=Path(payload['run']);_safe_ancestors(run)
 if not run.is_absolute():raise ValueError('hybrid_media_run_invalid')
 manifest=m.read(run/'manifest.json');request=manifest['request'];rid=manifest['run_id']
 if run.name!=rid or str(uuid.UUID(rid))!=rid or not supports_weibo_images(request):raise ValueError('hybrid_media_run_invalid')
 if payload['request_hash']!=request_fingerprint(request) or payload.get('headers')!={}:raise ValueError('hybrid_media_request_mismatch')
 topics=[row for kind,entity,row in observations(run,manifest) if kind=='topic']
 if len(topics)!=1 or canonical(topics[0])!=canonical(payload['note']):raise ValueError('hybrid_weibo_observation_mismatch')
 note=topics[0];mblog=weibo_mblog(note);oh=hashlib.sha256(canonical(note).encode()).hexdigest()
 if payload.get('response')!={'weibo_observation_sha256':oh}:raise ValueError('hybrid_weibo_observation_mismatch')
 fd=os.open(run/'hybrid-media-intent.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'w') as f:json.dump({'run_id':rid,'request_hash':payload['request_hash'],'content_id':note['note_id'],'weibo_observation_sha256':oh,'retry_unknown_forbidden':True},f)
 output=run/'output';output.mkdir(exist_ok=True);folder=output/'wb/media';_safe_ancestors(folder)
 if folder.exists() and any(folder.rglob('*')):raise ValueError('hybrid_media_output_not_empty')
 ledger=RunRequestBudget(run/'request-budget.json',rid,payload['request_hash'],request['max_api_requests'])
 sink=ProgressSink(run,manifest);sink.attempts=ledger.snapshot()['used'];install_hybrid_transport_limits(httpx,requests,aiohttp,request,sink,ledger)
 plan=weibo_image_plan(note);native_items=wb_media.build_media_items(mblog)
 if [i.url for i in native_items]!=[i['transport_url'] for i in plan]:raise ValueError('hybrid_media_sdk_contract_changed')
 allowed={i.url for i in native_items};original_send=httpx.AsyncClient.send;original_bytes=httpx.Response.aiter_bytes
 async def exact_send(client,request,*a,**kw):
  if request.method!='GET' or str(request.url) not in allowed or 'cookie' in request.headers:raise ValueError('hybrid_weibo_transport_forbidden')
  return await original_send(client,request,*a,**kw)
 async def bounded_bytes(response,*a,**kw):
  consumed=0
  async for block in original_bytes(response,*a,**kw):
   consumed+=len(block)
   if consumed>MAX_IMAGE:raise SystemExit(76)
   yield block
 httpx.AsyncClient.send,httpx.Response.aiter_bytes=exact_send,bounded_bytes
 downloader=MediaDownloader('wb',base_dir=output,extra_headers={'Referer':'https://weibo.com/'},max_retries=0,max_candidates=1,overwrite=False,timeout=min(30,request['timeout_seconds']))
 with contextlib.redirect_stdout(Quiet()),contextlib.redirect_stderr(Quiet()):await download_weibo_images(note,wb_media,downloader)
 assets=verify_assets(run,note);complete=len(assets)==len(mblog['pics'])
 result={'schema_version':1,'run_id':rid,'request_hash':payload['request_hash'],'state':'completed' if complete else 'partial','assets':assets,'subtitle_available':False,'api_attempts':ledger.snapshot()['used'],'cloud_ack':False,'content_engine':'mediacrawler_pro','media_engine':'native_mc_media_only'};m.write(run/'hybrid-media-result.json',result);return result

def main():
 raw=sys.stdin.buffer.read(131073)
 if len(raw)>131072:raise ValueError('hybrid_media_input_limit')
 payload=json.loads(raw);run=Path(payload['run']).resolve();os.chdir(run);manifest=json.loads((run/'manifest.json').read_text());stop=install_watchdog(run,manifest['request'])
 try:asyncio.run(execute_payload(payload))
 finally:stop.set()
if __name__=='__main__':
 try:main()
 except SystemExit:raise
 except BaseException:sys.stderr.write('hybrid_media_failed_or_unknown\n');raise SystemExit(87)
