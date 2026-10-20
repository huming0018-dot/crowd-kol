"""Same-run original Pro PC page -> existing Tieba downloader in owned MC child."""
import asyncio,hashlib,json,os,sys,uuid,stat
from pathlib import Path
from pro_tieba_entry import read_json,safe_path,source_assets
from pro_tieba_adapter import digest
from bili_media_child import install_watchdog

async def execute_payload(payload):
 import httpx
 from shared_request_budget import RunRequestBudget,request_fingerprint,install_hybrid_transport_limits
 from pro_executor import observations
 from tieba_media import download_assets,extract_assets
 run=safe_path(payload['run']);manifest=read_json(run/'manifest.json');request=manifest['request'];rid=manifest['run_id']
 if run.name!=str(uuid.UUID(rid)) or request['platform']!='tieba' or request['mode']!='detail' or request['media'] is not True or request['max_items']!=1 or request.get('platform_options',{})!={}:raise ValueError('tieba_media_scope_invalid')
 source=read_json(run/'tieba-media-source.json');raw=source['raw'];expected=digest(source)
 if source['run_id']!=rid or payload['response']!={'tieba_source_sha256':expected} or payload['headers']!={} or payload['request_hash']!=request_fingerprint(request):raise ValueError('tieba_media_binding_invalid')
 topics=[row for kind,identity,row in observations(run,manifest) if kind=='topic']
 if len(topics)!=1 or topics[0].get('note_id')!=source['content_id'] or payload['note']!={'note_id':source['content_id']}:raise ValueError('tieba_media_source_invalid')
 from media_platform.tieba.help import TieBaExtractor
 original=TieBaExtractor().extract_note_detail_from_api(raw).model_dump()
 if source.get('source_observation_sha256')!=digest(topics[0]):raise ValueError('tieba_media_source_changed')
 common=('note_id','title','desc','note_url','tieba_name','tieba_link','total_replay_num','total_replay_page')
 if any(topics[0].get(k)!=original.get(k) for k in common):raise ValueError('tieba_media_source_changed')
 from pro_tieba_entry import verify_media_source,summary
 expected_assets=verify_media_source(source)
 if summary(run,manifest,sys.modules['pro_executor']).get('coverage') not in ('exhausted','limit_reached','not_requested'):raise ValueError('tieba_media_scope_unverified')
 fd=os.open(run/'hybrid-media-intent.json',os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'w') as out:json.dump({'run_id':rid,'source_sha256':expected,'retry_unknown_forbidden':True},out)
 ledger=RunRequestBudget(run/'request-budget.json',rid,request_fingerprint(request),request['max_api_requests'])
 try:import requests
 except ImportError:requests=None
 # MC runtime has requests; no silent missing guard when used by its transports.
 if requests is None:raise ValueError('tieba_media_runtime_dependency_missing')
 sink=type('Sink',(),{'attempts':0,'update':lambda self,**kw:None})()
 install_hybrid_transport_limits(httpx,requests,None,request,sink,ledger)
 expected_assets=source_assets(raw)
 if [x['transport_url'] for x in expected_assets]!=[x['url'] for x in extract_assets(raw)]:raise ValueError('tieba_media_extractor_changed')
 async with httpx.AsyncClient(timeout=12,trust_env=False,follow_redirects=False) as client:result=await download_assets(raw,source['content_id'],run/'output',client)
 assets=[]
 for item in result['downloaded']:
  path=safe_path(item['path']);fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
  try:
   before=os.fstat(fd)
   if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or not 0<before.st_size<=25*1024*1024:raise ValueError('tieba_media_file_invalid')
   chunks=[];total=0
   while True:
    block=os.read(fd,65536)
    if not block:break
    total+=len(block)
    if total>25*1024*1024:raise ValueError('tieba_media_size_limit')
    chunks.append(block)
   data=b''.join(chunks);after=os.fstat(fd)
   if (before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns):raise ValueError('tieba_media_file_changed')
  finally:os.close(fd)
  if item['type']=='mp4':raise ValueError('tieba_media_video_scope_unverified')
  from saved_media_attachments import decode_bytes
  pixels=decode_bytes(data)
  if not data or len(data)!=item['bytes'] or hashlib.sha256(data).hexdigest()!=item['sha256']:raise ValueError('tieba_media_bytes_changed')
  assets.append({**item,**pixels,'path':str(path.relative_to(run)),'platform':'tieba','kind':'image' if item['type']!='mp4' else 'video','source_kind':'mediacrawler_api','reward_eligible':False,'content_engine':'mediacrawler_pro','media_engine':'native_mc_media_only','source_observation_sha256':digest(topics[0]),'source_page_sha256':expected,'original_url':expected_assets[len(assets)]['original_url'],'transport_url':expected_assets[len(assets)]['transport_url']})
 status='completed' if not result['errors'] and len(assets)==len(expected_assets) else 'partial'
 output={'schema_version':1,'run_id':rid,'request_hash':request_fingerprint(request),'state':status,'assets':assets,'api_attempts':ledger.snapshot()['used'],'cloud_ack':False,'content_engine':'mediacrawler_pro','media_engine':'native_mc_media_only'}
 import mc_runner as m;m.write(run/'hybrid-media-result.json',output)
 return output

def main():
 raw=sys.stdin.buffer.read(131073)
 if len(raw)>131072:raise ValueError('tieba_media_input_limit')
 payload=json.loads(raw);run=safe_path(payload['run']);os.chdir(run);manifest=read_json(run/'manifest.json');stop=install_watchdog(run,manifest['request'])
 try:asyncio.run(execute_payload(payload))
 finally:stop.set()
if __name__=='__main__':
 try:main()
 except SystemExit:raise
 except BaseException:sys.stderr.write('tieba_media_failed_or_unknown\n');raise SystemExit(87)
