"""Bili Pro login-only official proof. No browser, source task, or credential persistence."""
import argparse,asyncio,contextlib,fcntl,io,json,os,stat,subprocess,sys
from pathlib import Path
from urllib.parse import urlsplit

class VerificationFailure(BaseException):
 def __init__(self,reason):self.reason=reason

class Quiet(io.TextIOBase):
 def write(self,value):return len(value)
 def flush(self):pass

def launch(store,session_id,platform,recovery):
 if platform!='bili':raise ValueError('pro_self_check_unsupported')
 from pro_executor import task_installation,binding_for
 request={'source_executor':'pro','platform':platform,'session_id':session_id}
 installed=task_installation(store.collector_root,request);binding_for(store.collector_root,request)
 session,_=store._session(session_id,platform)
 fd=os.open(session/'active.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
 try:
  if not stat.S_ISREG(os.fstat(fd).st_mode):raise ValueError('session_busy')
  try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise ValueError('session_busy') from None
  for marker in ('login-stop','login-verify-continue'):
   (store.root/session_id/marker).unlink(missing_ok=True)
  checked=store.observe(session_id,platform,'checking',run_id=recovery['run_id'],
      _expected_context={k:recovery[k] for k in ('generation','account_ref')})
  store._update(session_id,platform,lambda v:v.update(login_flow='pro_bound_official_self',
     login_page_ready=False,login_verification_paused=False,login_wait_reason='official_self_check',
     login_diagnostic={'method':'pro_official_self','phase':'checking','bridge_requests':0,'official_self_requests':0}))
  command=[installed['python'],str(Path(__file__).resolve()),'--root',str(store.collector_root),
     '--session-id',session_id,'--lock-fd',str(fd)]
  env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','ENABLE_LOG_FILE':'false'}
  child=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                         pass_fds=(fd,),start_new_session=True,env=env)
  try:child.stdin.write(json.dumps({'installed':installed,'recovery':recovery}).encode());child.stdin.close()
  except (BrokenPipeError,OSError):raise ValueError('pro_login_outcome_unknown') from None
  result=store._update(session_id,platform,lambda v:v.update(login_worker_pid=child.pid))
  return {**result,'source_collection_started':False,'browser_started':False}
 finally:os.close(fd)

async def verify(store,session_id,recovery,installed,diagnostic=None):
 """Called only inside isolated owned child; true SDK loader/pong, two fixed requests."""
 from account_sessions import safe_account_ref
 from pro_executor import binding_for,install_bound_account,probe
 from pro_account_sessions import self_proof
 if not isinstance(recovery,dict) or set(recovery)!={'run_id','generation','account_ref'}:
  raise VerificationFailure('invalid_context')
 expected={k:recovery[k] for k in ('generation','account_ref')}
 def cancelled():
  stop=store.root/session_id/'login-stop'
  if stop.exists() or stop.is_symlink():raise VerificationFailure('login_user_cancelled')
 cancelled()
 def baseline():
  d=store.status(session_id,'bili')
  return d.get('pending_run_id')==recovery['run_id'] and type(d.get('generation')) is int and d['generation']==expected['generation'] and d.get('account_ref')==expected['account_ref']
 if not baseline():raise VerificationFailure('account_context_changed')
 bound=binding_for(store.collector_root,{'platform':'bili','session_id':session_id})
 probe(installed['root']);sys.path.insert(0,installed['root'])
 os.environ['ENABLE_LOG_FILE']='false'
 counts={'bridge':0,'official_self':0};proof=('check_failed',None)
 diagnostic={} if diagnostic is None else diagnostic
 diagnostic.update(method='pro_official_self',phase='checking',bridge_requests=0,official_self_requests=0)
 with contextlib.redirect_stdout(Quiet()),contextlib.redirect_stderr(Quiet()):
  import httpx
  from pkg.tools import utils
  utils.logger.remove()
  from pkg.account_pool.pool import AccountPoolManager,AccountWithIpPoolManager
  from media_platform.bilibili.client import BilibiliClient
  old_init,old_send=httpx.AsyncClient.__init__,httpx.AsyncClient.send
  old_loader=AccountPoolManager.load_accounts_from_cookie_bridge
  def init(client,*a,**kw):
   if kw.get('proxy') is not None or kw.get('proxies') is not None:raise VerificationFailure('proxy_forbidden')
   kw.update(trust_env=False,follow_redirects=False,timeout=10)
   kw['transport']=httpx.AsyncHTTPTransport(retries=0)
   return old_init(client,*a,**kw)
  async def send(client,request,*a,**kw):
   nonlocal proof
   cancelled()
   u=urlsplit(str(request.url));b=urlsplit(bound['cookiebridge_url'])
   if request.method!='GET' or u.username or u.password or u.fragment:raise VerificationFailure('endpoint_forbidden')
   bridge=(u.scheme==b.scheme and u.hostname==b.hostname and u.port==b.port and u.path==b.path.rstrip('/')+'/api/cookies/bili'
           and list(request.url.params.multi_items())==[('client_id',bound['client_id'])])
   official=(u.scheme=='https' and u.hostname=='api.bilibili.com' and u.port in (None,443)
             and u.path=='/x/web-interface/nav' and not u.query)
   kind='bridge' if bridge else 'official_self' if official else None
   if kind is None or counts[kind]>=1:raise VerificationFailure('request_budget_exhausted')
   counts[kind]+=1;diagnostic[kind+'_requests']=counts[kind];kw['follow_redirects']=False;kw['stream']=True
   response=await old_send(client,request,*a,**kw)
   if type(response.status_code) is int and 100<=response.status_code<=599:diagnostic[kind+'_http_status']=response.status_code
   try:
    if 300<=response.status_code<400:raise VerificationFailure('redirect_forbidden')
    content=bytearray()
    async for chunk in response.aiter_bytes():
     content.extend(chunk)
     if len(content)>262144:raise VerificationFailure('response_too_large')
    response._content=bytes(content)
   finally:await response.aclose()
   try:
    safe_payload=response.json()
    key='biz_code' if bridge else 'code'
    code=safe_payload.get(key) if isinstance(safe_payload,dict) else None
    if type(code) is int and code in ((0,1,2,3,4,100,101,102,103) if bridge else (0,-101,-400,-403,-412)):
     diagnostic[kind+'_business_code']=code
   except (ValueError,UnicodeError,RecursionError):pass
   cancelled()
   if official:proof=self_proof('bili',response)
   return response
  httpx.AsyncClient.__init__,httpx.AsyncClient.send=init,send
  try:
   install_bound_account(AccountPoolManager,bound,'bili',httpx)
   pool=AccountWithIpPoolManager('bili','cookie_bridge',proxy_ip_pool=None)
   await pool.load_accounts_from_cookie_bridge()
   native=BilibiliClient(account_with_ip_pool=pool)
   native.account_info=await pool.get_account_with_ip_info()
   success=await native.pong()
  finally:
   httpx.AsyncClient.__init__,httpx.AsyncClient.send=old_init,old_send
   AccountPoolManager.load_accounts_from_cookie_bridge=old_loader
 if counts!={'bridge':1,'official_self':1} or success is not True or proof[0]!='authenticated':
  if proof[0]=='logged_out':store.observe(session_id,'bili','logged_out',recovery['run_id'],_expected_context=expected)
  raise VerificationFailure('official_logout' if proof[0]=='logged_out' else 'official_check_failed')
 cancelled()
 if safe_account_ref('bili',proof[1])!=expected['account_ref'] or not baseline():
  raise VerificationFailure('account_context_changed')
 result=store.observe(session_id,'bili','authenticated',run_id=recovery['run_id'],account_id=proof[1],_expected_context=expected)
 def success_cleanup(value):
  if (value.get('pending_run_id')!=recovery['run_id'] or value.get('authorized_for_run')!=recovery['run_id']
      or value.get('generation')!=expected['generation'] or value.get('account_ref')!=expected['account_ref']
      or value.get('state') not in ('authenticated','resumed')):return
  value.pop('login_wait_reason',None);value.pop('login_error_code',None)
  value.update(login_page_ready=False,login_verification_paused=False,
      login_diagnostic={**diagnostic,'phase':'authenticated','subject_present':True})
 store._update(session_id,'bili',success_cleanup)
 return result

def main():
 p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--session-id',required=True);p.add_argument('--lock-fd',required=True,type=int);a=p.parse_args()
 from account_sessions import AccountSessions
 store=AccountSessions(a.root);payload=None
 diagnostic={'method':'pro_official_self','phase':'checking','bridge_requests':0,'official_self_requests':0}
 try:
  payload=json.loads(sys.stdin.buffer.read(32769))
  asyncio.run(asyncio.wait_for(verify(store,a.session_id,payload['recovery'],payload['installed'],diagnostic),25))
 except BaseException as e:
  # Never echo raw SDK errors, URLs, cookies, response text, subject or account hashes.
  code=e.reason if isinstance(e,VerificationFailure) else 'bridge_unavailable' if isinstance(e,SystemExit) and e.code==86 else 'verification_failed'
  try:
   recovery=payload['recovery'];expected={k:recovery[k] for k in ('generation','account_ref')}
   if code!='official_logout':store.observe(a.session_id,'bili','check_failed',run_id=recovery['run_id'],_expected_context=expected)
   def failure_diagnostic(value):
    if (value.get('pending_run_id')!=recovery['run_id'] or value.get('generation')!=expected['generation']
        or value.get('account_ref')!=expected['account_ref'] or value.get('state') not in ('check_failed','logged_out')):return
    value.update(login_error_code='pro_login_verification_failed',login_wait_reason=code,
                 login_page_ready=False,login_diagnostic={**diagnostic,'phase':'failed'})
   store._update(a.session_id,'bili',failure_diagnostic)
  except (ValueError,TypeError,KeyError):pass  # Never overwrite another task's newer account context.
 finally:os.close(a.lock_fd)
if __name__=='__main__':main()
