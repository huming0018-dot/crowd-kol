"""Private IPC of public WBI keys, bound to the current authenticated run."""
import re,os,stat,json
from pathlib import Path
from urllib.parse import urlsplit
FIELDS=frozenset(('schema','run_id','session_id','generation','account_ref','request_hash','img_url','sub_url'))
def read_proof(path):
 try:
  path=Path(path)
  if any(p.is_symlink() for p in path.parents):raise ValueError()
  fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
  try:
   before=os.fstat(fd)
   if (not stat.S_ISREG(before.st_mode) or before.st_uid!=os.getuid() or before.st_nlink!=1
       or stat.S_IMODE(before.st_mode)!=0o600 or not 0<before.st_size<=2048):raise ValueError()
   raw=os.read(fd,2049);after=os.fstat(fd)
   if (len(raw)!=before.st_size or (before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns,before.st_mode,before.st_nlink)!=(after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns,after.st_mode,after.st_nlink)):raise ValueError()
   value=json.loads(raw)
   if (not isinstance(value,dict) or set(value)!={'schema','run_id','request_hash','context_sha256'}
       or any(type(v) is not str for v in value.values())
       or value['schema']!='crowd-bili-wbi-public-proof-v1'
       or re.fullmatch(r'[a-f0-9-]{36}',value['run_id']) is None
       or any(re.fullmatch(r'[a-f0-9]{64}',value[k]) is None for k in ('request_hash','context_sha256'))):raise ValueError()
   return value
  finally:os.close(fd)
 except (OSError,ValueError,TypeError,UnicodeError,RecursionError):raise ValueError('hybrid_media_wbi_context_invalid') from None

def validate(value,run,manifest,*,require_proof=True):
 from shared_request_budget import request_fingerprint
 from account_sessions import AccountSessions
 try:
  request=manifest['request'];run=Path(run)
  if not isinstance(value,dict) or set(value)!=FIELDS or value['schema']!='crowd-bili-wbi-context-v1':raise ValueError()
  if (request['platform']!='bili' or request.get('source_executor')!='pro'
      or manifest['executor']['binding']!={'platform':'bili','provider':'native_persistent'}
      or type(value['generation']) is not int or value['generation']<1
      or value['run_id']!=run.name or manifest['run_id']!=run.name
      or value['session_id']!=request['session_id'] or value['request_hash']!=request_fingerprint(request)
      or type(value['account_ref']) is not str):raise ValueError()
  account=AccountSessions(run.parent.parent).status(request['session_id'],'bili')
  if (account.get('generation')!=value['generation'] or type(account.get('generation')) is not int
      or account.get('account_ref')!=value['account_ref'] or account.get('pending_run_id')!=run.name
      or account.get('authorized_for_run')!=run.name or account.get('login_verified') is not True
      or account.get('state') not in ('authenticated','resumed')):raise ValueError()
  for key in ('img_url','sub_url'):
   if type(value[key]) is not str:raise ValueError()
   u=urlsplit(value[key])
   if (u.scheme!='https' or u.hostname not in ('i0.hdslb.com','i1.hdslb.com','i2.hdslb.com')
       or u.port not in (None,443) or u.username or u.password or u.query or u.fragment
       or re.fullmatch(r'/bfs/wbi/[a-f0-9]{32}\.png',u.path) is None):raise ValueError()
  if require_proof:
   from shared_request_budget import canonical
   import hashlib
   proof=read_proof(run/'bili-wbi-public-proof.json')
   expected={'schema':'crowd-bili-wbi-public-proof-v1','run_id':run.name,'request_hash':value['request_hash'],'context_sha256':hashlib.sha256(canonical(value).encode()).hexdigest()}
   if canonical(proof)!=canonical(expected):raise ValueError()
  return {'wbi_img_url':value['img_url'],'wbi_sub_url':value['sub_url']}
 except (ValueError,TypeError,KeyError,AttributeError,OSError):raise ValueError('hybrid_media_wbi_context_invalid') from None
