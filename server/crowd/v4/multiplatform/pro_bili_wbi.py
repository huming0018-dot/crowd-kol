"""Use the installed mature WBI helper with this run's verified nav keys only.
No signer service, credential transport, cross-run cache or extra nav request.
"""
import hashlib,importlib.util,json,re,sys
from pathlib import Path
from urllib.parse import urlsplit
HELPER_SHA='ab2d346a64ea5b14fd650d0b7db2a12ba867d7a97d661e60f39fd10704fd7bab'
class WbiFailure(ValueError):pass

def load_signer(root):
 from managed_pro_signer import private_object,SignerError
 try:
  descriptor=private_object(Path(root)/'pro-signer.json')
  if set(descriptor)!={'python','source_root'} or any(type(descriptor[k]) is not str for k in descriptor):raise WbiFailure()
  source=Path(descriptor['source_root']);p=source/'logic/bilibili/help.py'
  if not source.is_absolute() or any(q.is_symlink() for q in [p,*p.parents]) :raise WbiFailure()
  raw=p.read_bytes()
  if hashlib.sha256(raw).hexdigest()!=HELPER_SHA:raise WbiFailure()
  # Imported helper is the original licensed pure Python class; use the already
  # loaded Pro SDK's compatible clock utility, without changing its pkg namespace.
  import pkg
  from pkg.tools import utils
  sentinel=object();old_module=sys.modules.get('pkg.utils',sentinel);old_attr=getattr(pkg,'utils',sentinel)
  sys.modules['pkg.utils']=utils;pkg.utils=utils
  try:
   spec=importlib.util.spec_from_file_location('_crowd_installed_bili_wbi',p);module=importlib.util.module_from_spec(spec);exec(compile(raw,str(p),'exec'),module.__dict__)
  finally:
   if old_module is sentinel:sys.modules.pop('pkg.utils',None)
   else:sys.modules['pkg.utils']=old_module
   if old_attr is sentinel:delattr(pkg,'utils')
   else:pkg.utils=old_attr
  return module.BilibiliSign
 except (OSError,ValueError,TypeError,KeyError,AttributeError,ImportError,SignerError):raise WbiFailure('pro_bili_wbi_dependency_unavailable') from None

LOCAL_MODE='verified_nav_local_wbi_v1'
def bridge_local_mode(root,request,bound):
 # Explicit local installation capability. Existing four-field Bridge bindings
 # remain unchanged and users without this descriptor retain the old SignSrv.
 if request.get('platform')!='bili' or bound.get('provider') in ('native_persistent','existing_cdp'):return False
 path=Path(root)/'pro-bili-wbi.json'
 try:path.lstat()
 except FileNotFoundError:return False
 except OSError:raise WbiFailure('pro_bili_wbi_dependency_unavailable') from None
 from managed_pro_signer import private_object,SignerError
 try:
  value=private_object(path)
  if value!={'mode':LOCAL_MODE} or type(value.get('mode')) is not str:raise ValueError()
 except (OSError,ValueError,TypeError,SignerError):raise WbiFailure('pro_bili_wbi_dependency_unavailable') from None
 return True

class BiliWbi:
 def __init__(self,run,request,sink):
  self.run=Path(run);self.request=request;self.sink=sink;self.signer=None;self.subject=None;self.context=None;self.key_urls=None;self.signs=0;self.installed=None
  from account_sessions import AccountSessions
  self.accounts=AccountSessions(self.run.parent.parent)
  baseline=self.accounts.status(request['session_id'],'bili')
  self.context=(baseline.get('generation'),baseline.get('account_ref'))
  if type(self.context[0]) is not int or self.context[0]<1 or type(self.context[1]) is not str:raise WbiFailure('pro_bili_wbi_identity_unverified')
  self.browser_connection=None
  manifest=json.loads((self.run/'manifest.json').read_text()) if (self.run/'manifest.json').is_file() else {}
  if manifest.get('executor',{}).get('binding')=={'platform':'bili','provider':'existing_cdp'}:
   from browser_session import validate_binding
   try:self.browser_connection=validate_binding(baseline.get('browser_connection'),'bili')
   except ValueError:raise WbiFailure('pro_bili_wbi_identity_unverified') from None
  self.sign_type=load_signer(self.run.parent.parent)
 def observe(self,response):
  from pro_account_sessions import self_proof
  from account_sessions import safe_account_ref
  u=response.request.url
  if (u.scheme,u.host,u.path)!=('https','api.bilibili.com','/x/web-interface/nav') or u.port not in (None,443) or u.query:return
  proof,subject=self_proof('bili',response)
  if proof!='authenticated':return
  if safe_account_ref('bili',subject)!=self.context[1]:return
  if self.subject is not None:raise WbiFailure('pro_bili_wbi_nav_repeated')
  try:
   value=response.json()['data']['wbi_img'];keys=[]
   for field in ('img_url','sub_url'):
    text=value[field]
    if type(text) is not str:raise WbiFailure()
    parsed=urlsplit(text)
    if parsed.scheme!='https' or parsed.hostname not in ('i0.hdslb.com','i1.hdslb.com','i2.hdslb.com') or parsed.port not in (None,443) or parsed.username or parsed.password or parsed.query or parsed.fragment:raise WbiFailure()
    match=re.fullmatch(r'/bfs/wbi/([a-f0-9]{32})\.png',parsed.path)
    if match is None:raise WbiFailure()
    keys.append(match[1])
   self.signer=self.sign_type(*keys);self.subject=safe_account_ref('bili',subject);self.key_urls=(value['img_url'],value['sub_url'])
  except (ValueError,TypeError,KeyError,AttributeError,RecursionError):raise WbiFailure('pro_bili_wbi_nav_keys_unavailable') from None
 def install(self,client_type):
  owner=self
  if self.installed is not None:raise WbiFailure('pro_bili_wbi_install_duplicate')
  original=client_type.bilibili_sign
  async def checked_sign(client,request):
   from pkg.rpc.sign_srv_client import BilibliSignResponse
   value=owner.accounts.status(owner.request['session_id'],'bili')
   context=(value.get('generation'),value.get('account_ref'))
   if owner.browser_connection is not None:
    from browser_session import validate_binding
    from shared_request_budget import canonical
    try:current_browser=validate_binding(value.get('browser_connection'),'bili')
    except ValueError:raise WbiFailure('pro_bili_wbi_identity_changed') from None
    if canonical(current_browser)!=canonical(owner.browser_connection):raise WbiFailure('pro_bili_wbi_identity_changed')
   if (owner.signer is None or owner.subject is None or value.get('account_ref')!=owner.subject
       or type(value.get('generation')) is not int or value['generation']<1
       or value.get('state') not in ('authenticated','resumed') or value.get('login_verified') is not True
       or value.get('pending_run_id')!=owner.run.name or value.get('authorized_for_run')!=owner.run.name):raise WbiFailure('pro_bili_wbi_identity_unverified')
   if owner.context is not None and context!=owner.context:raise WbiFailure('pro_bili_wbi_identity_changed')
   owner.context=context
   params=request.req_data
   if not isinstance(params,dict) or len(params)>64 or any(type(k) is not str or type(v) not in (str,int) for k,v in params.items()):raise WbiFailure('pro_bili_wbi_params_invalid')
   if len(json.dumps(params,ensure_ascii=False).encode())>16384 or owner.signs>=100:raise WbiFailure('pro_bili_wbi_limit')
   owner.signs+=1
   signed=owner.signer.sign(dict(params))
   return BilibliSignResponse(data={'wts':str(signed['wts']),'w_rid':signed['w_rid']})
  async def local_sign(client,request):
   try:return await checked_sign(client,request)
   except WbiFailure:
    owner.sink.update(phase='failed',failure_reason='pro_bili_wbi_unavailable');raise SystemExit(86) from None
  self.installed=(client_type,original,local_sign)
  client_type.bilibili_sign=local_sign
 def restore(self):
  if self.installed is None:return
  client,original,installed=self.installed
  if client.bilibili_sign is installed:client.bilibili_sign=original
  self.installed=None

 def media_context(self):
  from shared_request_budget import request_fingerprint
  from bili_wbi_context import validate
  if self.key_urls is None or self.subject!=self.context[1]:raise WbiFailure('pro_bili_wbi_identity_unverified')
  value={'schema':'crowd-bili-wbi-context-v1','run_id':self.run.name,'session_id':self.request['session_id'],'generation':self.context[0],'account_ref':self.context[1],'request_hash':request_fingerprint(self.request),'img_url':self.key_urls[0],'sub_url':self.key_urls[1]}
  manifest=json.loads((self.run/'manifest.json').read_text())
  if manifest.get('executor',{}).get('bili_wbi_mode')==LOCAL_MODE:
   from shared_request_budget import canonical
   value.update(schema='crowd-bili-wbi-context-v2',binding_sha256=hashlib.sha256(canonical(manifest['executor']['binding']).encode()).hexdigest())
  if manifest.get('executor',{}).get('binding')=={'platform':'bili','provider':'existing_cdp'}:
   from shared_request_budget import canonical
   value.update(schema='crowd-bili-wbi-context-v3',binding_sha256=hashlib.sha256(canonical(manifest['executor']['binding']).encode()).hexdigest(),browser_connection_sha256=hashlib.sha256(canonical(self.browser_connection).encode()).hexdigest())
  validate(value,self.run,manifest,require_proof=False)
  from shared_request_budget import canonical
  from bili_wbi_context import read_proof
  import os
  path=self.run/'bili-wbi-public-proof.json'
  proof={'schema':'crowd-bili-wbi-public-proof-v1','run_id':self.run.name,'request_hash':value['request_hash'],'context_sha256':hashlib.sha256(canonical(value).encode()).hexdigest()}
  try:fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  except FileExistsError:
   if canonical(read_proof(path))!=canonical(proof):raise WbiFailure('pro_bili_wbi_context_conflict')
  else:
   with os.fdopen(fd,'w') as stream:stream.write(canonical(proof));stream.flush();os.fsync(stream.fileno())
  validate(value,self.run,manifest)
  return value
