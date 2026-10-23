"""Read-only proof of a precise failed-before-source startup. Never repair a run."""
import json,os,stat,sqlite3,contextlib,hashlib
from pathlib import Path
REASON='pro_signer_wrapper_changed'
def small(path,limit=1048576):
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 try:
  s=os.fstat(fd)
  if not stat.S_ISREG(s.st_mode) or s.st_size>limit:raise ValueError('startup_evidence_unsafe')
  raw=os.read(fd,limit+1)
  if len(raw)>limit:raise ValueError('startup_evidence_unsafe')
  v=json.loads(raw)
  if not isinstance(v,dict):raise ValueError('startup_evidence_shape')
  return v
 finally:os.close(fd)
def failed_before_source(run,manifest,status):
 media=media_failed_before_source(run,manifest,status)
 if media is not None:return media
 if status.get('failure_reason')!=REASON:return None
 run=Path(run)
 if any(p.is_symlink() for p in (run,*run.parents)):raise ValueError('startup_evidence_unsafe')
 request=manifest.get('request',{})
 if (manifest.get('executor',{}).get('backend')!='pro' or request.get('source_executor')!='pro'
     or manifest.get('run_id')!=run.name or status.get('run_id')!=run.name
     or status.get('state')!='failed' or type(status.get('exit_code')) is not int or status['exit_code']!=86
     or type(status.get('api_attempts')) is not int or status['api_attempts']!=0
     or any(k in obj for obj in (manifest,request) for k in ('continuation','source_continuation'))):raise ValueError('startup_failure_unproven')
 phase=small(run/'phase.json')
 if phase.get('failure_reason')!=REASON or phase.get('phase')!='failed' or type(phase.get('api_attempts')) is not int or phase['api_attempts']!=0:raise ValueError('startup_failure_unproven')
 for name in ('pro-observations.sqlite3','pro-observations.sqlite3-wal','pro-observations.sqlite3-shm','normalized.json','sign-service-intent.json','sign-service-lifecycle.jsonl','native-credential-intent.json','pro-pagination.json','pro-media-result.json','hybrid-media-result.json','hybrid-media-dispatch.json','mc-source-steps.sqlite3-wal','mc-source-steps.sqlite3-shm','source-reuse.sqlite3','public-source-seed.json','source_reuse'):
  p=run/name
  if p.exists() or p.is_symlink():raise ValueError('startup_source_evidence_present')
 output=run/'output'
 if not output.is_dir() or output.is_symlink() or any(output.iterdir()):raise ValueError('startup_source_evidence_present')
 b=small(run/'request-budget.json',16384)
 canon=json.dumps(request,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)
 if (set(b)!={'schema','run_id','request_hash','limit','used','stages'} or b['schema']!='crowd-shared-request-budget-v1' or b['run_id']!=run.name
     or b['request_hash']!=hashlib.sha256(canon.encode()).hexdigest() or type(b['used']) is not int or b['used']!=0 or b['stages']!=[]
     or type(b['limit']) is not int or b['limit']!=request.get('max_api_requests')):raise ValueError('startup_budget_unproven')
 db=run/'mc-source-steps.sqlite3'
 if db.is_symlink() or not db.is_file() or db.stat().st_size>1048576:raise ValueError('startup_monitor_unproven')
 with contextlib.closing(sqlite3.connect(db.as_uri()+'?mode=ro',uri=True,timeout=.02)) as c:
  c.execute('PRAGMA query_only=ON')
  if c.execute('SELECT run,platform FROM binding').fetchall()!=[(run.name,request['platform'])] or c.execute('SELECT count(*) FROM events').fetchone()[0]!=0:raise ValueError('startup_monitor_unproven')
 return {'schema':'crowd_mc_import_v1','run_id':run.name,'source_kind':'mediacrawler_api','reward_eligible':False,'source':manifest.get('source'),'records':[],'media':[],'artifacts':[],'files':[],'rejected_records':0,'coverage':'not_started','run_state':'failed','failure_reason':REASON,'pro_acquisition':{'coverage':'not_started','committed':False,'startup_failure_verified':True},'summary':{'records':0,'contents':0,'comments':0,'dynamics':0,'media_files':0,'rejected_records':0,'coverage':'not_started'}}

def media_failed_before_source(run,manifest,status):
 """The new finite pre-SDK witness cannot certify or repair a historical run."""
 import fcntl,uuid
 from shared_request_budget import canonical,request_fingerprint
 run=Path(run);witness=run/'pro-media-preflight.json'
 if not witness.exists() and not witness.is_symlink():return None
 if any(p.is_symlink() for p in (run,*run.parents)):raise ValueError('media_preflight_unsafe')
 request=manifest.get('request',{});rid=manifest.get('run_id')
 if (type(rid)is not str or str(uuid.UUID(rid))!=rid or rid!=run.name
     or manifest.get('executor',{}).get('backend')!='pro' or request.get('source_executor')!='pro'
     or request.get('platform')!='xhs' or request.get('media')is not True
     or any(k in obj for obj in (manifest,request)for k in ('continuation','source_continuation'))):
  raise ValueError('media_preflight_scope_invalid')
 session_id=request.get('session_id')
 if type(session_id)is not str or str(uuid.UUID(session_id))!=session_id:raise ValueError('media_preflight_scope_invalid')
 lock=run.parent.parent/'sessions'/session_id/'active.lock'
 if any(p.is_symlink() for p in (lock,*lock.parents)):raise ValueError('media_preflight_unsafe')
 fd=os.open(lock,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 try:
  info=os.fstat(fd)
  if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:raise ValueError('media_preflight_unsafe')
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  fd2=os.open(witness,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
  try:
   before=os.fstat(fd2);raw=os.read(fd2,16385);after=os.fstat(fd2)
   if (not stat.S_ISREG(before.st_mode) or before.st_uid!=os.getuid() or before.st_mode&0o077
       or before.st_nlink!=1 or before.st_size>16384 or len(raw)!=before.st_size
       or (before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns)):
    raise ValueError('media_preflight_unsafe')
  finally:os.close(fd2)
  value=json.loads(raw)
  pairs={'media_binding':'media_dependency_unavailable','node_import':'portable_node_unavailable','node_resource':'node_resource_unavailable'}
  if (type(value)is not dict or set(value)!={'schema','run_id','request_hash','executor','platform','stage','state','reason','source_started','api_attempts'}
      or canonical(value).encode()!=raw or value['schema']!='crowd-pro-media-preflight-v1'
      or value['run_id']!=rid or value['request_hash']!=request_fingerprint(request)
      or value['executor']!='pro' or value['platform']!='xhs' or value['state']!='failed_before_source'
      or type(value['stage'])is not str or type(value['reason'])is not str or value['stage'] not in pairs or pairs[value['stage']]!=value['reason']
      or value['source_started']is not False or type(value['api_attempts'])is not int or value['api_attempts']!=0):
   raise ValueError('media_preflight_invalid')
  actual=small(run/'status.json')
  if (actual.get('run_id')!=rid or actual.get('state')!='failed'
      or type(actual.get('exit_code'))is not int or not -128<=actual['exit_code']<=255 or actual['exit_code']==0
      or actual.get('api_attempts')is not None or actual.get('api_requests')is not None
      or any(status.get(k)!=actual.get(k)for k in ('run_id','state','exit_code'))):
   raise ValueError('media_preflight_status_invalid')
  for name in ('pro-observations.sqlite3','pro-observations.sqlite3-wal','pro-observations.sqlite3-shm',
               'request-budget.json','phase.json','mc-source-steps.sqlite3','mc-source-steps.sqlite3-wal','mc-source-steps.sqlite3-shm','pro-pagination.json',
               'xhs-pro-media-intent.json','normalized.json','sign-service-intent.json','sign-service-lifecycle.jsonl',
               'native-credential-intent.json','pro-media-result.json','hybrid-media-result.json','hybrid-media-dispatch.json','source-reuse.sqlite3','public-source-seed.json','source_reuse'):
   p=run/name
   if p.exists() or p.is_symlink():raise ValueError('media_preflight_source_present')
  output=run/'output'
  if not output.is_dir() or output.is_symlink() or any(output.iterdir()):raise ValueError('media_preflight_source_present')
  return {'schema':'crowd_mc_import_v1','run_id':rid,'source_kind':'mediacrawler_api','reward_eligible':False,
          'source':manifest.get('source'),'records':[],'media':[],'artifacts':[],'files':[],
          'rejected_records':0,'coverage':'not_started','run_state':'failed','failure_reason':value['reason'],
          'media_preflight_verified':True,
          'pro_acquisition':{'coverage':'not_started','committed':False,'startup_failure_verified':True},
          'summary':{'records':0,'contents':0,'comments':0,'dynamics':0,'media_files':0,'rejected_records':0,'coverage':'not_started'}}
 finally:os.close(fd)
