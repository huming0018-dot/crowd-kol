"""WB/Zhihu/Bili original persistent context -> private pipe -> original Pro account pool.
No browser is launched on import. Never log or persist credential values.
"""
import asyncio,contextlib,fcntl,json,os,re,signal,stat,sys,threading,hashlib,subprocess,time,ctypes,errno
from pathlib import Path

LIMIT=65536
FRAME_LIMIT=262144
MC_CONVERTER_SHA256='edd893fa76bf44173705b69882946ed7acee0613761424518cfc455598170494'
class CredentialError(ValueError):pass
SCOPES={'bili':('bili_bridge_profile','https://www.bilibili.com/',frozenset(('bilibili.com','www.bilibili.com'))),'wb':('wb_bridge_profile','https://m.weibo.cn/',frozenset(('weibo.cn','m.weibo.cn'))),'zhihu':('zhihu_bridge_profile','https://www.zhihu.com/',frozenset(('zhihu.com','www.zhihu.com')))}
def scope_for(platform):
 if not isinstance(platform,str) or platform not in SCOPES:raise CredentialError('native_provider_session_invalid')
 return SCOPES[platform]
def schema_for(platform):
 scope_for(platform);return 'crowd-native-'+platform+'-credentials-v1'
SAFE_ERRORS={'native_provider_profile_invalid','native_provider_session_invalid','native_provider_profile_missing','native_provider_profile_busy','native_provider_mc_missing','native_provider_lock_invalid','native_provider_busy','native_provider_cookie_scope_invalid','native_provider_cookie_shape_invalid','native_provider_credentials_unavailable','native_provider_browser_unavailable','native_provider_persistence_unavailable','native_provider_unavailable','native_provider_retry_forbidden','native_provider_exit_observer_unavailable','native_provider_ownership_lost','native_provider_cleanup_unknown'}

def safe_path(path):
 if not isinstance(path,(str,os.PathLike)):raise CredentialError('native_provider_profile_invalid')
 p=Path(path)
 if not p.is_absolute() or p.resolve()!=p or any(x.is_symlink() for x in [p,*p.parents]):raise CredentialError('native_provider_profile_invalid')
 return p

def profile_for(root,session_id,platform='wb'):
 basename,_,_=scope_for(platform)
 import uuid
 if not isinstance(session_id,str) or str(uuid.UUID(session_id))!=session_id:raise CredentialError('native_provider_session_invalid')
 root=safe_path(root);session=safe_path(root/'sessions'/session_id);profile=safe_path(session/'browser_data'/basename)
 if any(p.stat().st_uid!=os.getuid() or stat.S_IMODE(p.stat().st_mode)&0o022 for p in (root,session,profile) if p.is_dir()):raise CredentialError('native_provider_profile_invalid')
 if not session.is_dir() or not profile.is_dir() or not safe_path(profile/'Default/Preferences').is_file():raise CredentialError('native_provider_profile_missing')
 identity=safe_path(session/'identity.json');fd=os.open(identity,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 try:
  info=os.fstat(fd)
  if not stat.S_ISREG(info.st_mode) or info.st_size>4096:raise CredentialError('native_provider_session_invalid')
  try:metadata=json.loads(os.read(fd,4097))
  except (ValueError,UnicodeError,RecursionError):raise CredentialError('native_provider_session_invalid') from None
  if not isinstance(metadata,dict) or metadata.get('platform')!=platform:raise CredentialError('native_provider_session_invalid')
 finally:os.close(fd)
 # Chrome itself retains ownership of persistent data. Never delete stale locks.
 lock=profile/'SingletonLock'
 if lock.is_symlink():
  match=re.search(r'-(\d+)$',os.readlink(lock))
  if not match:raise CredentialError('native_provider_profile_busy')
  try:os.kill(int(match[1]),0)
  except ProcessLookupError:pass
  except PermissionError:raise CredentialError('native_provider_profile_busy') from None
  else:raise CredentialError('native_provider_profile_busy')
 elif lock.exists():raise CredentialError('native_provider_profile_busy')
 return session,profile

def validate_credentials(value,platform='wb'):
 if not isinstance(value,dict) or set(value)!={'schema','cookies'} or value.get('schema')!=schema_for(platform):raise CredentialError('native_provider_protocol_invalid')
 cookie=value.get('cookies')
 if not isinstance(cookie,str) or not cookie or any(ord(x)<32 or ord(x)==127 for x in cookie):raise CredentialError('native_provider_credentials_unavailable')
 try:size=len(cookie.encode('utf8'))
 except UnicodeError:raise CredentialError('native_provider_credentials_unavailable') from None
 if size>LIMIT:raise CredentialError('native_provider_credentials_unavailable')
 return cookie

async def collect_original_context(root,session_id,mc_root,platform='wb'):
 _,url,domains=scope_for(platform)
 session,profile=profile_for(root,session_id,platform);mc=safe_path(mc_root)
 converter=safe_path(mc/'tools/crawler_util.py')
 if not converter.is_file() or hashlib.sha256(converter.read_bytes()).hexdigest()!=MC_CONVERTER_SHA256:raise CredentialError('native_provider_mc_missing')
 lockfd=os.open(session/'native-provider.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
 try:
  info=os.fstat(lockfd)
  if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1 or stat.S_IMODE(info.st_mode)!=0o600:raise CredentialError('native_provider_lock_invalid')
  try:fcntl.flock(lockfd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise CredentialError('native_provider_busy') from None
  # Recheck the same profile after acquiring our exclusive provider lock.
  assert profile_for(root,session_id,platform)[1]==profile
  sys.path.insert(0,str(mc))
  from playwright.async_api import async_playwright
  from tools.crawler_util import convert_browser_context_cookies
  class ScopedContext:
   def __init__(self,context):self.context=context
   async def cookies(self,urls=None):
    if urls!=[url]:raise CredentialError('native_provider_cookie_scope_invalid')
    rows=await self.context.cookies(urls=urls)
    if not isinstance(rows,list) or len(rows)>200:raise CredentialError('native_provider_cookie_shape_invalid')
    selected=[]
    for row in rows:
     if not isinstance(row,dict) or not isinstance(row.get('domain'),str):raise CredentialError('native_provider_cookie_shape_invalid')
     domain=row['domain'].lstrip('.').lower()
     if domain not in domains:raise CredentialError('native_provider_cookie_scope_invalid')
     if any(not isinstance(row.get(k),str) or not row[k] or any(ord(x)<32 or ord(x)==127 or x==';' for x in row[k]) for k in ('name','value')):raise CredentialError('native_provider_cookie_shape_invalid')
     selected.append(row)
    return selected
  async with async_playwright() as playwright:
   context=None
   try:
    try:context=await playwright.chromium.launch_persistent_context(str(profile),channel='chrome',headless=True,offline=True,service_workers='block',ignore_default_args=['--disable-extensions'])
    except Exception:raise CredentialError('native_provider_browser_unavailable') from None
    cookie,_=await convert_browser_context_cookies(ScopedContext(context),urls=[url])
    return validate_credentials({'schema':schema_for(platform),'cookies':cookie},platform)
   finally:
    if context is not None:
     try:await asyncio.wait_for(context.close(),10)
     except Exception:raise CredentialError('native_provider_persistence_unavailable') from None
 finally:os.close(lockfd)

def waitable_exit(pid):
 """Observe our child without reaping; PID/PGID ownership survives cleanup."""
 if hasattr(os,'waitid'):
  info=os.waitid(os.P_PID,pid,os.WEXITED|os.WNOHANG|os.WNOWAIT)
  return None if info is None or info.si_pid==0 else (info.si_code,info.si_status)
 if sys.platform!='darwin':raise CredentialError('native_provider_exit_observer_unavailable')
 # macOS SDK sys/signal.h siginfo_t: six ints, pointer, union sigval,
 # long si_band, unsigned long pad[7]. Python's macOS os omits waitid.
 class Info(ctypes.Structure):
  _fields_=[('signo',ctypes.c_int),('error',ctypes.c_int),('code',ctypes.c_int),('pid',ctypes.c_int),('uid',ctypes.c_uint),('status',ctypes.c_int),('addr',ctypes.c_void_p),('value',ctypes.c_void_p),('band',ctypes.c_long),('pad',ctypes.c_ulong*7)]
 if ctypes.sizeof(Info)!=104:raise CredentialError('native_provider_exit_observer_unavailable')
 libc=ctypes.CDLL(None,use_errno=True);call=libc.waitid;call.argtypes=[ctypes.c_int,ctypes.c_uint,ctypes.POINTER(Info),ctypes.c_int];call.restype=ctypes.c_int
 info=Info();rc=call(os.P_PID,pid,ctypes.byref(info),os.WEXITED|os.WNOHANG|os.WNOWAIT)
 if rc!=0:raise CredentialError('native_provider_ownership_lost')
 if info.pid==0:return None
 # waitid only observes this parent's child; Darwin may leave si_uid zero.
 if info.pid!=pid:raise CredentialError('native_provider_ownership_lost')
 return info.code,info.status

def active_group(pgid):
 # Process metadata only, never arguments or browser/profile contents.
 value=subprocess.run(['ps','-axo','pid=,pgid=,stat=,uid='],capture_output=True,text=True,timeout=2)
 if value.returncode or len(value.stdout)>1048576:raise CredentialError('native_provider_cleanup_unknown')
 result=[]
 for line in value.stdout.splitlines():
  parts=line.split()
  if len(parts)!=4:continue
  if int(parts[1])!=pgid or parts[2].startswith('Z'):continue
  if int(parts[3])!=os.getuid():raise CredentialError('native_provider_ownership_lost')
  result.append(int(parts[0]))
 return result

async def read_credentials(root,session_id,mc_root,*,timeout=25,platform='wb'):
 if not isinstance(timeout,(int,float)) or isinstance(timeout,bool) or not 1<=timeout<=30:raise CredentialError('native_provider_timeout_invalid')
 profile_for(root,session_id,platform);mc=safe_path(mc_root);python=mc/'.venv/bin/python'
 if not python.is_file():raise CredentialError('native_provider_python_missing')
 rd,wr=os.pipe();os.set_blocking(rd,False);process=None;raw=bytearray();deadline=time.monotonic()+timeout
 async def pause():
  if time.monotonic()>=deadline:raise asyncio.TimeoutError()
  await asyncio.sleep(min(.01,max(0,deadline-time.monotonic())))
 async def stop_owned():
  if process is None:return
  # No poll/wait/communicate before group cleanup. WNOWAIT retains PID.
  waitable_exit(process.pid)
  try:
   if active_group(process.pid):
    with contextlib.suppress(ProcessLookupError):os.killpg(process.pid,signal.SIGTERM)
    try:await asyncio.sleep(.2)
    finally:
     if active_group(process.pid):
      with contextlib.suppress(ProcessLookupError):os.killpg(process.pid,signal.SIGKILL)
     cleanup_deadline=time.monotonic()+2
     while active_group(process.pid):
      if time.monotonic()>=cleanup_deadline:raise CredentialError('native_provider_cleanup_unknown')
      await asyncio.sleep(.01)
  finally:
   with contextlib.suppress(subprocess.TimeoutExpired):process.wait(timeout=2)

 try:
  process=subprocess.Popen([str(python),'-I','-B',str(Path(__file__).resolve()),'_credential_child',str(wr)],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,pass_fds=(wr,),start_new_session=True)
  os.close(wr);wr=-1
  metadata={'root':str(root),'session_id':session_id,'mc_root':str(mc)}
  if platform!='wb':metadata['platform']=platform
  payload=json.dumps(metadata).encode()
  if len(payload)>16384:raise CredentialError('native_provider_protocol_invalid')
  os.set_blocking(process.stdin.fileno(),False);offset=0
  while offset<len(payload):
   try:offset+=os.write(process.stdin.fileno(),payload[offset:])
   except BlockingIOError:await pause()
  process.stdin.close()
  while True:
   if time.monotonic()>=deadline:raise asyncio.TimeoutError()
   try:block=os.read(rd,min(4096,FRAME_LIMIT+1-len(raw)))
   except BlockingIOError:await pause();continue
   if not block:break
   raw.extend(block)
   if len(raw)>FRAME_LIMIT:raise CredentialError('native_provider_response_too_large')
  # A valid frame is not a completed helper: observe actual normal exit.
  while waitable_exit(process.pid) is None:await pause()
 finally:
  if wr>=0:os.close(wr)
  try:await stop_owned()
  finally:
   if process is not None and process.stdin is not None:process.stdin.close()
   os.close(rd)
 try:value=json.loads(raw)
 except (ValueError,UnicodeError,RecursionError):raise CredentialError('native_provider_protocol_invalid') from None
 if process.returncode!=0:
  reason=value.get('reason') if isinstance(value,dict) else None
  raise CredentialError(reason if isinstance(reason,str) and reason in SAFE_ERRORS else 'native_provider_unavailable')
 return validate_credentials(value,platform)

def install_native_account(pool_class,root,session_id,mc_root,*,run=None,sink=None,platform='wb'):
 scope_for(platform)
 attempted=False
 async def load(pool):
  nonlocal attempted
  if pool._platform_name!=platform:raise SystemExit(78)
  try:
   if attempted:raise CredentialError('native_provider_retry_forbidden')
   attempted=True
   if run is not None:
    folder=safe_path(run);intent=folder/'native-credential-intent.json'
    try:fd=os.open(intent,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    except FileExistsError:raise CredentialError('native_provider_retry_forbidden') from None
    with os.fdopen(fd,'w') as stream:json.dump({'schema':'crowd-native-credential-intent-v1','run_id':folder.name,'session_id':session_id,'provider':'native_persistent','retry_unknown_forbidden':True},stream);stream.flush();os.fsync(stream.fileno())
   cookie=await read_credentials(root,session_id,mc_root,**({'platform':platform} if platform!='wb' else {}))
  except asyncio.CancelledError:raise
  except (CredentialError,OSError,asyncio.TimeoutError) as error:
   reason=str(error) if isinstance(error,CredentialError) and str(error) in SAFE_ERRORS else 'native_provider_unavailable'
   if sink is not None:
    try:sink.update(phase='failed',failure_reason='pro_native_credentials_unavailable',credential_provider='native_persistent',credential_reason=reason)
    except Exception:pass
   raise SystemExit(86) from None
  from pkg.account_pool.pool import AccountInfoModel,AccountStatusEnum
  pool.add_account(AccountInfoModel(id=1,account_name='native-original-'+platform+'-session',cookies=cookie,status=AccountStatusEnum.NORMAL.value,platform_name=platform))
 pool_class.load_accounts_from_cookie_bridge=load

def child_main(fd):
 parent=os.getppid();finished=threading.Event()
 def watch_parent():
  while not finished.wait(.5):
   if os.getppid()!=parent:
    if os.getpgrp()==os.getpid():os.killpg(os.getpid(),signal.SIGKILL)
    os._exit(86)
 threading.Thread(target=watch_parent,daemon=True).start()
 try:
  request=json.loads(sys.stdin.buffer.read(16385))
  if not isinstance(request,dict) or set(request) not in ({'root','session_id','mc_root'},{'root','session_id','mc_root','platform'}):raise CredentialError('native_provider_protocol_invalid')
  platform=request.get('platform','wb');scope_for(platform)
  cookie=asyncio.run(asyncio.wait_for(collect_original_context(request['root'],request['session_id'],request['mc_root'],**({'platform':platform} if platform!='wb' else {})),20))
  data=json.dumps({'schema':schema_for(platform),'cookies':cookie},separators=(',',':')).encode()
  if len(data)>FRAME_LIMIT:raise CredentialError('native_provider_response_too_large')
  with os.fdopen(fd,'wb') as pipe:pipe.write(data)
  return 0
 except BaseException as error:
  reason=str(error) if isinstance(error,CredentialError) and str(error) in SAFE_ERRORS else 'native_provider_unavailable'
  with contextlib.suppress(OSError):os.write(fd,json.dumps({'schema':'crowd-native-wb-error-v1','reason':reason}).encode())
  return 86
 finally:finished.set()
if __name__=='__main__':
 if len(sys.argv)!=3 or sys.argv[1]!='_credential_child':raise SystemExit(86)
 raise SystemExit(child_main(int(sys.argv[2])))
