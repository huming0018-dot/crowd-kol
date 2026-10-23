"""Finite local Pro preflight. Cached official identity is not fresh platform auth.

No login, Cookie read, source HTTP, listener, HELLO or task. Expensive dependency
validation is cached for at most60s, keyed by exact local files. Execution keeps
the original official self check and all runner budget/stop/identity guards.
"""
from pathlib import Path
import hashlib,json,math,os,platform,re,stat,subprocess,time

SOURCE_COMMIT='d32dd565277116ba4880c28ccd417a7c376cb62d'
PROTOCOL='vox-acquisition-v1'
_CACHE={}
_NEGATIVE={}
class Unavailable(Exception):
 def __init__(self,reason):self.reason=reason
def need(ok,reason):
 if not ok:raise Unavailable(reason)
def _host():
 system={'Darwin':'darwin','Linux':'linux','Windows':'windows','Android':'android','iOS':'ios'}.get(platform.system(),'unknown')
 arch={'arm64':'arm64','aarch64':'arm64','AMD64':'x64','x86_64':'x64','i386':'x86','i686':'x86','x86':'x86'}.get(platform.machine(),'unknown')
 return {'os':system,'arch':arch}
def _sha(path,private=False):
 path=Path(path);need(not any(x.is_symlink()for x in(path,*path.parents)),'preflight_failed')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 try:
  a=os.fstat(fd);need(stat.S_ISREG(a.st_mode)and a.st_nlink==1 and a.st_uid in(0,os.getuid())and not a.st_mode&0o022 and 0<=a.st_size<=160*1024*1024,'preflight_failed')
  if private:need(a.st_uid==os.getuid()and a.st_size>0 and not a.st_mode&0o077,'preflight_failed')
  with os.fdopen(os.dup(fd),'rb')as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
  b=os.fstat(fd);need((a.st_ino,a.st_size,a.st_mtime_ns,a.st_ctime_ns)==(b.st_ino,b.st_size,b.st_mtime_ns,b.st_ctime_ns),'preflight_failed');return digest
 finally:os.close(fd)
def _fingerprint(paths):
 return {str(Path(p)):_sha(p)for p in sorted(set(map(str,paths)))}
def _source_info(root):
 from pro_executor import bridge
 return bridge().source_info(root)
def _dependency_probe(installation,collector):
 """Real pinned capability exit + actual client/store dependencies, never pong."""
 import pro_executor as P
 from managed_pro_signer import private_object,SERVER,SERVER_SHA,SOURCE_MANIFEST_SHA
 info=P.probe(installation['root'],installation['python'])
 need(info['protocol']==PROTOCOL and 'xhs'in info['native_protocol_platforms'],'dependency_unavailable')
 # Socket-denied imports validate the actual selected Python, not the Owner Python.
 script="""import sys,json,socket,pathlib
def deny(*a,**k):raise OSError('preflight_network_forbidden')
socket.socket.connect=deny;socket.create_connection=deny
sys.path.insert(0,sys.argv[1])
from media_platform.xhs.client import XiaoHongShuClient
from media_platform.xhs.handlers.detail_handler import DetailHandler
from repo.platform_save_data.xhs.xhs_store_impl import XhsDbStoreImplement
import aiofiles,httpx,pydantic
roots=[pathlib.Path(sys.argv[1]).resolve(),pathlib.Path(sys.prefix).resolve()]
paths=sorted({str(pathlib.Path(m.__file__).resolve())for m in list(sys.modules.values())if getattr(m,'__file__',None)and pathlib.Path(m.__file__).is_file()and any(pathlib.Path(m.__file__).resolve().is_relative_to(r)for r in roots)})
print(json.dumps({'ok':True,'files':paths}))
"""
 env={'PATH':os.environ.get('PATH',''),'PYTHONDONTWRITEBYTECODE':'1','PYTHONUNBUFFERED':'1'}
 result=subprocess.run([installation['python'],'-B','-c',script,installation['root']],cwd=installation['root'],env=env,capture_output=True,timeout=10)
 need(result.returncode==0 and len(result.stdout)<=262144,'dependency_unavailable');modules=json.loads(result.stdout);need(modules.get('ok')is True and type(modules.get('files'))is list,'dependency_unavailable')
 descriptor=private_object(Path(collector)/'pro-signer.json');need(set(descriptor)=={'python','source_root'},'dependency_unavailable')
 need(_sha(SERVER)==SERVER_SHA and _sha(SERVER.with_name('SIGN-SOURCE-SHA.json'))==SOURCE_MANIFEST_SHA,'source_changed')
 signer_python=Path(descriptor['python']);signer_source=Path(descriptor['source_root']);need(signer_python.is_absolute()and signer_python.is_file()and os.access(signer_python,os.X_OK),'dependency_unavailable')
 # Existing validate-only mode verifies source/dependency pins, creates no listener.
 # Preserve the selected venv entry (resolving it before invocation loses its
 # environment). Invoke the existing main/validate-only, then inspect only
 # imported file locations and its selected Node. Both legacy NODE-SHA and
 # current portable-Node wrappers therefore keep their own existing checks.
 sign_script="""import sys,json,pathlib,shutil
sys.path.insert(0,sys.argv[1]);import pro_signer_server as S
server,source=sys.argv[1:];sys.argv=[str(pathlib.Path(server)/'pro_signer_server.py'),'--source-root',source]
code=S.main()
if code:raise SystemExit(code)
roots=[pathlib.Path(server).resolve(),pathlib.Path(source).resolve(),pathlib.Path(sys.prefix).resolve()]
paths=sorted({str(pathlib.Path(m.__file__).resolve())for m in list(sys.modules.values())if getattr(m,'__file__',None)and pathlib.Path(m.__file__).is_file()and any(pathlib.Path(m.__file__).resolve().is_relative_to(r)for r in roots)})
print(json.dumps({'files':paths,'node':shutil.which('node')}))
"""
 result=subprocess.run([str(signer_python),'-B','-c',sign_script,str(SERVER.parent),str(signer_source)],env=env,capture_output=True,timeout=10)
 need(result.returncode==0 and len(result.stdout)<=262144,'dependency_unavailable');lines=result.stdout.splitlines();need(len(lines)==2,'dependency_unavailable');value=json.loads(lines[0]);sign_files=json.loads(lines[1])
 need(value=={'ok':True,'validate_only':True,'listening':False,'source_requests':0,'browser_started':False,'platforms':['xhs','dy','zhihu']},'dependency_unavailable')
 need(type(sign_files.get('node'))is str and type(sign_files.get('files'))is list,'dependency_unavailable');node=Path(sign_files['node']).resolve()
 manifest=json.loads(SERVER.with_name('SIGN-SOURCE-SHA.json').read_text())
 node_resource=list(node.parent.parent.rglob('*'))if node.parent.name=='bin'and node.parent.parent.parent.name=='node-runtime'else[node]
 metadata=[SERVER.with_name(n)for n in('SIGN-SOURCE-SHA.json','DEPENDENCIES.json','DEPENDENCY-SHA.json','NODE-SHA.json')]
 files=[*map(Path,modules['files']),*map(Path,sign_files['files']),Path(installation['python']).resolve(),signer_python.resolve(),SERVER,*metadata,*[signer_source/n for n in manifest],*node_resource]
 # Archive/manifest/Node/license files are all included in cache invalidation.
 return [p for p in files if p.is_file()]
def _state(store,sid,now):
 s=store.status(sid,'xhs');need(s.get('login_in_progress')is False,'login_in_progress')
 need(s.get('session_id')==sid and s.get('platform')=='xhs'and s.get('state')in('authenticated','resumed')and s.get('identity_status')=='authenticated_self_id'and s.get('login_verified')is True and s.get('recovering')is False and type(s.get('generation'))is int and s['generation']>=1 and type(s.get('account_ref'))is str and re.fullmatch('[a-f0-9]{64}',s['account_ref'])is not None,'identity_unverified')
 verified=s.get('verified_at');need(type(verified)in(int,float)and math.isfinite(verified)and 0<verified<=now,'identity_unverified')
 need(s.get('verification_method')=='upstream_authenticated_endpoint','identity_unverified');return s
def produce(app,now=None):
 now=time.time()if now is None else now;host=_host();base={'observed_at_ms':int(now*1000),'host':host,'state':'not_ready','reason_code':'preflight_failed','source_readiness':[]}
 try:
  # Existing own locks/Node installer are not yet a Windows/mobile product.
  need(host['os']in('darwin','linux'),'unsupported_scope')
  from account_sessions import AccountSessions
  import pro_executor as P
  try:sid=app._cloud_session({'platform':'xhs'})
  except (ValueError,OSError):raise Unavailable('not_configured')from None
  roots=[Path(r)for r in app._roots()if(Path(r)/'sessions'/sid).is_dir()];need(len(roots)==1,'not_configured');root=roots[0];store=AccountSessions(root);state=_state(store,sid,now)
  request={'source_executor':'pro','platform':'xhs','session_id':sid}
  try:installation=P.task_installation(root,request);bound=P.binding_for(root,request)
  except (ValueError,OSError,P.bridge().BridgeError):raise Unavailable('not_configured')from None
  need(bound.get('platform')=='xhs'and bound.get('sign_url')=='http://127.0.0.1:8990','unsupported_scope')
  info=_source_info(installation['root']);need(info.get('commit')==SOURCE_COMMIT and info.get('dirty')is False,'source_changed')
  critical=[root/'pro-executor.json',root/'pro-signer.json',root/'sessions'/sid/'identity.json',root/'sessions'/sid/'pro-binding.json',root/'accounts'/sid/'state.json']
  for path in critical:_sha(path,True)
  basics=_fingerprint(critical);key=(str(root),sid);cached=_CACHE.get(key);files=None
  failed=_NEGATIVE.get(key)
  if failed and failed['basic']==basics and 0<=now-failed['at']<15:raise Unavailable(failed['reason'])
  if cached and 0<=now-cached['at']<60 and cached['basic']==basics:
   try:
    if _fingerprint(cached['files'])==cached['fingerprint']:files=cached['files']
   except (OSError,ValueError,Unavailable):pass
  if files is None:
   try:files=_dependency_probe(installation,root)
   except Unavailable as error:
    _NEGATIVE[key]={'at':now,'basic':basics,'reason':error.reason};raise
   except Exception:
    _NEGATIVE[key]={'at':now,'basic':basics,'reason':'dependency_unavailable'};raise Unavailable('dependency_unavailable')from None
   fingerprint=_fingerprint(files);_CACHE[key]={'at':now,'basic':basics,'files':files,'fingerprint':fingerprint}
  need(_fingerprint(critical)==basics and _state(store,sid,now)==state,'identity_unverified')
  proof=hashlib.sha256(json.dumps({'local_files':basics,'dependency_files':_CACHE[key]['fingerprint'],'source_commit':SOURCE_COMMIT},sort_keys=True,separators=(',',':')).encode()).hexdigest()
  scope={'schema':'crowd-pro-source-readiness-v1','engine':'mediacrawler_pro','protocol':PROTOCOL,'platform':'xhs','mode':'detail','scope':'xhs_detail_body_comments_v1','comments':True,'replies':True,'media':False,'max_items':1,'max_comments':200,'source_commit':SOURCE_COMMIT,'identity_basis':'cached_authenticated_self_id','identity_verified_at_ms':int(state['verified_at']*1000),'session_generation':state['generation'],'session_ref':hashlib.sha256(sid.encode()).hexdigest(),'binding_sha256':proof}
  return {**base,'state':'ready','reason_code':'ready','source_readiness':[scope]}
 except Unavailable as e:return {**base,'reason_code':e.reason}
 except Exception:return base
