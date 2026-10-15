"""Isolated original MC media-only process. No browser startup or content recrawl."""
import asyncio,contextlib,hashlib,io,json,os,sys,uuid,stat,threading,time,signal
from pathlib import Path
from types import SimpleNamespace
from pro_hybrid_media import bili_view

class EmptyBrowserStorage:
 def __init__(self,storage=None):self.storage={} if storage is None else storage
 async def evaluate(self,script):
  if script!='() => window.localStorage':raise ValueError('media_browser_call_forbidden')
  return dict(self.storage)  # Native Bili receives only this run's verified public keys.

class Quiet:
 def write(self,s):return len(s)
 def flush(self):pass

def verify_assets(run,view,request):
 """Read new-run native output only; never change source body hashes."""
 from native_media_scope import bilibili_identity_map
 from mc_runner import read
 # Original helper checks exact aid/cid/bvid against persisted same-View identity.
 records=[{'kind':'content','content_id':str(view['View']['aid']),'canonical_id_scheme':'bilibili.aid.v1'}]
 identities,identity_hash=bilibili_identity_map(run/'output',run.name,records,read)
 bvid=view['View']['bvid'];pair=identities.get(bvid)
 if not pair:raise ValueError('hybrid_media_identity_missing')
 from analysis_artifact import _safe_ancestors
 result=[];folder=run/'output/bili/media'/bvid;_safe_ancestors(folder)
 if folder.exists():
  paths=sorted(folder.iterdir())
  if len(paths)>1000:raise ValueError('hybrid_media_file_limit')
  total=0
  for path in paths:
   if path.suffix.lower() not in ('.m4a','.mp4','.jpg','.png','.webp'):continue
   if path.is_symlink() or not path.is_file() or path.resolve().parent!=folder.resolve():raise ValueError('hybrid_media_unsafe_file')
   size=path.stat().st_size
   if not 0<size<=67108864:raise ValueError('hybrid_media_size_limit')
   h=hashlib.sha256()
   _safe_ancestors(path)
   fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
   with os.fdopen(fd,'rb') as f:
    before=os.fstat(f.fileno())
    if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1:raise ValueError('hybrid_media_unsafe_file')
    consumed=0
    for block in iter(lambda:f.read(65536),b''):
     consumed+=len(block)
     if consumed>67108864:raise ValueError('hybrid_media_size_limit')
     h.update(block)
    after=os.fstat(f.fileno())
    if (before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns) or consumed!=size:raise ValueError('hybrid_media_concurrent_change')
   total+=size
   if total>104857600:raise ValueError('hybrid_media_total_limit')
   result.append({'path':str(path.relative_to(run)),'bytes':size,'sha256':h.hexdigest(),'platform':'bilibili','content_id':pair['aid'],'source_media_id':bvid,'kind':'audio' if path.suffix=='.m4a' else 'video' if path.suffix=='.mp4' else 'image','status':'downloaded_by_hybrid_media_executor','source_kind':'mediacrawler_api','reward_eligible':False,'content_engine':'mediacrawler_pro','media_engine':'native_mc_media_only','bilibili_view_cid':pair['cid'],'bilibili_media_identity_sha256':identity_hash})
 return result

async def execute_payload(payload,*,client_factory=None):
 """Dependency injection is only for isolated tests; main never accepts callbacks."""
 import config,httpx,requests
 try:import aiohttp
 except ModuleNotFoundError:aiohttp=None
 import mc_runner as m
 from shared_request_budget import RunRequestBudget,request_fingerprint,install_hybrid_transport_limits
 from media_platform.bilibili.core import BilibiliCrawler
 from media_platform.bilibili.client import BilibiliClient
 from pro_executor import ProgressSink
 from analysis_artifact import _safe_ancestors
 run=Path(payload['run']);_safe_ancestors(run)
 if not run.is_absolute():raise ValueError('hybrid_media_run_invalid')
 manifest=m.read(run/'manifest.json');request=manifest['request'];rid=manifest['run_id']
 if run.name!=rid or str(uuid.UUID(rid))!=rid or request['platform']!='bili' or request.get('media') is not True:raise ValueError('hybrid_media_run_invalid')
 if payload['request_hash']!=request_fingerprint(request):raise ValueError('hybrid_media_request_mismatch')
 view=bili_view(payload['note'],payload['response'])
 # New intent and empty media folder: existing outputs cannot masquerade as a new download.
 intent=run/'hybrid-media-intent.json'
 fd=os.open(intent,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'w') as f:json.dump({'run_id':rid,'request_hash':payload['request_hash'],'content_id':payload['note']['video_id'],'retry_unknown_forbidden':True},f)
 (run/'output').mkdir(exist_ok=True)
 folder=run/'output/bili/media'
 if folder.exists() and any(folder.rglob('*')):raise ValueError('hybrid_media_output_not_empty')
 ledger=RunRequestBudget(run/'request-budget.json',rid,payload['request_hash'],request['max_api_requests'])
 sink=ProgressSink(run,manifest);sink.attempts=ledger.snapshot()['used']
 storage=None
 native=manifest.get('executor',{}).get('binding',{}).get('provider')=='native_persistent'
 if native:
  from bili_wbi_context import validate
  storage=validate(payload.get('wbi_context'),run,manifest)
  class GuardedBudget:
   def debit(self,stage):
    validate(payload.get('wbi_context'),run,manifest)
    return ledger.debit(stage)
  budget=GuardedBudget()
 else:
  if 'wbi_context' in payload:raise ValueError('hybrid_media_wbi_context_invalid')
  budget=ledger
 install_hybrid_transport_limits(httpx,requests,aiohttp,request,sink,budget)
 config.ENABLE_GET_MEDIA=True;config.CRAWLER_MAX_SLEEP_SEC=0
 config.SAVE_DATA_PATH=str(run/'output');config.PLATFORM='bili'
 m.configure_executor(config,request)
 upstream=SimpleNamespace(CrawlerFactory=SimpleNamespace(CRAWLERS={'bili':BilibiliCrawler}))
 m.configure_platform_hooks(upstream,request)
 headers=payload.get('headers',{})
 if not isinstance(headers,dict) or set(headers)-{'Cookie','User-Agent','Referer'} or any(not isinstance(v,str) or '\n' in v or '\r' in v for v in headers.values()):raise ValueError('hybrid_media_headers_invalid')
 crawler=BilibiliCrawler();crawler.bili_client=(client_factory or BilibiliClient)(headers=headers,playwright_page=EmptyBrowserStorage(storage),cookie_dict={})
 with contextlib.redirect_stdout(Quiet()),contextlib.redirect_stderr(Quiet()):
  await crawler.download_media(view,asyncio.Semaphore(1))
 assets=verify_assets(run,view,request)
 phase=m.safe_phase_progress(run);subtitle_available=phase.get('subtitle_status')=='available'
 options=request.get('platform_options',{});expected_kind='audio' if options.get('long_audio') is True else 'video'
 complete=any(a['kind']==expected_kind for a in assets) or (options.get('transcript_only') is True and subtitle_available)
 result={'schema_version':1,'run_id':rid,'request_hash':payload['request_hash'],'state':'completed' if complete else 'partial','assets':assets,'subtitle_available':subtitle_available,'api_attempts':ledger.snapshot()['used'],'cloud_ack':False,'content_engine':'mediacrawler_pro','media_engine':'native_mc_media_only'}
 m.write(run/'hybrid-media-result.json',result)
 return result

def install_watchdog(run,request):
 """POSIX media process group only, reusing original MC output accounting."""
 from native_media_scope import output_byte_usage
 from mc_runner import write
 if os.getpgrp()!=os.getpid():raise ValueError('hybrid_media_owned_process_group_required')
 parent=os.getppid();deadline=time.monotonic()+request['timeout_seconds'];finished=threading.Event()
 def watch():
  while not finished.wait(.1):
   reason=None
   if os.getppid()!=parent:reason='media_parent_exited'
   elif (run/'stop.json').exists():reason='media_stop_requested'
   elif time.monotonic()>deadline:reason='wall_timeout'
   else:
    try:
     if output_byte_usage(run/'output',request,os.getpid())['limited']:reason='output_byte_limit'
    except (OSError,ValueError):reason='media_output_watchdog_failed'
   if reason:
    try:write(run/'hybrid-media-stop.json',{'failure_reason':reason,'run_id':run.name})
    finally:
     os.killpg(os.getpgrp(),signal.SIGTERM)
     os._exit(74)
 threading.Thread(target=watch,daemon=True,name='owned-media-watchdog').start()
 return finished

def main():
 # Parent pins interpreter/MC/runtime paths before subprocess. IPC carries headers
 # only in memory; never echo payload, exception text or upstream logs.
 data=sys.stdin.buffer.read(131073)
 if len(data)>131072:raise ValueError('hybrid_media_input_limit')
 payload=json.loads(data);run=Path(payload['run']).resolve();os.chdir(run)
 manifest=json.loads((run/'manifest.json').read_text());stop=install_watchdog(run,manifest['request'])
 try:asyncio.run(execute_payload(payload))
 finally:stop.set()
if __name__=='__main__':
 try:main()
 except SystemExit:raise
 except BaseException:
  sys.stderr.write('hybrid_media_failed_or_unknown\n');raise SystemExit(87)
