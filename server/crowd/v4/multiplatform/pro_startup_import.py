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
 for name in ('pro-observations.sqlite3','pro-observations.sqlite3-wal','pro-observations.sqlite3-shm','normalized.json','sign-service-intent.json','sign-service-lifecycle.jsonl','native-credential-intent.json','pro-pagination.json','pro-media-result.json','source-reuse.sqlite3','public-source-seed.json','source_reuse'):
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
