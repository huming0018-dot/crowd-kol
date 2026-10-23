"""One durable pre-request budget across owned source/media processes; no URLs.
Same-FD locked bounded JSON is deliberately fail-closed after an interrupted write.
"""
import contextlib,fcntl,hashlib,json,os,re,stat,uuid
from pathlib import Path
class BudgetError(ValueError):pass
def canonical(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)
def request_fingerprint(request):return hashlib.sha256(canonical(request).encode()).hexdigest()
def _object(pairs):
 result={}
 for key,value in pairs:
  if key in result:raise BudgetError('request_budget_invalid')
  result[key]=value
 return result
class RunRequestBudget:
 def __init__(self,path,run_id,request_hash,limit,create=False):
  self.path=Path(path);self.run_id=run_id;self.hash=request_hash;self.limit=limit
  try:valid_uuid=isinstance(run_id,str) and str(uuid.UUID(run_id))==run_id
  except (ValueError,TypeError,AttributeError):valid_uuid=False
  if (not valid_uuid or not isinstance(request_hash,str)
      or not re.fullmatch('[a-f0-9]{64}',request_hash) or type(limit) is not int or not 1<=limit<=500
      or not self.path.is_absolute() or self.path.parent.is_symlink() or not self.path.parent.is_dir()):raise BudgetError('request_budget_binding_invalid')
  created=False
  if create:
   try:
    fd=os.open(self.path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_NONBLOCK,0o600);os.close(fd);created=True
   except FileExistsError:pass
   except OSError:raise BudgetError('request_budget_unavailable') from None
  self._access(initialize=created)
 def _validate(self,v):
  if (not isinstance(v,dict) or set(v)!={'schema','run_id','request_hash','limit','used','stages'}
      or v.get('schema')!='crowd-shared-request-budget-v1' or v.get('run_id')!=self.run_id
      or v.get('request_hash')!=self.hash or type(v.get('limit')) is not int or v['limit']!=self.limit
      or type(v.get('used')) is not int or not 0<=v['used']<=self.limit
      or not isinstance(v.get('stages'),list) or len(v['stages'])!=v['used']
      or any(s not in ('pro','media') for s in v['stages'])):raise BudgetError('request_budget_binding_invalid')
 def _access(self,stage=None,initialize=False):
  try:fd=os.open(self.path,os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK)
  except OSError:raise BudgetError('request_budget_unavailable') from None
  try:
   fcntl.flock(fd,fcntl.LOCK_EX)
   info=os.fstat(fd)
   if not stat.S_ISREG(info.st_mode) or info.st_mode&0o077 or info.st_uid!=os.getuid() or info.st_size>16384:raise BudgetError('request_budget_invalid')
   raw=os.read(fd,16385)
   if initialize:
    if raw:raise BudgetError('request_budget_invalid')
    value={'schema':'crowd-shared-request-budget-v1','run_id':self.run_id,'request_hash':self.hash,'limit':self.limit,'used':0,'stages':[]}
   else:
    try:value=json.loads(raw.decode(),object_pairs_hook=_object)
    except (ValueError,UnicodeError,RecursionError):raise BudgetError('request_budget_invalid') from None
   self._validate(value)
   if stage:
    if stage not in ('pro','media'):raise BudgetError('request_budget_stage_invalid')
    if value['used']>=self.limit:raise SystemExit(73)
    value['used']+=1;value['stages'].append(stage)
   if initialize or stage:
    data=canonical(value).encode();os.lseek(fd,0,os.SEEK_SET);offset=0
    while offset<len(data):
     count=os.write(fd,data[offset:])
     if not count:raise BudgetError('request_budget_write_failed')
     offset+=count
    os.ftruncate(fd,len(data));os.fsync(fd)
   return value
  except OSError:raise BudgetError('request_budget_unavailable') from None
  finally:os.close(fd)
 def debit(self,stage='pro'):
  if not isinstance(stage,str) or stage not in ('pro','media'):raise BudgetError('request_budget_stage_invalid')
  return self._access(stage=stage)['used']
 def snapshot(self):return self._access()

def install_hybrid_transport_limits(httpx,requests,aiohttp,request,sink,budget):
 """Reuse the existing response/identity guards and debit BEFORE each transport."""
 from pro_executor import install_transport_limits
 def debit():
  try:used=budget.debit('media')
  except SystemExit:
   sink.update(phase='stopping',failure_reason='api_request_limit');raise
  sink.attempts=used;sink.update();return used
 install_transport_limits(httpx,request,sink,debit_callback=debit)
 sync=requests.sessions.Session.request
 def request_send(self,*a,**kw):
  url=a[1] if len(a)>1 else kw.get('url')
  retry=getattr(self.get_adapter(url),'max_retries',None)
  total=getattr(retry,'total',None)
  if not (total is False or type(total) is int and total==0):raise BudgetError('request_budget_hidden_retry_forbidden')
  kw['allow_redirects']=False
  debit();response=sync(self,*a,**kw)
  status=getattr(response,'status_code',None)
  if type(status) is int and 300<=status<=399:raise BudgetError('request_budget_redirect_forbidden')
  return response
 requests.sessions.Session.request=request_send
 if aiohttp is not None:
  aio=aiohttp.ClientSession._request
  async def aio_send(self,*a,**kw):
   kw['allow_redirects']=False
   if hasattr(self,'_retry_connection'):self._retry_connection=False
   debit();response=await aio(self,*a,**kw)
   status=getattr(response,'status',None)
   if type(status) is int and 300<=status<=399:raise BudgetError('request_budget_redirect_forbidden')
   return response
  aiohttp.ClientSession._request=aio_send
