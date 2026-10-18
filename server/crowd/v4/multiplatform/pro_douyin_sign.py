"""Use the same installed licensed pure sign implementation without an HTTP hop."""
import asyncio,json,os,signal,subprocess,sys
from pathlib import Path
from managed_pro_signer import private_object,stop_owned,SignerError
from pro_native_credentials import read_private_credentials,CredentialError

def validate_sign_output(value):
 if type(value) is not dict or set(value)!={'a_bogus'} or type(value['a_bogus']) is not str or not 1<=len(value['a_bogus'])<=2048:raise ValueError()
 return value

class LocalDouyinSign:
 def __init__(self,run,scope):self.run=Path(run);self.scope=scope;self.original=None;self.count=0
 def install(self,client_type):
  owner=self;original=client_type.douyin_sign;descriptor=private_object(self.run.parent.parent/'pro-signer.json')
  if set(descriptor)!={'python','source_root'} or any(type(v) is not str for v in descriptor.values()):raise SignerError('pro_signer_installation_invalid')
  python=Path(descriptor['python']);source=Path(descriptor['source_root'])
  if not python.is_absolute() or not python.is_file() or not source.is_absolute() or not source.is_dir():raise SignerError('pro_signer_installation_invalid')
  # O_EXCL prevents replay after unknown child/sign outcome for this run.
  journal=self.run/'dy-local-sign-intent.jsonl';fd=os.open(journal,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);os.close(fd)
  async def sign(instance,sign_req):
   owner.scope.validate()
   if owner.count>=100:raise SignerError('pro_signer_unavailable')
   if type(sign_req.uri) is not str or not sign_req.uri.startswith('/aweme/v1/web/') or len(sign_req.uri)>512 or type(sign_req.query_params) is not str or len(sign_req.query_params)>12000 or type(sign_req.user_agent) is not str or len(sign_req.user_agent)>2048:raise SignerError('pro_signer_unavailable')
   owner.count+=1
   fd=os.open(journal,os.O_WRONLY|os.O_APPEND|os.O_NOFOLLOW|os.O_NONBLOCK)
   with os.fdopen(fd,'w') as stream:stream.write(json.dumps({'ordinal':owner.count,'phase':'before_sign'})+'\n');stream.flush();os.fsync(stream.fileno())
   env=os.environ.copy()
   for key in list(env):
    if key in ('PYTHONPATH','PYTHONHOME','NODE_OPTIONS','NODE_PATH') or key.startswith(('DYLD_','LD_PRELOAD')):env.pop(key,None)
   try:
    payload={'source_root':str(source),'uri':sign_req.uri,'query_params':sign_req.query_params,'user_agent':sign_req.user_agent}
    value=await read_private_credentials(python,Path(__file__).with_name('pro_douyin_sign_worker.py'),payload,timeout=10,platform='dy',output_validator=validate_sign_output,env=env)
    owner.scope.validate()
    from pkg.rpc.sign_srv_client.sign_model import DouyinSignResponse,DouyinSignResult
    return DouyinSignResponse(data=DouyinSignResult(a_bogus=value['a_bogus']))
   except (OSError,ValueError,asyncio.TimeoutError,CredentialError):raise SignerError('pro_signer_unavailable') from None
  client_type.douyin_sign=sign;self.original=(client_type,original);return self
 def restore(self):
  if self.original:self.original[0].douyin_sign=self.original[1];self.original=None
