"""Server-side adapter for existing CloudClient; never puts Owner key in a browser."""
from pathlib import Path
import hashlib,json,re,stat,os
from urllib.parse import urlsplit,parse_qs
from datetime import datetime,timezone
from cloud_sync import CloudError

def bundle(directory,report_hash):
 if type(report_hash)is not str or re.fullmatch('[a-f0-9]{64}',report_hash)is None:raise ValueError('publication_local_invalid')
 root=Path(directory)
 if not root.is_absolute()or any(p.is_symlink()for p in [root,*root.parents]):raise ValueError('publication_local_invalid')
 def read(name,maximum):
  path=root/name
  if path.is_symlink()or not path.is_file()or not 0<path.stat().st_size<=maximum:raise ValueError('publication_local_invalid')
  return path.read_bytes()
 manifest=json.loads(read('manifest.json',16384));files={}
 if manifest.get('report_hash')!=report_hash:raise ValueError('publication_local_invalid')
 if set(manifest.get('formats',{}))!={'json','html','jsonl','csv'}:raise ValueError('publication_local_invalid')
 for fmt in ['json','html','jsonl','csv']:
  blob=read('report.'+fmt,1000000);expected=manifest['formats'][fmt]
  if len(blob)!=expected['bytes']or hashlib.sha256(blob).hexdigest()!=expected['sha256']:raise ValueError('publication_local_changed')
  files[fmt]=blob.decode('utf8',errors='strict')
 if hashlib.sha256(files['json'].encode()).hexdigest()!=report_hash or sum(len(x.encode())for x in files.values())>250000:raise ValueError('publication_local_changed')
 payload={'manifest':manifest,'files':files}
 if len(json.dumps({'action':'publication_put','payload':payload},ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())>300000:raise ValueError('publication_package_limit')
 return payload

class PublicationClient:
 def __init__(self,client):
  if getattr(client,'role',None)!='owner':raise ValueError('principal_denied')
  self.client=client
 def init(self):return self.client.call('publication_storage_init',{})
 def publish(self,directory,report_hash):
  # One call only; preserve unknown result. Server reconciles exact objects if explicitly resumed.
  return self.client.call('publication_put',bundle(directory,report_hash))
 def links(self,report_hash,expected_formats):
  if type(report_hash)is not str or re.fullmatch('[a-f0-9]{64}',report_hash)is None or type(expected_formats)is not dict or set(expected_formats)!={'json','html','jsonl','csv'}:raise ValueError('publication_local_invalid')
  value=self.client.call('publication_links',{'report_hash':report_hash})
  fields={'schema','owner_scope','report_hash','project_id','issued_at','expires_at','expires_in','formats','media_bytes_included'}
  if type(value)is not dict or set(value)!=fields or value['schema']!='crowd-publication-links-v1'or value['owner_scope']!='crowd-owner-main'or value['report_hash']!=report_hash or type(value['project_id'])is not str or re.fullmatch('[a-z0-9][a-z0-9-]{0,63}',value['project_id'])is None or type(value['expires_in'])is not int or value['expires_in']!=900 or value['media_bytes_included']is not False or type(value['formats'])is not dict or set(value['formats'])!=set(expected_formats):raise ValueError('publication_remote_mismatch')
  try:
   times=[]
   for key in ['issued_at','expires_at']:
    text=value[key]
    if type(text)is not str or re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z',text)is None:raise ValueError()
    times.append(datetime.fromisoformat(text.replace('Z','+00:00')))
   if (times[1]-times[0]).total_seconds()!=900 or times[1]<=datetime.now(timezone.utc):raise ValueError()
   endpoint=urlsplit(self.client.endpoint)
   for fmt,entry in value['formats'].items():
    if type(entry)is not dict or set(entry)!={'sha256','bytes','mime','signed_url'}or any(type(entry[k])is not type(expected_formats[fmt][k])or entry[k]!=expected_formats[fmt][k]for k in ['sha256','bytes','mime'])or type(entry['signed_url'])is not str or len(entry['signed_url'])>8192:raise ValueError()
    url=urlsplit(entry['signed_url']);query=parse_qs(url.query,keep_blank_values=True)
    if url.scheme!='https'or url.netloc!=endpoint.netloc or url.username or url.password or url.fragment or url.path!='/storage/v1/object/sign/crowd-publication-snapshots/publications/crowd-owner-main/'+report_hash+'/report.'+fmt or set(query)!={'token','download'}or len(query['token'])!=1 or not query['token'][0]or query['download']!=['']:raise ValueError()
  except (ValueError,TypeError,KeyError,OverflowError):raise ValueError('publication_remote_mismatch')from None
  return value
 def read(self,report_hash,fmt,expected_sha256):
  if type(report_hash)is not str or re.fullmatch('[a-f0-9]{64}',report_hash)is None or fmt not in ('json','html','jsonl','csv')or type(expected_sha256)is not str or re.fullmatch('[a-f0-9]{64}',expected_sha256)is None:raise ValueError('publication_local_invalid')
  try:value=self.client.call('publication_get',{'report_hash':report_hash,'format':fmt})
  except CloudError as error:
   # Until root merges the single read action into current G02 error classification,
   # a read transport failure is unavailable, never a write outcome to reconcile.
   if str(error)=='cloud_outcome_unknown':raise CloudError('cloud_read_unavailable')from None
   raise
  if type(value)is not dict or value.get('schema')!='crowd-publication-read-v1'or value.get('report_hash')!=report_hash or value.get('format')!=fmt or type(value.get('body_utf8'))is not str:raise ValueError('publication_remote_mismatch')
  raw=value['body_utf8'].encode('utf8',errors='strict')
  if not 0<len(raw)<=1000000 or value.get('bytes')!=len(raw)or value.get('sha256')!=expected_sha256 or hashlib.sha256(raw).hexdigest()!=expected_sha256 or value.get('media_bytes_included')is not False:raise ValueError('publication_remote_mismatch')
  return raw

if __name__=='__main__':
 import argparse,sys
 parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);parser.add_argument('--snapshot',required=True);parser.add_argument('--report-hash',required=True);parser.add_argument('--action',choices=['init','publish','read','links'],required=True);parser.add_argument('--links-output');parser.add_argument('--format',choices=['json','html','jsonl','csv'],default='json');args=parser.parse_args()
 # Explicit operator invocation only. No config/credentials are read merely on import.
 from cloud_sync import CloudClient
 api=PublicationClient(CloudClient(args.config,role='owner'))
 local=bundle(Path(args.snapshot).resolve(),args.report_hash)
 if args.action=='links':
  if not args.links_output:parser.error('--links-output required for private credentials')
  target=Path(args.links_output)
  if not target.is_absolute()or any(p.is_symlink()for p in [target,*target.parents]):raise ValueError('publication_local_invalid')
  # Reserve private destination before minting; an unknown issuance is never repeated implicitly.
  fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'w')as out:
   value=api.links(args.report_hash,local['manifest']['formats']);
   if value['project_id']!=local['manifest']['project_id']:raise ValueError('publication_remote_mismatch')
   json.dump(value,out);out.flush();os.fsync(out.fileno())
  print(json.dumps({'schema':value['schema'],'report_hash':value['report_hash'],'expires_at':value['expires_at'],'formats':{f:{k:e[k]for k in ['sha256','bytes']}for f,e in value['formats'].items()},'media_bytes_included':False}))
 elif args.action=='init':print(json.dumps(api.init(),ensure_ascii=False))
 elif args.action=='publish':print(json.dumps(api.publish(Path(args.snapshot).resolve(),args.report_hash),ensure_ascii=False))
 else:sys.stdout.buffer.write(api.read(args.report_hash,args.format,local['manifest']['formats'][args.format]['sha256']))
