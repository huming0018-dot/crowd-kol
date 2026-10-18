"""Borrow an explicitly bound Bili CDP context; never launch a browser or profile.
Cookie bytes cross only the inherited private credential pipe. Official UID proof
is still mandatory in the caller; this component never authenticates an account.
"""
import asyncio,contextlib,fcntl,json,os,re,stat,sys,threading,signal
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import pro_native_credentials as native
from browser_session import validate_binding,connect_context,BrowserSessionError
from account_sessions import AccountSessions

URL='https://www.bilibili.com/'

def context_for(root,session_id,expected):
 if (type(expected) is not dict or set(expected)!={'generation','account_ref','run_id','browser_connection'}
     or type(expected['generation']) is not int or expected['generation']<1
     or not isinstance(expected['account_ref'],str) or not re.fullmatch('[a-f0-9]{64}',expected['account_ref'])
     or not isinstance(expected['run_id'],str) or not re.fullmatch('[a-f0-9-]{36}',expected['run_id'])):
  raise native.CredentialError('native_provider_session_invalid')
 try:
  binding=validate_binding(expected['browser_connection'],'bili')
  if binding['selection_kind']!='platform_page':raise ValueError()
  value=AccountSessions(root).status(session_id,'bili')
  if (type(value) is not dict or type(value.get('generation')) is not int
      or value['generation']!=expected['generation'] or value.get('account_ref')!=expected['account_ref']
      or value.get('pending_run_id')!=expected['run_id'] or value.get('state')=='account_changed'
      or value.get('browser_connection')!=binding):raise ValueError()
 except (ValueError,TypeError,KeyError,AttributeError,RecursionError):
  raise native.CredentialError('native_provider_session_invalid') from None
 return dict(binding)

def expected_from_state(root,session_id,pending_run_id=None):
 value=AccountSessions(root).status(session_id,'bili')
 if type(value) is not dict:raise native.CredentialError('native_provider_session_invalid')
 expected={key:value.get(key) for key in ('generation','account_ref','browser_connection')}
 expected['run_id']=value.get('pending_run_id') if pending_run_id is None else pending_run_id
 context_for(root,session_id,expected)
 return expected

class DiagnosticSink:
 def __init__(self,value):self.value=value
 def update(self,**value):
  reason=value.get('credential_reason')
  if type(reason) is str and reason in native.SAFE_ERRORS:self.value.update(credential_provider='existing_cdp',credential_reason=reason)

def cookie_string(rows):
 if type(rows) is not list or not rows or len(rows)>200:raise native.CredentialError('native_provider_cookie_shape_invalid')
 pairs=[];names=set()
 for row in rows:
  if type(row) is not dict or not isinstance(row.get('domain'),str) or row['domain'].lstrip('.').lower() not in ('bilibili.com','www.bilibili.com'):
   raise native.CredentialError('native_provider_cookie_scope_invalid')
  for key in ('name','value'):
   if not isinstance(row.get(key),str) or not row[key] or any(ord(c)<32 or ord(c)==127 or c==';' for c in row[key]):raise native.CredentialError('native_provider_cookie_shape_invalid')
  if '=' in row['name'] or row['name'] in names:raise native.CredentialError('native_provider_cookie_shape_invalid')
  names.add(row['name']);pairs.append(row['name']+'='+row['value'])
 return native.validate_credentials({'schema':native.schema_for('bili'),'cookies':'; '.join(pairs)},'bili')

async def collect_bound_context(root,session_id,expected):
 binding=context_for(root,session_id,expected)
 from playwright.async_api import async_playwright
 async with async_playwright() as manager:
  try:
   context=await connect_context(manager.chromium,binding,'bili')
   context_for(root,session_id,expected)
   rows=await asyncio.wait_for(context.cookies(urls=[URL]),5)
   context_for(root,session_id,expected)
   return cookie_string(rows)
  except asyncio.CancelledError:raise
  except (BrowserSessionError,asyncio.TimeoutError):raise native.CredentialError('native_provider_browser_unavailable') from None
 # Manager owns only its transport. Never call browser.close/context.close.

async def read_credentials(root,session_id,mc_root,expected,*,timeout=25):
 if type(timeout) not in (int,float) or not 1<=timeout<=30:raise native.CredentialError('native_provider_timeout_invalid')
 context_for(root,session_id,expected) # Reject unbound metadata before any child.
 from account_sessions import identifier
 identifier(session_id);root=native.safe_path(root);mc=native.safe_path(mc_root);python=mc/'.venv/bin/python'
 if not python.is_file():raise native.CredentialError('native_provider_python_missing')
 lockpath=root/'accounts'/session_id/'state.lock'
 fd=os.open(lockpath,os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK)
 try:
  info=os.fstat(fd)
  if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1 or stat.S_IMODE(info.st_mode)&0o022:raise native.CredentialError('native_provider_lock_invalid')
  try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise native.CredentialError('native_provider_busy') from None
  context_for(root,session_id,expected)
  value=await native.read_private_credentials(python,Path(__file__).resolve(),{'root':str(root),'session_id':session_id,'expected':expected},timeout=timeout,platform='bili')
  context_for(root,session_id,expected)
  return value
 finally:os.close(fd)

def install_cdp_account(pool_class,root,session_id,mc_root,expected,*,run=None,sink=None):
 attempted=False
 async def load(pool):
  nonlocal attempted
  if pool._platform_name!='bili':raise SystemExit(78)
  try:
   if attempted:raise native.CredentialError('native_provider_retry_forbidden')
   attempted=True;context_for(root,session_id,expected)
   if run is not None:
    folder=native.safe_path(run)
    fd=os.open(folder/'cdp-credential-intent.json',os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:json.dump({'schema':'crowd-existing-cdp-intent-v1','provider':'existing_cdp','session_id':session_id,'run_id':folder.name,'pending_run_id':expected['run_id'],'retry_unknown_forbidden':True},stream);stream.flush();os.fsync(stream.fileno())
   cookie=await read_credentials(root,session_id,mc_root,expected)
  except asyncio.CancelledError:raise
  except (native.CredentialError,OSError,asyncio.TimeoutError) as error:
   reason=str(error) if isinstance(error,native.CredentialError) and str(error) in native.SAFE_ERRORS else 'native_provider_unavailable'
   if sink is not None:
    with contextlib.suppress(Exception):sink.update(phase='failed',failure_reason='pro_existing_cdp_credentials_unavailable',credential_provider='existing_cdp',credential_reason=reason)
   raise SystemExit(86) from None
  from pkg.account_pool.pool import AccountInfoModel,AccountStatusEnum
  pool.add_account(AccountInfoModel(id=1,account_name='existing-cdp-original-bili-session',cookies=cookie,status=AccountStatusEnum.NORMAL.value,platform_name='bili'))
 pool_class.load_accounts_from_cookie_bridge=load

def child_main(fd):
 parent=os.getppid();finished=threading.Event()
 def watch():
  while not finished.wait(.5):
   if os.getppid()!=parent:
    if os.getpgrp()==os.getpid():os.killpg(os.getpid(),signal.SIGKILL)
    os._exit(86)
 threading.Thread(target=watch,daemon=True).start()
 try:
  request=json.loads(sys.stdin.buffer.read(16385))
  if type(request) is not dict or set(request)!={'root','session_id','expected'}:raise native.CredentialError('native_provider_protocol_invalid')
  cookie=asyncio.run(asyncio.wait_for(collect_bound_context(**request),20))
  with os.fdopen(fd,'wb') as stream:stream.write(json.dumps({'schema':native.schema_for('bili'),'cookies':cookie}).encode())
  return 0
 except BaseException as error:
  reason=str(error) if isinstance(error,native.CredentialError) and str(error) in native.SAFE_ERRORS else 'native_provider_unavailable'
  with contextlib.suppress(OSError):os.write(fd,json.dumps({'reason':reason}).encode())
  return 86
 finally:finished.set()

if __name__=='__main__':
 if len(sys.argv)!=3 or sys.argv[1]!='_credential_child':raise SystemExit(86)
 raise SystemExit(child_main(int(sys.argv[2])))
