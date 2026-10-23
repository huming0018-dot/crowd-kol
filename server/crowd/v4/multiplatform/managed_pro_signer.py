"""Own the already-audited pure local signer for one original Pro run."""
import contextlib,errno,fcntl,hashlib,json,os,signal,socket,stat,subprocess,time,uuid,sys
from pathlib import Path
SERVER=Path(__file__).with_name('pro_signer_server.py')
SERVER_SHA='7a33a3545ee91e7d592f75a50d6eb3152e77d8492f0952d8300bd3a47a8cabeb'
SOURCE_MANIFEST_SHA='65f74774ed37b21fa49688929a17270c1f7777ef82fecc075239d24c8ed26b6d'
SOURCE_COMMIT='26c53d8f3221d95e0d4961b0593debd179d3cf10'
class SignerError(RuntimeError):pass

def private_object(path):
 try:
  if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError()
  fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
  try:
   a=os.fstat(fd)
   if not stat.S_ISREG(a.st_mode) or a.st_uid!=os.getuid() or a.st_mode&0o077 or not 0<a.st_size<=16384:raise ValueError()
   raw=os.read(fd,16385);b=os.fstat(fd)
   if len(raw)!=a.st_size or (a.st_size,a.st_mtime_ns,a.st_ctime_ns)!=(b.st_size,b.st_mtime_ns,b.st_ctime_ns):raise ValueError()
   value=json.loads(raw)
   if not isinstance(value,dict):raise ValueError()
   return value
  finally:os.close(fd)
 except FileNotFoundError:raise SignerError('pro_signer_installation_missing') from None
 except (OSError,ValueError,TypeError,RecursionError):raise SignerError('pro_signer_installation_invalid') from None

def stop_owned(process):
 if process.returncode is not None:return
 for sig,timeout in ((signal.SIGTERM,2),(signal.SIGKILL,2)):
  try:os.killpg(process.pid,sig)
  except ProcessLookupError:pass
  try:process.wait(timeout=timeout)
  except subprocess.TimeoutExpired:continue
  if sig==signal.SIGTERM:
   # The leader can exit before an owned descendant; match existing media cleanup.
   try:os.killpg(process.pid,signal.SIGKILL)
   except ProcessLookupError:pass
  return
 raise SignerError('pro_signer_stop_unknown')

@contextlib.contextmanager
def owned_signer(run,request,binding):
 if request.get('platform') not in ('xhs','dy','zhihu'):
  yield {'state':'not_required'};return
 run=Path(run)
 try:valid_run=run.is_absolute() and not any(p.is_symlink() for p in (run,*run.parents)) and str(uuid.UUID(run.name))==run.name
 except ValueError:valid_run=False
 if not valid_run:raise SignerError('pro_signer_run_invalid')
 if binding.get('platform')!=request['platform'] or binding.get('sign_url')!='http://127.0.0.1:8990':raise SignerError('pro_signer_binding_invalid')
 lifetime=request.get('timeout_seconds')
 if type(lifetime) is not int or not 1<=lifetime<=7200:raise SignerError('pro_signer_lifetime_invalid')
 collector=run.parent.parent;descriptor=private_object(collector/'pro-signer.json')
 if set(descriptor)!={'python','source_root'} or any(not isinstance(descriptor[k],str) for k in descriptor):raise SignerError('pro_signer_installation_invalid')
 python=Path(descriptor['python']);source=Path(descriptor['source_root'])
 if not python.is_absolute() or not python.is_file() or not os.access(python,os.X_OK) or not source.is_absolute() or not source.is_dir() or source.is_symlink():raise SignerError('pro_signer_installation_invalid')
 if SERVER.is_symlink() or hashlib.sha256(SERVER.read_bytes()).hexdigest()!=SERVER_SHA or hashlib.sha256(SERVER.with_name('SIGN-SOURCE-SHA.json').read_bytes()).hexdigest()!=SOURCE_MANIFEST_SHA:raise SignerError('pro_signer_wrapper_changed')
 lockpath=collector/'signer-8990.lock';fd=os.open(lockpath,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK,0o600);process=None
 try:
  meta=os.fstat(fd)
  if not stat.S_ISREG(meta.st_mode) or meta.st_uid!=os.getuid() or meta.st_nlink!=1 or meta.st_mode&0o077:raise SignerError('pro_signer_lock_invalid')
  try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise SignerError('pro_signer_busy') from None
  with socket.socket() as probe:
   try:probe.bind(('127.0.0.1',8990))
   except OSError as error:raise SignerError('pro_signer_busy' if error.errno==errno.EADDRINUSE else 'pro_signer_listen_unavailable') from None
  intent=run/'sign-service-intent.json';
  try:intentfd=os.open(intent,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  except FileExistsError:raise SignerError('pro_signer_intent_already_exists') from None
  with os.fdopen(intentfd,'w') as stream:
   json.dump({'run_id':run.name,'platform':request['platform'],'port':8990,'wrapper_sha256':SERVER_SHA,'retry_unknown_forbidden':True},stream);stream.flush();os.fsync(stream.fileno())
  lifecycle=run/'sign-service-lifecycle.jsonl';env=os.environ.copy()
  for k in list(env):
   if k in ('PYTHONPATH','PYTHONHOME','NODE_OPTIONS','NODE_PATH','CROWD_EXECUTOR','CROWD_PRO_WEIBO_ENABLED') or k.startswith(('DYLD_','LD_PRELOAD')):env.pop(k,None)
  env.update(CROWD_SIGNER_PARENT_PID=str(os.getpid()),CROWD_SIGNER_MAX_SECONDS=str(lifetime+10))
  try:process=subprocess.Popen([str(python),'-B',str(SERVER),'--source-root',str(source),'--serve','--lifecycle',str(lifecycle)],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=env,cwd=run,start_new_session=True)
  except OSError:raise SignerError('pro_signer_spawn_failed') from None
  until=time.monotonic()+min(10,lifetime)
  while time.monotonic()<until:
   if process.poll() is not None:raise SignerError('pro_signer_start_failed')
   if lifecycle.exists():
    try:
     life_fd=os.open(lifecycle,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
     try:
      info=os.fstat(life_fd)
      if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:raise SignerError('pro_signer_lifecycle_invalid')
      raw=os.read(life_fd,16385)
     finally:os.close(life_fd)
     if len(raw)>16384:raise SignerError('pro_signer_lifecycle_invalid')
     rows=[json.loads(line) for line in raw.splitlines()]
     first=rows[0] if rows else {}
     if not isinstance(first,dict):raise SignerError('pro_signer_lifecycle_invalid')
     if (first.get('event')=='started' and type(first.get('pid')) is int and first['pid']==process.pid and first.get('host')=='127.0.0.1' and first.get('port')==8990 and first.get('source_commit')==SOURCE_COMMIT and type(first.get('source_requests')) is int and first['source_requests']==0 and type(first.get('sign_count')) is int and first['sign_count']==0 and first.get('browser_started') is False and first.get('failed') is False):break
    except (json.JSONDecodeError,OSError):pass
   time.sleep(.02)
  else:raise SignerError('pro_signer_start_timeout')
  yield {'state':'ready','owned_pid':process.pid}
 finally:
  preserving_error=sys.exc_info()[0] is not None
  try:
   if process is not None:
    try:stop_owned(process)
    except SignerError:
     if not preserving_error:raise
  finally:os.close(fd)
