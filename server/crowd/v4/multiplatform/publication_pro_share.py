"""Explicit publication of a server-known ready Pro Consumer snapshot, never a collector."""
from pathlib import Path
import base64,datetime,hashlib,json,os,re,stat,uuid
from publication_client import PublicationClient,bundle

SCHEMA='crowd-owner-pro-publication-v1'
def private_dir(path):
 if any(p.is_symlink()for p in [path,*path.parents]):raise ValueError('publication_pro_local_invalid')
 path.mkdir(mode=0o700,parents=True,exist_ok=True);s=path.stat()
 if s.st_uid!=os.getuid()or not stat.S_ISDIR(s.st_mode)or s.st_mode&0o077:raise ValueError('publication_pro_local_invalid')
 return path

def create(path,value):
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'w')as out:json.dump(value,out,ensure_ascii=False,sort_keys=True,separators=(',',':'));out.flush();os.fsync(out.fileno())
 fd=os.open(path.parent,os.O_RDONLY);os.fsync(fd);os.close(fd)

def read(path):
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 with os.fdopen(fd,'rb')as stream:
  s=os.fstat(stream.fileno())
  if not stat.S_ISREG(s.st_mode)or s.st_uid!=os.getuid()or s.st_mode&0o077 or not 0<s.st_size<=16384:raise ValueError('publication_pro_local_invalid')
  return json.loads(stream.read(16385))

def generate(app,payload):
 from publication_share import MIMES,PAGE
 from participant_material_delivery import publication
 from pro_ack_snapshot import validate_context,scope,validate_group,project_id,records
 from material_bridge import read_bytes
 if type(payload)is not dict or set(payload)!={'request_id','pro_key','operation'} or payload['operation']not in ('publish','verify','links'):raise ValueError('publication_share_invalid')
 try:
  if type(payload['request_id'])is not str or str(uuid.UUID(payload['request_id']))!=payload['request_id']:raise ValueError()
 except (ValueError,TypeError,AttributeError):raise ValueError('publication_share_invalid')from None
 key=payload['pro_key']
 if type(key)is not str or re.fullmatch('pro-[a-f0-9]{64}',key)is None:raise ValueError('publication_share_invalid')
 client=getattr(app,'cloud_client',None)
 if getattr(client,'role',None)!='owner':raise ValueError('owner_authorization_required')
 if getattr(client,'endpoint',None)!='https://bdwrhshgdeghgyzwpxnl.supabase.co/functions/v1/crowd-machine':raise ValueError('publication_share_scope_unavailable')
 state=publication(app.root,key)
 if state.get('state')!='ready':raise ValueError('publication_pro_not_ready')
 # Bind the selected context to its original ACK group before trusting any pointer.
 context=validate_context(state['context']);selected=scope({k:context[k]for k in ('task_id','subject','installation_id','dispatch_id')})
 raw_group=read_bytes(Path(context['group_path']),8*1024*1024)
 if hashlib.sha256(raw_group).hexdigest()!=context['group_sha256']:raise ValueError('publication_pro_scope_mismatch')
 snapshot=validate_group(json.loads(raw_group))
 if snapshot['scope']!=selected or snapshot['group_cursor']!=context['group_cursor']or state.get('source_scope')!=selected or type(state.get('items'))is not int or state['items']!=len(snapshot['receipts']):raise ValueError('publication_pro_scope_mismatch')
 # The existing Consumer read revalidates snapshot/pack and item mapping. No client path/hash accepted.
 bodies={f:app.material_delivery(f,pro_key=key)for f in MIMES}
 if any(type(v)is not bytes or not 0<len(v)<=1000000 for v in bodies.values())or sum(map(len,bodies.values()))>250000:raise ValueError('publication_package_limit')
 report=json.loads(bodies['json']);project=report.get('project_id')
 if project!=project_id(snapshot) or type(report.get('items'))is not list or len(report['items'])!=state['items']:raise ValueError('publication_pro_scope_mismatch')
 selected_rows=records(snapshot);item_rows={}
 for row in report['items']:
  if type(row)is not dict or type(row.get('identity'))is not dict or type(row.get('metadata'))is not dict:raise ValueError('publication_pro_scope_mismatch')
  request=row['identity'].get('source_record_id')
  if type(request)is not str or request in item_rows:raise ValueError('publication_pro_scope_mismatch')
  item_rows[request]=row['metadata'].get('capture')
 if item_rows!=selected_rows:raise ValueError('publication_pro_scope_mismatch')
 digest=hashlib.sha256(bodies['json']).hexdigest();formats={f:{'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'mime':MIMES[f]}for f,raw in bodies.items()}
 manifest={'schema':'crowd-publication-snapshot-v1','owner_scope':'crowd-owner-main','report_hash':digest,'project_id':project,'as_of':report['as_of'],'tool_version':report['tool_version'],'item_count':len(report['items']),'formats':formats,'media_bytes_included':False}
 root=Path(app.root);folder=private_dir(root/'publication-pro-bundles')/digest
 if not folder.exists():
  try:folder.mkdir(mode=0o700)
  except FileExistsError:pass
  # Partial creation stays fail-closed; never overwrite an existing immutable bundle.
  for f,raw in bodies.items():
   fd=os.open(folder/('report.'+f),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
   with os.fdopen(fd,'wb')as out:out.write(raw);out.flush();os.fsync(out.fileno())
  create(folder/'manifest.json',manifest)
 if bundle(folder,digest)!={'manifest':manifest,'files':{f:v.decode('utf8')for f,v in bodies.items()}}:raise ValueError('publication_pro_local_changed')
 private_dir(folder)
 expected={'schema':SCHEMA,'pro_key':key,'report_hash':digest,'formats':formats,'items':len(report['items']),'project_id':project}
 verified_file=folder/'verified.json'
 def verified():
  if not verified_file.exists():return False
  if read(verified_file)!=expected:raise ValueError('publication_pro_local_changed')
  return True
 def result():return {'ok':True,'schema':SCHEMA,'status':'verified','verified':True,'pro_key':key,'report_hash':digest,'project_id':project,'items':len(report['items']),'formats':formats,'media_bytes_included':False}
 operation=payload['operation'];api=PublicationClient(client)
 if operation=='publish'and verified():return result()
 if operation=='links'and not verified():raise ValueError('publication_pro_not_verified')
 intents=private_dir(root/'publication-pro-intents')
 try:create(intents/(payload['request_id']+'.json'),{'schema':SCHEMA,'operation':operation,'pro_key':key,'report_hash':digest,'status':'attempted_no_automatic_retry'})
 except FileExistsError:raise ValueError('publication_share_already_attempted')from None
 if operation in ('publish','verify'):
  if operation=='publish':
   try:create(folder/'publish-intent.json',{'request_id':payload['request_id'],'status':'attempted_no_automatic_retry'})
   except FileExistsError:raise ValueError('publication_pro_publish_unknown_verify_required')from None
  elif not (folder/'publish-intent.json').exists():raise ValueError('publication_pro_not_published')
  try:
   if operation=='publish':api.publish(folder,digest)
   for f,raw in bodies.items():
    if api.read(digest,f,formats[f]['sha256'])!=raw:raise ValueError('publication_remote_mismatch')
   try:create(verified_file,expected)
   except FileExistsError:verified()
   return result()
  except Exception:raise ValueError('publication_pro_'+operation+'_unknown_no_retry')from None
 try:
  value=api.links(digest,formats)
  if value['project_id']!=project:raise ValueError()
  now=datetime.datetime.now(datetime.timezone.utc);start=datetime.datetime.fromisoformat(value['issued_at'].replace('Z','+00:00'))
  if start>now+datetime.timedelta(seconds=30):raise ValueError()
  encoded=base64.urlsafe_b64encode(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode()).rstrip(b'=')
  if len(encoded)>32755:raise ValueError()
  return {'ok':True,'schema':'crowd-owner-publication-share-v1','report_hash':digest,'project_id':project,'expires_at':value['expires_at'],'page_url':PAGE+'#publication='+encoded.decode()}
 except Exception:raise ValueError('publication_pro_links_unknown_no_retry')from None
