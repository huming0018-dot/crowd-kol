"""Parent-side own glue. Captures the same original Pro response, no repeat detail."""
import json,os,subprocess,uuid,signal,time,threading
from pathlib import Path
from pro_hybrid_media import bili_view,weibo_mblog

class BiliDetailObserver:
 def __init__(self):self.views={}
 def observe(self,response):
  # Safe observer of the already-requested API response only. No HTTP action.
  try:
   u=__import__('urllib.parse',fromlist=['urlsplit']).urlsplit(str(response.request.url))
   if u.scheme!='https' or u.username or u.password or u.port not in (None,443) or u.fragment or u.hostname!='api.bilibili.com' or u.path not in ('/x/web-interface/view','/x/web-interface/view/detail'):return
   data=response.json()
   if response.status_code!=200 or not isinstance(data,dict) or type(data.get('code')) is not int or data['code']!=0 or not isinstance(data.get('data'),dict):return
   raw=data['data'];view=raw.get('View') if isinstance(raw.get('View'),dict) else raw
   safe={k:view[k] for k in ('aid','cid','bvid','pic','duration') if k in view}
   bvid=safe.get('bvid');bili_view({'video_id':str(safe.get('aid')),'bvid':bvid},{'View':safe})
   if bvid in self.views and self.views[bvid]!=safe:
    self.views[bvid]=None;raise ValueError('hybrid_detail_identity_conflict')
   self.views[bvid]=safe
  except (ValueError,TypeError,AttributeError):return
 def response_for(self,note):
  view=self.views.get(note.get('bvid'))
  return bili_view(note,{'View':view})

def run_media_child(run,note,response,headers,*,python,mc_root,runtime_root,budget_module_root,timeout=600,wbi_context=None):
 """Caller validates pinned paths and request budget before this explicit action.
 No task creation, browser startup or CookieBridge request. Credentials in pipe only.
 """
 from shared_request_budget import request_fingerprint
 run=Path(run);manifest=json.loads((run/'manifest.json').read_text());request=manifest['request']
 if str(uuid.UUID(run.name))!=run.name or manifest['run_id']!=run.name:raise ValueError('hybrid_media_run_invalid')
 if request['platform']=='wb':
  from shared_request_budget import canonical
  import hashlib
  weibo_mblog(note)
  if response!={'weibo_observation_sha256':hashlib.sha256(canonical(note).encode()).hexdigest()} or headers!={}:raise ValueError('hybrid_weibo_observation_mismatch')
  child=Path(__file__).with_name('wb_media_child.py')
 else:
  bili_view(note,response)
  native=manifest.get('executor',{}).get('binding',{}).get('provider')=='native_persistent'
  if native:
   from bili_wbi_context import validate
   validate(wbi_context,run,manifest)
  elif wbi_context is not None:raise ValueError('hybrid_media_wbi_context_invalid')
  child=Path(__file__).with_name('bili_media_child.py')
 env=os.environ.copy()
 for k in ('PYTHONHOME','NODE_OPTIONS','NODE_PATH','CROWD_EXECUTOR','CROWD_PRO_WEIBO_ENABLED'):env.pop(k,None)
 env['PYTHONPATH']=os.pathsep.join([str(Path(__file__).parent),str(budget_module_root),str(runtime_root),str(mc_root)])
 # An intent precedes subprocess launch. Timeout/unknown cannot silently retry.
 fd=os.open(run/'hybrid-media-dispatch.json',os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'w') as f:json.dump({'run_id':run.name,'request_hash':request_fingerprint(request),'retry_unknown_forbidden':True},f)
 payload={'run':str(run.resolve()),'note':note,'response':response,'headers':headers,'request_hash':request_fingerprint(request)}
 if wbi_context is not None:payload['wbi_context']=wbi_context
 if threading.current_thread() is not threading.main_thread():raise ValueError('hybrid_media_main_thread_required')
 process=None;prior_handler=signal.getsignal(signal.SIGTERM)
 def stop_group():
  if process is None:return
  try:os.killpg(process.pid,signal.SIGTERM)
  except ProcessLookupError:pass
  try:process.wait(timeout=2)
  except subprocess.TimeoutExpired:
   try:os.killpg(process.pid,signal.SIGKILL)
   except ProcessLookupError:pass
   process.wait(timeout=2)
  # The leader may have exited before a TERM-ignoring FFmpeg descendant.
  try:os.killpg(process.pid,signal.SIGKILL)
  except ProcessLookupError:pass
 def stopped(signum,frame):
  stop_group();raise SystemExit(128+signum)
 try:
  signal.signal(signal.SIGTERM,stopped)
  process=subprocess.Popen([str(python),'-B',str(child)],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=env,cwd=run,start_new_session=True)
  process.communicate(input=json.dumps(payload).encode(),timeout=timeout)
  done=process
 except BaseException:
  stop_group();raise  # preserve timeout/cancellation; intent remains unknown
 finally:
  stop_group()  # also stop any owned FFmpeg descendant left after child exit
  signal.signal(signal.SIGTERM,prior_handler)
 if done.returncode==77:raise ValueError('hybrid_media_access_denied_not_login_proof')
 if done.returncode in (73,74,79,80,81,82):raise SystemExit(done.returncode)
 if done.returncode!=0:raise ValueError('hybrid_media_failed_or_unknown')
 from analysis_artifact import _read
 result=_read(run/'hybrid-media-result.json',1048576)[0]
 if result.get('run_id')!=run.name or result.get('request_hash')!=payload['request_hash']:raise ValueError('hybrid_media_result_binding_invalid')
 return result
