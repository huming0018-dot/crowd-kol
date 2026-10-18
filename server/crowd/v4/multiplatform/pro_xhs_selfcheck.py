"""Existing Pro official-self check only; never authorizes or resumes collection."""
import asyncio,contextlib,fcntl,io,json,os,re,stat,subprocess,sys,time,uuid
from pathlib import Path
from urllib.parse import urlsplit

class CheckFailure(BaseException):
 def __init__(self,code):self.code=code
class Quiet(io.TextIOBase):
 def write(self,value):return len(value)
 def flush(self):pass
CODES={'authenticated_same_account','official_logged_out','official_check_failed','account_changed','account_context_changed','bridge_unavailable','signer_unavailable','transport_error','endpoint_forbidden','request_budget_exhausted','response_too_large','redirect_forbidden','check_cancelled','check_timeout','verification_failed'}

def receipt(path,value):
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'w',encoding='utf-8') as stream:json.dump(value,stream);stream.flush();os.fsync(stream.fileno())

def context(store,sid):
 from account_sessions import identifier
 value=store.status(sid,'xhs')
 generation=value.get('generation');ref=value.get('account_ref');pending=value.get('pending_run_id')
 if type(generation) is not int or generation<1 or type(ref) is not str or not re.fullmatch('[a-f0-9]{64}',ref):raise ValueError('self_check_identity_unverified')
 if pending is not None:identifier(pending)
 return {'generation':generation,'account_ref':ref,'pending_run_id':pending}

def publish(store,sid,expected,diagnostic):
 def change(value):
  if any(type(value.get(k)) is not type(v) or value.get(k)!=v for k,v in expected.items()):raise ValueError('self_check_account_changed')
  value['last_self_check']=diagnostic
 return store._update(sid,'xhs',change)

def launch(store,sid):
 from pro_executor import task_installation,binding_for
 request={'platform':'xhs','session_id':sid,'source_executor':'pro'}
 installed=task_installation(store.collector_root,request);bound=binding_for(store.collector_root,request)
 if bound.get('provider') is not None:raise ValueError('pro_self_check_unsupported')
 session,_=store._session(sid,'xhs');fd=os.open(session/'active.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
 try:
  info=os.fstat(fd)
  if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1:raise ValueError('session_busy')
  try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise ValueError('session_busy') from None
  expected=context(store,sid)
  # Holding the original active lock proves no previous verification/source worker owns it.
  # A new explicit check-only action may replace an abandoned display, never its evidence.
  base=Path(store.collector_root)/'self-checks'
  if base.is_symlink():raise ValueError('invalid_self_check_path')
  base.mkdir(exist_ok=True,mode=0o700);operation=base/str(uuid.uuid4());operation.mkdir(mode=0o700)
  diagnostic={'method':'pro_official_self','check_only':True,'phase':'checking','operation_id':operation.name,'bridge_requests':0,'signer_requests':0,'official_self_requests':0,'source_collection_started':False,'started_at':time.time(),'deadline_at':time.time()+40}
  receipt(operation/'intent.json',diagnostic)
  publish(store,sid,expected,diagnostic)
  command=[installed['python'],'-B',str(Path(__file__).with_name('pro_login_recovery.py')),'--root',str(store.collector_root),'--session-id',sid,'--lock-fd',str(fd),'--xhs-check-only']
  try:
   child=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,pass_fds=(fd,),start_new_session=True,env={**os.environ,'ENABLE_LOG_FILE':'false','PYTHONDONTWRITEBYTECODE':'1'})
  except OSError:
   publish(store,sid,expected,{**diagnostic,'phase':'failed','reason':'verification_failed'});raise ValueError('self_check_start_failed') from None
  receipt(operation/'worker.json',{'worker_pid':child.pid,'deadline_at':diagnostic['deadline_at']})
  try:child.stdin.write(json.dumps({'installed':installed,'expected':expected,'operation':str(operation)}).encode());child.stdin.close()
  except (OSError,BrokenPipeError):raise ValueError('self_check_outcome_unknown') from None
  return {'ok':True,'session_id':sid,'check_only':True,'source_collection_started':False,'browser_started':False,'operation_id':operation.name}
 finally:os.close(fd)

async def verify(store,sid,expected,installed,diagnostic,*,operation=None):
 from account_sessions import safe_account_ref
 from pro_executor import binding_for,install_bound_account,probe
 from pro_account_sessions import self_proof
 def current():
  if context(store,sid)!=expected:raise CheckFailure('account_context_changed')
  marker=Path(operation)/'stop' if operation is not None else None
  if marker is not None and (marker.exists() or marker.is_symlink()):raise CheckFailure('check_cancelled')
 current();bound=binding_for(store.collector_root,{'platform':'xhs','session_id':sid})
 if bound.get('provider') is not None:raise CheckFailure('bridge_unavailable')
 probe(installed['root']);sys.path.insert(0,installed['root']);os.environ['ENABLE_LOG_FILE']='false'
 with contextlib.redirect_stdout(Quiet()),contextlib.redirect_stderr(Quiet()):
  import config
  config.SIGN_SRV_HOST='127.0.0.1';config.SIGN_SRV_PORT='8990';config.ENABLE_LOG_FILE=False
  import httpx
  from pkg.tools import utils
  utils.logger.remove()
  from pkg.account_pool.pool import AccountPoolManager,AccountWithIpPoolManager
  from pkg.rpc.sign_srv_client import SignServerClient
  from media_platform.xhs.client import XiaoHongShuClient
  old_init,old_send=httpx.AsyncClient.__init__,httpx.AsyncClient.send
  old_loader=AccountPoolManager.load_accounts_from_cookie_bridge;old_sign=SignServerClient.request
  proof=('check_failed',None)
  def init(client,*a,**kw):
   if kw.get('proxy') is not None or kw.get('proxies') is not None:raise CheckFailure('endpoint_forbidden')
   kw.update(trust_env=False,follow_redirects=False,timeout=10,transport=httpx.AsyncHTTPTransport(retries=0,trust_env=False));return old_init(client,*a,**kw)
  async def send(client,request,*a,**kw):
   nonlocal proof
   current();u=urlsplit(str(request.url));b=urlsplit(bound['cookiebridge_url']);s=urlsplit(bound['sign_url'])
   if u.username or u.password or u.fragment:raise CheckFailure('endpoint_forbidden')
   bridge=request.method=='GET' and (u.scheme,u.hostname,u.port,u.path)==(b.scheme,b.hostname,b.port,b.path.rstrip('/')+'/api/cookies/xhs') and list(request.url.params.multi_items())==[('client_id',bound['client_id'])]
   sign=request.method=='POST' and (u.scheme,u.hostname,u.port,u.path)==(s.scheme,s.hostname,s.port,'/signsrv/v1/xhs/sign') and not u.query
   official=request.method=='GET' and u.scheme=='https' and u.hostname=='edith.xiaohongshu.com' and u.port in (None,443) and u.path=='/api/sns/web/v2/user/me' and not u.query
   kind='bridge' if bridge else 'signer' if sign else 'official_self' if official else None
   if kind is None:raise CheckFailure('endpoint_forbidden')
   if sign and diagnostic['bridge_requests']!=1 or official and diagnostic['signer_requests']!=1:raise CheckFailure('endpoint_forbidden')
   key=kind+'_requests'
   if diagnostic[key]>=1:raise CheckFailure('request_budget_exhausted')
   if sign:
    try:body=json.loads(request.content)
    except (ValueError,UnicodeError):raise CheckFailure('endpoint_forbidden') from None
    if not isinstance(body,dict) or body.get('uri')!='/api/sns/web/v2/user/me' or body.get('data') is not None:raise CheckFailure('endpoint_forbidden')
   diagnostic[key]+=1;kw.update(follow_redirects=False,stream=True)
   try:response=await old_send(client,request,*a,**kw)
   except httpx.RequestError:raise CheckFailure('transport_error') from None
   diagnostic[kind+'_http_status']=response.status_code
   try:
    if 300<=response.status_code<400:raise CheckFailure('redirect_forbidden')
    data=bytearray()
    async for chunk in response.aiter_bytes():
     data.extend(chunk)
     if len(data)>262144:raise CheckFailure('response_too_large')
    response._content=bytes(data)
   finally:await response.aclose()
   current()
   if official:proof=self_proof('xhs',response)
   return response
  async def sign_request(client,method,uri,**kw):
   if method!='POST' or uri!='/signsrv/v1/xhs/sign' or set(kw)!={'json'}:raise CheckFailure('endpoint_forbidden')
   async with httpx.AsyncClient() as session:
    response=await session.post(bound['sign_url']+uri,json=kw['json'])
    if response.status_code!=200:raise CheckFailure('signer_unavailable')
    try:return response.json()
    except (ValueError,UnicodeError):raise CheckFailure('signer_unavailable') from None
  httpx.AsyncClient.__init__,httpx.AsyncClient.send=init,send;SignServerClient.request=sign_request
  try:
   install_bound_account(AccountPoolManager,bound,'xhs',httpx)
   pool=AccountWithIpPoolManager('xhs','cookie_bridge',proxy_ip_pool=None);await pool.load_accounts_from_cookie_bridge()
   client=XiaoHongShuClient(account_with_ip_pool=pool);client.account_info=await pool.get_account_with_ip_info()
   method=XiaoHongShuClient.query_self
   if hasattr(method,'__wrapped__'):raise CheckFailure('official_check_failed')
   try:await method(client)
   except Exception:
    raise CheckFailure('official_check_failed' if diagnostic['official_self_requests'] else 'signer_unavailable') from None
  finally:
   httpx.AsyncClient.__init__,httpx.AsyncClient.send=old_init,old_send;SignServerClient.request=old_sign;AccountPoolManager.load_accounts_from_cookie_bridge=old_loader
 current()
 if any(diagnostic[k+'_requests']!=1 for k in ('bridge','signer','official_self')):return 'official_check_failed'
 if proof[0]=='logged_out':return 'official_logged_out'
 if proof[0]!='authenticated':return 'official_check_failed'
 return 'authenticated_same_account' if safe_account_ref('xhs',proof[1])==expected['account_ref'] else 'account_changed'

def worker(args):
 from account_sessions import AccountSessions
 from managed_pro_signer import owned_signer,SignerError
 store=AccountSessions(args.root);diagnostic={'method':'pro_official_self','check_only':True,'phase':'checking','bridge_requests':0,'signer_requests':0,'official_self_requests':0,'source_collection_started':False};payload=None;operation=None
 try:
  payload=json.loads(sys.stdin.buffer.read(32769))
  if not isinstance(payload,dict) or set(payload)!={'installed','expected','operation'} or not isinstance(payload['expected'],dict):raise CheckFailure('verification_failed')
  if context(store,args.session_id)!=payload['expected']:raise CheckFailure('account_context_changed')
  operation=Path(payload['operation'])
  if operation.parent!=Path(store.collector_root)/'self-checks' or str(uuid.UUID(operation.name))!=operation.name or operation.is_symlink():raise CheckFailure('verification_failed')
  diagnostic['operation_id']=operation.name
  bound=__import__('pro_executor').binding_for(store.collector_root,{'platform':'xhs','session_id':args.session_id})
  with owned_signer(operation,{'platform':'xhs','timeout_seconds':25},bound):
   code=asyncio.run(asyncio.wait_for(verify(store,args.session_id,payload['expected'],payload['installed'],diagnostic,operation=operation),25))
 except BaseException as error:
  code=error.code if isinstance(error,CheckFailure) and error.code in CODES else 'bridge_unavailable' if isinstance(error,SystemExit) and error.code==86 else 'signer_unavailable' if isinstance(error,SignerError) else 'check_timeout' if isinstance(error,TimeoutError) else 'verification_failed'
 finally:
  try:
   if isinstance(payload,dict) and operation is not None:
    result={**diagnostic,'phase':'completed' if code=='authenticated_same_account' else 'failed','reason':code,'checked_at':time.time()}
    receipt(operation/'result.json',result)
    publish(store,args.session_id,payload['expected'],result)
  finally:os.close(args.lock_fd)
