"""Server-side adapter for existing CloudClient; never puts Owner key in a browser."""
from pathlib import Path
import hashlib,json,re,stat
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
 parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);parser.add_argument('--snapshot',required=True);parser.add_argument('--report-hash',required=True);parser.add_argument('--action',choices=['init','publish','read'],required=True);parser.add_argument('--format',choices=['json','html','jsonl','csv'],default='json');args=parser.parse_args()
 # Explicit operator invocation only. No config/credentials are read merely on import.
 from cloud_sync import CloudClient
 api=PublicationClient(CloudClient(args.config,role='owner'))
 local=bundle(Path(args.snapshot).resolve(),args.report_hash)
 if args.action=='init':print(json.dumps(api.init(),ensure_ascii=False))
 elif args.action=='publish':print(json.dumps(api.publish(Path(args.snapshot).resolve(),args.report_hash),ensure_ascii=False))
 else:sys.stdout.buffer.write(api.read(args.report_hash,args.format,local['manifest']['formats'][args.format]['sha256']))
