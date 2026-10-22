"""One durable readiness report stream, invoked only at the existing idle claim boundary.

Unknown writes reconcile through status only. No new scheduler, source or task.
The server TTL is not renewed by replay; local proof is rechecked every claim.
"""
from pathlib import Path
import datetime,hashlib,json,os,re,time,uuid
from cloud_sync import canonical,CloudError
from automatic_materials import private_json,write
from publication_pro_share import private_dir,create

REASONS={'ready','not_configured','dependency_unavailable','identity_unverified','login_in_progress','unsupported_scope','source_changed','preflight_failed'}
def need(ok):
 if not ok:raise ValueError('worker_capability_invalid')
def uid(value):
 try:need(type(value)is str and str(uuid.UUID(value))==value)
 except (TypeError,AttributeError):raise ValueError('worker_capability_invalid')from None
 return value
def report_hash(value):return hashlib.sha256(('crowd-machine-capability-report-v1\n'+canonical(value)).encode()).hexdigest()
def _time(value):
 need(type(value)is str)
 try:parsed=datetime.datetime.fromisoformat(value.replace('Z','+00:00'));need(parsed.tzinfo is not None);return parsed.timestamp()
 except (ValueError,OverflowError):raise ValueError('worker_capability_invalid')from None
def validate_sample(value,now):
 need(type(value)is dict and set(value)=={'observed_at_ms','host','state','reason_code','source_readiness'})
 observed=value['observed_at_ms'];need(type(observed)is int and int((now-120)*1000)<=observed<=int(now*1000))
 host=value['host'];need(type(host)is dict and set(host)=={'os','arch'}and type(host['os'])is str and host['os']in('darwin','linux','windows','android','ios','unknown')and type(host['arch'])is str and host['arch']in('arm64','x64','x86','unknown'))
 need(type(value['reason_code'])is str and value['reason_code']in REASONS and value['state']in('ready','not_ready')and type(value['source_readiness'])is list)
 if value['state']=='not_ready':need(value['reason_code']!='ready'and value['source_readiness']==[]);return
 need(value['reason_code']=='ready'and len(value['source_readiness'])==1 and host['os']in('darwin','linux'))
 s=value['source_readiness'][0];constants={'schema':'crowd-pro-source-readiness-v1','engine':'mediacrawler_pro','protocol':'vox-acquisition-v1','platform':'xhs','mode':'detail','scope':'xhs_detail_body_comments_v1','comments':True,'replies':True,'media':False,'max_items':1,'max_comments':200,'source_commit':'d32dd565277116ba4880c28ccd417a7c376cb62d','identity_basis':'cached_authenticated_self_id'}
 extra={'identity_verified_at_ms','session_generation','session_ref','binding_sha256'}
 need(type(s)is dict and set(s)==set(constants)|extra and all(type(s[k])is type(v)and s[k]==v for k,v in constants.items()))
 need(type(s['identity_verified_at_ms'])is int and 0<s['identity_verified_at_ms']<=observed and type(s['session_generation'])is int and s['session_generation']>=1)
 need(all(type(s[k])is str and re.fullmatch('[a-f0-9]{64}',s[k])is not None for k in('session_ref','binding_sha256')))
def receipt(value,report,worker=None):
 fields={'schema','worker_id','report_id','sequence','report_hash','received_at','expires_at','replayed'}
 need(type(value)is dict and set(value)==fields and value['schema']=='crowd-worker-capability-receipt-v1'and type(value['replayed'])is bool);uid(value['worker_id']);uid(value['report_id'])
 need(worker is None or value['worker_id']==worker);need(value['report_id']==report['report_id']and type(value['sequence'])is int and value['sequence']==report['sequence']and value['report_hash']==report_hash(report))
 received,expires=_time(value['received_at']),_time(value['expires_at']);need(received<expires<=min(received+120,report['observed_at_ms']/1000+120)+.001)
 return value
def status(value):
 need(type(value)is dict and set(value)=={'schema','worker_id','latest_sequence','latest_report_id','report_receipt'}and value['schema']=='crowd-worker-capability-status-v1');uid(value['worker_id']);need(type(value['latest_sequence'])is int and value['latest_sequence']>=0)
 if value['latest_sequence']==0:need(value['latest_report_id']is None and value['report_receipt']is None)
 else:uid(value['latest_report_id'])
 return value
def semantic(sample):return canonical({k:v for k,v in sample.items()if k!='observed_at_ms'})
def _write(path,value):
 write(path,value);fd=os.open(path.parent,os.O_RDONLY)
 try:os.fsync(fd)
 finally:os.close(fd)
class ReadinessReporter:
 def __init__(self,root,client,provider):
  self.root=private_dir(Path(root)/'capability-reports');self.path=self.root/'current.json';self.client,self.provider=client,provider
 def _load(self):
  if not self.path.exists():return None
  return private_json(self.path)
 def _record(self,row,answer):
  recorded={**row,'state':'recorded','receipt':answer}
  _write(self.path,recorded)
  # The state update is never acknowledged in memory before durable write.
  return recorded
 def current(self,now=None):
  sample=self.provider();now=time.time()if now is None else now;validate_sample(sample,now);row=self._load()
  if row is not None:
   need(type(row)is dict and row.get('state')in('attempted_no_retry','recorded'));report=row['report'];uid(report['report_id'])
   if row['state']=='attempted_no_retry':
    try:
     response=status(self.client.call('worker_capability_status',{'report_id':report['report_id']}));answer=receipt(response['report_receipt'],report,response['worker_id']);row=self._record(row,answer)
    except (CloudError,OSError,ValueError):return None
   answer=receipt(row['receipt'],report)
   # Local changed/failed proof invalidates old ready immediately, not after TTL.
   if semantic(sample)==semantic({k:report[k]for k in sample})and 0<=now-report['observed_at_ms']/1000<60 and now<_time(answer['expires_at']):return report['report_id']if sample['state']=='ready'else None
  # Recover server sequence on each new report, never guess after a restart or conflict.
  try:latest=status(self.client.call('worker_capability_status',{}))
  except (CloudError,OSError,ValueError):return None
  report={'schema':'crowd-worker-capabilities-v1','report_id':str(uuid.uuid4()),'sequence':latest['latest_sequence']+1,**sample};pending={'state':'attempted_no_retry','report':report}
  # Create a permanent original intent, then publish its pointer before the sole RPC.
  create(self.root/(report['report_id']+'.json'),pending)
  if self.path.exists():_write(self.path,pending)
  else:create(self.path,pending)
  try:
   answer=receipt(self.client.call('worker_capability_report',report),report,latest['worker_id']);self._record(pending,answer)
  except (CloudError,OSError,ValueError):return None
  return report['report_id']if sample['state']=='ready'and now<_time(answer['expires_at'])else None
 def matches(self,report_id,session_id,now=None):
  """Recheck selected local session immediately before the existing runner start."""
  sample=self.provider();now=time.time()if now is None else now;validate_sample(sample,now);row=self._load()
  if not row or row.get('state')!='recorded':return False
  report=row['report'];receipt(row['receipt'],report)
  return (report['report_id']==report_id and sample['state']=='ready'
          and semantic(sample)==semantic({k:report[k]for k in sample})
          and sample['source_readiness'][0]['session_ref']==hashlib.sha256(session_id.encode()).hexdigest())
