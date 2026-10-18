"""Explicit local Owner share action using existing immutable publication and Storage links."""
import base64,datetime,hashlib,json,os,stat,uuid
from pathlib import Path
from publication_client import PublicationClient
MIMES={'json':'application/json; charset=utf-8','html':'text/html; charset=utf-8','jsonl':'application/x-ndjson; charset=utf-8','csv':'text/csv; charset=utf-8'}
PAGE='https://app-lyart-eta-22.vercel.app/materials'

def generate(app,payload):
 if type(payload)is dict and ('pro_key'in payload or 'operation'in payload):
  from publication_pro_share import generate as pro_generate
  return pro_generate(app,payload)
 if type(payload)is not dict or set(payload)!={'request_id'} or type(payload['request_id'])is not str:raise ValueError('publication_share_invalid')
 try:
  if str(uuid.UUID(payload['request_id']))!=payload['request_id']:raise ValueError()
 except ValueError:raise ValueError('publication_share_invalid')from None
 client=getattr(app,'cloud_client',None)
 if getattr(client,'role',None)!='owner':raise ValueError('owner_authorization_required')
 if getattr(client,'endpoint',None)!='https://bdwrhshgdeghgyzwpxnl.supabase.co/functions/v1/crowd-machine':raise ValueError('publication_share_scope_unavailable')
 # Read existing exports, never build, publish, collect or accept a browser-selected scope.
 expected={};project=None;report_hash=None
 for fmt,mime in MIMES.items():
  raw=app.material_delivery(fmt,domain=True)
  if type(raw)is not bytes or not 0<len(raw)<=1000000:raise ValueError('publication_share_local_unavailable')
  digest=hashlib.sha256(raw).hexdigest();expected[fmt]={'sha256':digest,'bytes':len(raw),'mime':mime}
  if fmt=='json':
   report=json.loads(raw);project=report.get('project_id');report_hash=digest
 if project!='shanghai-existing-six-domain':raise ValueError('publication_share_scope_unavailable')
 root=Path(app.root);folder=root/'publication-share-intents'
 if any(p.is_symlink()for p in [folder,*folder.parents]):raise ValueError('publication_share_local_unavailable')
 folder.mkdir(mode=0o700,exist_ok=True);meta=folder.stat()
 if not stat.S_ISDIR(meta.st_mode)or meta.st_uid!=os.getuid()or meta.st_mode&0o077:raise ValueError('publication_share_local_unavailable')
 # Intent only: never save signed URLs. Same request, including unknown outcomes, cannot remint.
 try:fd=os.open(folder/(payload['request_id']+'.json'),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 except FileExistsError:raise ValueError('publication_share_already_attempted')from None
 with os.fdopen(fd,'w')as out:
  json.dump({'request_id':payload['request_id'],'report_hash':report_hash,'status':'attempted_no_automatic_retry'},out);out.flush();os.fsync(out.fileno())
 try:
  value=PublicationClient(client).links(report_hash,expected)
  if value['project_id']!=project:raise ValueError()
  now=datetime.datetime.now(datetime.timezone.utc);start=datetime.datetime.fromisoformat(value['issued_at'].replace('Z','+00:00'))
  if start>now+datetime.timedelta(seconds=30):raise ValueError()
  # Existing server fixes bucket, scope and four paths; bounded fragment uses the same consumer schema.
  encoded=base64.urlsafe_b64encode(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode()).rstrip(b'=')
  if len(encoded)>32755:raise ValueError()
  return {'ok':True,'schema':'crowd-owner-publication-share-v1','report_hash':report_hash,'project_id':project,'expires_at':value['expires_at'],'page_url':PAGE+'#publication='+encoded.decode('ascii')}
 except Exception:raise ValueError('publication_share_outcome_unknown_no_retry')from None
