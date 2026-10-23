"""Own XHS image glue around a separately licensed Pro DownloadManager.
No platform parser, downloader implementation, browser or account credentials.
"""
import hashlib,json,os,re,stat,subprocess,sys,uuid
from pathlib import Path
MANAGER_SHA='8fe88ee05ac91fa7e256be921b67e6fcb9396f337fed0a92f8ca12ea45e5c84e'
ENGINE='native_pro_downloader'
DRIVER_SHA='056c4a28fbee3975ad0d36427ef655979c6c324356aa06723b8d102d4ddeb66f'
AXIOS_INVENTORY_SHA='7341217843184a92af65c4a7125094242d5fe52c48f035740e7ab62fb89f85ba'

def digest(value):
 from shared_request_budget import canonical
 return hashlib.sha256(value if isinstance(value,bytes) else canonical(value).encode()).hexdigest()

def supports(request):
 return (request.get('platform')=='xhs' and request.get('source_executor')=='pro' and request.get('media') is True
  and request.get('mode') in ('search','detail','creator') and request.get('platform_options',{})=={} and request.get('wordcloud',False) is False)

TRANSPORT_POLICY='native_source_url_v1'

def transport_policy(run):
 from saved_media_attachments import safe_path,read_json_object
 p=Path(run)/'xhs-pro-media-intent.json'
 if not p.exists()and not p.is_symlink():return TRANSPORT_POLICY
 value=read_json_object(safe_path(p,run),1048576)
 if 'transport_policy'not in value:return 'legacy_https_v1'
 if value['transport_policy']!=TRANSPORT_POLICY:raise ValueError('xhs_media_transport_policy_invalid')
 return TRANSPORT_POLICY

def plan(run,manifest):
 from pro_executor import import_records
 from saved_media_attachments import reference_transport
 if not supports(manifest['request']) or Path(run).name!=manifest['run_id'] or str(uuid.UUID(manifest['run_id']))!=manifest['run_id']:raise ValueError('xhs_media_run_invalid')
 records,refs,_=import_records(run,manifest,include_media_summary=False)
 from pro_executor import observations
 if any(row.get('type')!='normal' or type(row.get('image_list')) is not str for kind,_,row in observations(run,manifest) if kind=='topic'):raise ValueError('xhs_media_images_only_scope')
 if not records or not any(r['kind']=='content' for r in records):raise ValueError('xhs_media_source_missing')
 result=[];seen=set()
 for ref in refs:
  if ref.get('kind') not in ('image','comment_image','cover'):raise ValueError('xhs_media_video_not_adapted')
  mid=ref['media_id'];cid=ref['content_id']
  if not re.fullmatch('[0-9a-f]{64}',mid) or not re.fullmatch('[0-9a-f]{24}',cid) or mid in seen:raise ValueError('xhs_media_reference_invalid')
  seen.add(mid);url=ref['url'] if transport_policy(run)==TRANSPORT_POLICY else reference_transport(ref)
  from urllib.parse import urlsplit
  u=urlsplit(url)
  if u.scheme not in ('http','https') or u.username or u.password or u.fragment or u.port not in ((None,80)if u.scheme=='http'else(None,443)) or not any(u.hostname==d or (u.hostname or '').endswith('.'+d) for d in ('xhscdn.com','xhsimg.com')):raise ValueError('xhs_media_reference_invalid')
  result.append({'content_id':cid,'media_id':mid,'url':url})
 return result

def identity(run,manifest):
 from account_sessions import AccountSessions
 from analysis_artifact import _safe_ancestors
 root=Path(run).parent.parent;sid=manifest['request']['session_id'];store=AccountSessions(root)
 state=store.status(sid,'xhs')
 if (state.get('state') not in ('authenticated','resumed') or state.get('login_verified') is not True or state.get('authorized_for_run')!=manifest['run_id'] or type(state.get('generation')) is not int or state['generation']<0 or not re.fullmatch('[0-9a-f]{64}',state.get('account_ref',''))):raise ValueError('xhs_media_identity_unverified')
 paths=[store.root/sid/'state.json',root/'sessions'/sid/'identity.json',root/'sessions'/sid/'pro-binding.json']
 # Reuse the existing fixed Pro binding reader; no browser credentials.
 from pro_executor import binding_for
 binding=binding_for(root,manifest['request'])
 for p in paths[:2]:_safe_ancestors(p)
 if (root/'sessions'/sid/'login-stop').exists():raise ValueError('xhs_media_identity_changed')
 return {'session_id':sid,'state_path':str(paths[0]),'state_sha256':digest(paths[0].read_bytes()),'identity_path':str(paths[1]),'identity_sha256':digest(paths[1].read_bytes()),'binding_path':str(paths[2]),'binding_sha256':digest(paths[2].read_bytes()),'binding':binding}

def check_context(run,manifest,intent):
 from shared_request_budget import request_fingerprint
 if (Path(run)/'stop.json').exists():raise SystemExit(74)
 if dependency_binding(Path(run).parent.parent)['binding_sha256']!=intent.get('dependency_binding_sha256'):raise ValueError('xhs_media_dependency_binding_changed')
 if manifest['run_id']!=Path(run).name or intent.get('run_id')!=manifest['run_id'] or intent.get('request_hash')!=request_fingerprint(manifest['request']) or intent.get('plan')!=plan(run,manifest) or intent.get('identity')!=identity(run,manifest):raise ValueError('xhs_media_context_changed')

def guard(run,row):
 from mc_runner import read
 from shared_request_budget import RunRequestBudget,request_fingerprint
 run=Path(run);manifest=read(run/'manifest.json');intent=read(run/'xhs-pro-media-intent.json');check_context(run,manifest,intent)
 if type(row) is not dict or set(row)!={'method','url','media_id'} or row['method'] not in ('HEAD','GET') or not any(x['media_id']==row['media_id'] and x['url']==row['url'] for x in intent['plan']):raise ValueError('xhs_media_transport_scope')
 # Every original-manager HEAD and GET is a real shared-budget attempt.
 return RunRequestBudget(run/'request-budget.json',manifest['run_id'],request_fingerprint(manifest['request']),manifest['request']['max_api_requests']).debit('media')

def verify_assets(run,manifest,assets):
 from saved_media_attachments import safe_path,read,decode_bytes
 expected=plan(run,manifest)
 if type(assets) is not list or len(assets)!=len(expected):raise ValueError('xhs_media_asset_set_mismatch')
 result=[]
 from pro_executor import import_records
 refs={r['media_id']:r for r in import_records(run,manifest,include_media_summary=False)[1]}
 for item,a in zip(expected,assets):
  if type(a) is not dict or a.get('content_id')!=item['content_id'] or a.get('source_media_id')!=item['media_id'] or a.get('transport_url')!=item['url'] or a.get('media_engine')!=ENGINE or a.get('content_engine')!='mediacrawler_pro' or a.get('source_kind')!='mediacrawler_api' or a.get('reward_eligible') is not False or a.get('kind')!='image':raise ValueError('xhs_media_asset_binding_invalid')
  p=Path(a['path']);p=p if p.is_absolute() else Path(run)/p;p=safe_path(p,Path(run)/'output')
  expected_path=Path(run)/'output/xhs/media'/item['content_id']/(digest(item['media_id'].encode())+'.png')
  if p!=expected_path:raise ValueError('xhs_media_asset_path_invalid')
  data=read(p,2097152);decoded=decode_bytes(data)
  if p.stat().st_nlink!=1:raise ValueError('xhs_media_asset_path_invalid')
  if not data or type(a.get('bytes')) is not int or a.get('bytes')!=len(data) or a.get('sha256')!=digest(data):raise ValueError('xhs_media_asset_changed')
  result.append({**a,'path':str(p.relative_to(run)),'platform':'xiaohongshu','original_url':refs[item['media_id']]['url'],'status':'downloaded_by_native_pro_downloader','width':decoded['width'],'height':decoded['height'],'rgba_sha256':decoded['pixel_sha256']})
 # Nothing outside the verified object set may be admitted by the scanner.
 folder=Path(run)/'output/xhs/media'
 files={p for p in folder.rglob('*') if p.is_file()} if folder.exists() else set()
 if files!={Path(run)/a['path'] for a in result}:raise ValueError('xhs_media_unregistered_asset')
 return result


def dependency_binding(root):
 """Private operator local-reference metadata; never task/browser supplied paths."""
 from saved_media_attachments import safe_path,read_json_object,read
 try:driver=read(Path(__file__).with_name('pro_xhs_download.mjs'),1048576)
 except (OSError,ValueError):raise ValueError('xhs_media_driver_unavailable') from None
 if digest(driver)!=DRIVER_SHA:raise ValueError('xhs_media_driver_changed')
 p=safe_path(Path(root)/'pro-xhs-media.json');info=p.stat()
 if info.st_mode&0o077 or info.st_uid!=os.getuid():raise ValueError('xhs_media_dependency_binding_invalid')
 value=read_json_object(p,1048576)
 if (set(value)!={'schema','manager_path','manager_sha256','axios_root','axios_files'} or value['schema']!='crowd-pro-xhs-download-manager-v1' or value['manager_sha256']!=MANAGER_SHA or type(value['axios_files']) is not dict or not value['axios_files']):raise ValueError('xhs_media_dependency_binding_invalid')
 source=safe_path(value['manager_path']);axios_root=safe_path(value['axios_root'])
 if digest(read(source,1048576))!=MANAGER_SHA:raise ValueError('xhs_manager_changed')
 if digest(value['axios_files'])!=AXIOS_INVENTORY_SHA:raise ValueError('xhs_media_dependency_inventory_untrusted')
 actual={str(f.relative_to(axios_root)) for f in axios_root.rglob('*') if f.is_file() or f.is_symlink()}
 if actual!=set(value['axios_files']):raise ValueError('xhs_media_dependency_files_changed')
 for name,expected in value['axios_files'].items():
  f=safe_path(axios_root/name,axios_root)
  if not re.fullmatch('[0-9a-f]{64}',expected) or digest(read(f,8388608))!=expected:raise ValueError('xhs_media_dependency_files_changed')
 if json.loads(read(axios_root/'node_modules/axios/package.json',1048576)).get('version')!='0.21.4' or json.loads(read(axios_root/'node_modules/follow-redirects/package.json',1048576)).get('version')!='1.15.9':raise ValueError('xhs_media_dependency_version_changed')
 return {**value,'binding_path':str(p),'binding_sha256':digest(p.read_bytes())}

FAILURE_REASONS=frozenset(('xhs_media_http_rejected','xhs_media_transport_timeout','xhs_media_transport_failed','xhs_media_unknown_failure','xhs_media_http_status','xhs_media_type_invalid','xhs_media_size_invalid','xhs_media_stream_invalid','xhs_media_length_mismatch','xhs_media_timeout','xhs_media_output_invalid','xhs_media_output_exists','xhs_media_context_changed','xhs_media_budget_exhausted','xhs_media_stopped','xhs_media_guard_failed','xhs_manager_changed','xhs_manager_import_changed'))

TRANSPORT_ERRNOS=frozenset(('ETIMEDOUT','ECONNABORTED','ECONNRESET','ENOTFOUND','EAI_AGAIN','ECONNREFUSED'))

def _failure_shape(value):
 if type(value)is not dict:raise ValueError('xhs_media_failure_diagnostic_invalid')
 version=value.get('schema')
 keys={'schema','stage','reason','http_status'}
 if version=='crowd-xhs-media-failure-v2':
  keys|={'transport_errno','stream_bytes'}
  errno=value.get('transport_errno');count=value.get('stream_bytes')
  if not(errno is None or type(errno)is str and errno in TRANSPORT_ERRNOS)or not(count is None or type(count)is int and 0<=count<=9007199254740991):raise ValueError('xhs_media_failure_diagnostic_invalid')
 if (set(value)!=keys
     or version not in ('crowd-xhs-media-failure-v1','crowd-xhs-media-failure-v2') or type(value['stage'])is not str
     or value['stage']not in ('head','get','stream','write','manager','unknown')
     or type(value['reason'])is not str or value['reason']not in FAILURE_REASONS
     or not(value['http_status']is None or type(value['http_status'])is int and 100<=value['http_status']<=599)):
  raise ValueError('xhs_media_failure_diagnostic_invalid')
 return value

def record_node_failure(run,manifest,raw):
 """Finite metadata only. Original intent/partial files and budget remain intact."""
 from shared_request_budget import request_fingerprint
 from saved_media_attachments import safe_path
 run=safe_path(run)
 if len(raw)>2048:raise ValueError('xhs_media_failure_diagnostic_invalid')
 def unique(pairs):
  result={}
  for k,v in pairs:
   if k in result:raise ValueError('xhs_media_failure_diagnostic_invalid')
   result[k]=v
  return result
 value=_failure_shape(json.loads(raw,object_pairs_hook=unique))
 if manifest.get('run_id')!=run.name or str(uuid.UUID(run.name))!=run.name:raise ValueError('xhs_media_failure_scope_invalid')
 record={**value,'run_id':run.name,'request_hash':request_fingerprint(manifest['request'])}
 fd=os.open(run/'pro-xhs-media-failure.json',os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_WRONLY,0o600)
 with os.fdopen(fd,'w')as f:json.dump(record,f,separators=(',',':'));f.flush();os.fsync(f.fileno())
 directory=os.open(run,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
 try:os.fsync(directory)
 finally:os.close(directory)
 return record

def read_failure(run,manifest):
 from shared_request_budget import request_fingerprint
 from saved_media_attachments import safe_path,read_json_object
 run=safe_path(run);p=run/'pro-xhs-media-failure.json'
 if not p.exists()and not p.is_symlink():return None
 p=safe_path(p,run);info=p.stat()
 if info.st_uid!=os.getuid()or info.st_mode&0o077 or info.st_nlink!=1:raise ValueError('xhs_media_failure_diagnostic_invalid')
 value=read_json_object(p,2048)
 if (value.get('run_id')!=run.name or manifest.get('run_id')!=run.name
     or value.get('request_hash')!=request_fingerprint(manifest['request'])):raise ValueError('xhs_media_failure_scope_invalid')
 _failure_shape({k:v for k,v in value.items()if k not in ('run_id','request_hash')})
 return value

def execute_payload(payload,*,launch=None):
 """Explicit own child entry. Tests may inject transport, main has no such flag."""
 from mc_runner import read,write
 from shared_request_budget import request_fingerprint,RunRequestBudget
 from saved_media_attachments import safe_path
 run=safe_path(payload['run']);manifest=read(run/'manifest.json');request=manifest['request']
 if payload.get('request_hash')!=request_fingerprint(request) or payload.get('headers')!={}:raise ValueError('xhs_media_request_mismatch')
 items=plan(run,manifest);rows=__import__('pro_executor').observations(run,manifest)
 expected_topics=[row for kind,_,row in rows if kind=='topic']
 if payload.get('note')!=expected_topics or payload.get('response')!={'xhs_plan_sha256':digest(items)}:raise ValueError('xhs_media_source_changed')
 binding=dependency_binding(run.parent.parent);context=identity(run,manifest)
 intent={'run_id':manifest['run_id'],'request_hash':payload['request_hash'],'plan':items,'identity':context,'dependency_binding_sha256':binding['binding_sha256'],'retry_unknown_forbidden':True,'transport_policy':TRANSPORT_POLICY}
 fd=os.open(run/'xhs-pro-media-intent.json',os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_WRONLY,0o600)
 with os.fdopen(fd,'w') as f:json.dump(intent,f);f.flush();os.fsync(f.fileno())
 check_context(run,manifest,intent)
 folder=run/'output/xhs/media';safe_path(folder);folder.mkdir(parents=True,exist_ok=True)
 if any(folder.rglob('*')):raise ValueError('xhs_media_output_exists')
 if not items:assets=[]
 elif launch is None:
  from portable_node import check
  node=check(Path.home()/'Library/Application Support/CrowdV4Updater')
  driver=Path(__file__).with_name('pro_xhs_download.mjs')
  command=[str(node),'--experimental-vm-modules',str(driver)]
  env=os.environ.copy()
  for name in ('NODE_OPTIONS','NODE_PATH','PYTHONHOME'):env.pop(name,None)
  own={'run':str(run),'root':str(folder),'items':items,'binding':binding,'identity':context,'python':sys.executable,'guard_module':str(Path(__file__).resolve()),'timeout':min(30000,int(request['timeout_seconds']*1000))}
  done=subprocess.run(command,input=json.dumps(own).encode(),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env=env,timeout=request['timeout_seconds'])
  if done.returncode in (73,74):raise SystemExit(done.returncode)
  if done.returncode!=0:
   if done.returncode==87:record_node_failure(run,manifest,done.stdout)
   raise ValueError('xhs_media_failed_or_unknown')
  if len(done.stdout)>1048576:raise ValueError('xhs_media_failed_or_unknown')
  assets=json.loads(done.stdout)
 else:assets=launch(items,folder)
 check_context(run,manifest,intent);assets=verify_assets(run,manifest,assets)
 ledger=RunRequestBudget(run/'request-budget.json',manifest['run_id'],payload['request_hash'],request['max_api_requests'])
 result={'schema_version':1,'run_id':manifest['run_id'],'request_hash':payload['request_hash'],'state':'completed','assets':assets,'subtitle_available':False,'api_attempts':ledger.snapshot()['used'],'cloud_ack':False,'content_engine':'mediacrawler_pro','media_engine':ENGINE}
 write(run/'hybrid-media-result.json',result);return result

def summary(run,manifest,value):
 from mc_runner import read
 from shared_request_budget import RunRequestBudget,request_fingerprint
 intent=read(Path(run)/'xhs-pro-media-intent.json')
 if intent.get('plan')!=plan(run,manifest) or intent.get('request_hash')!=request_fingerprint(manifest['request']) or intent.get('run_id')!=manifest['run_id']:raise ValueError('xhs_media_source_changed')
 assets=verify_assets(run,manifest,value.get('assets'))
 ledger=RunRequestBudget(Path(run)/'request-budget.json',manifest['run_id'],request_fingerprint(manifest['request']),manifest['request']['max_api_requests'])
 if assets!=value['assets'] or value.get('api_attempts')!=ledger.snapshot()['used'] or value.get('state')!='completed':raise ValueError('xhs_media_result_changed')
 return value

if __name__=='__main__':
 try:
  raw=sys.stdin.buffer.read(131073)
  if len(raw)>131072:raise ValueError('xhs_media_guard_input_invalid')
  if len(sys.argv)==3 and sys.argv[1]=='--guard':guard(Path(sys.argv[2]),json.loads(raw));print('ok')
  elif len(sys.argv)==1:
   from bili_media_child import install_watchdog
   payload=json.loads(raw);run=Path(payload['run']);manifest=json.loads((run/'manifest.json').read_text());os.chdir(run)
   stopped=install_watchdog(run,manifest['request'])
   try:execute_payload(payload)
   finally:stopped.set()
  else:raise ValueError('xhs_media_args_invalid')
 except SystemExit:raise
 except BaseException:raise SystemExit(87) from None
