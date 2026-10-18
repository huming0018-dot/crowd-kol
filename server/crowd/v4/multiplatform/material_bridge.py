"""Explicit pinned inputs -> existing CTFS stages. No platform/cloud transport."""
from pathlib import Path
import argparse,hashlib,json,os,stat,sys,csv,io,uuid
MAX_SNAPSHOT=8*1024*1024
class MaterialError(ValueError):pass

def read_bytes(path,limit):
 p=Path(path).absolute()
 if any(x.is_symlink()for x in (p,*p.parents)):raise MaterialError('material_path_symlink')
 fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 try:
  before=os.fstat(fd)
  if not stat.S_ISREG(before.st_mode)or before.st_nlink!=1 or before.st_size>limit:raise MaterialError('material_file_invalid')
  raw=os.read(fd,limit+1);after=os.fstat(fd)
  if len(raw)!=before.st_size or (before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns):raise MaterialError('material_file_changed')
  return raw
 finally:os.close(fd)

def parse_json(raw):
 def pairs(items):
  result={}
  for k,v in items:
   if k in result:raise MaterialError('material_duplicate_key')
   result[k]=v
  return result
 try:return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(MaterialError('material_nonfinite')))
 except (RecursionError,UnicodeError,json.JSONDecodeError):raise MaterialError('material_json_invalid')from None

def read_json(path,limit=MAX_SNAPSHOT):
 return parse_json(read_bytes(path,limit))

def csv_records(text):
 # Existing snapshot byte bound also bounds one embedded typed capture field.
 previous=csv.field_size_limit()
 try:
  csv.field_size_limit(MAX_SNAPSHOT)
  return [json.loads(v['record'])for v in csv.DictReader(io.StringIO(text))]
 finally:csv.field_size_limit(previous)

def pin_source(root,pins,expected_sha256=None):
 root=Path(root).absolute();blob=read_bytes(pins,MAX_SNAPSHOT)
 if expected_sha256 is not None and hashlib.sha256(blob).hexdigest()!=expected_sha256:raise MaterialError('toolbox_pin_changed')
 doc=parse_json(blob)
 if doc.get('source_version')!='0.5.1'or type(doc.get('files'))is not dict or not doc['files']:raise MaterialError('toolbox_pin_invalid')
 for name,sha in doc['files'].items():
  rel=Path(name)
  if rel.is_absolute()or '..'in rel.parts or hashlib.sha256(read_bytes(root/rel,MAX_SNAPSHOT)).hexdigest()!=sha:raise MaterialError('toolbox_source_changed')
 return root

def pro_snapshot_module(runtime_root,expected):
 path=Path(runtime_root).absolute()/'pro_ack_snapshot.py'
 if type(expected)is not str or hashlib.sha256(read_bytes(path,MAX_SNAPSHOT)).hexdigest()!=expected:raise MaterialError('material_pro_snapshot_changed')
 import pro_ack_snapshot
 if Path(pro_ack_snapshot.__file__).absolute()!=path:raise MaterialError('material_pro_snapshot_changed')
 return pro_ack_snapshot

def pro_comments_module(runtime_root,expected):
 path=Path(runtime_root).absolute()/'participant_pro_comments.py'
 if type(expected)is not str or hashlib.sha256(read_bytes(path,MAX_SNAPSHOT)).hexdigest()!=expected:raise MaterialError('material_pro_comments_changed')
 import participant_pro_comments
 if Path(participant_pro_comments.__file__).absolute()!=path:raise MaterialError('material_pro_comments_changed')
 return participant_pro_comments

def snapshot_bundle(snapshot,runtime_root):
 if type(snapshot)is dict and snapshot.get('schema')=='crowd-participant-pro-material-snapshot-v1':
  from pro_ack_snapshot import bundle
  return bundle(snapshot)
 # Keep the existing wire canonical/hash domain; Python short JSON is different.
 runtime_root=Path(runtime_root).absolute();sys.path.insert(0,str(runtime_root))
 from cloud_sync import canonical,_hash,SCHEMA
 if type(snapshot)is not dict or snapshot.get('schema')!='ctfs-confirmed-capture-snapshot-v1' or type(snapshot.get('captures'))is not list or not 1<=len(snapshot['captures'])<=2000:raise MaterialError('material_snapshot_invalid')
 task=snapshot.get('task_id');child=snapshot.get('child_id')
 for x in (task,child):
  try:assert str(uuid.UUID(x))==x
  except (ValueError,TypeError,AttributeError,AssertionError):raise MaterialError('material_scope_invalid')from None
 sources=[];candidates=[];seen=set()
 for item in snapshot['captures']:
  if type(item)is not dict or set(item)!={'capture_id','envelope_hash','envelope_canonical','receipt_canonical','envelope','receipt'}:raise MaterialError('material_capture_invalid')
  e=item['envelope'];r=item['receipt'];cid=item['capture_id']
  if type(e)is not dict or type(r)is not dict or e.get('schema')!=SCHEMA or canonical(e)!=item['envelope_canonical']or canonical(r)!=canonical(json.loads(item['receipt_canonical']))or r!=json.loads(item['receipt_canonical'])or _hash(SCHEMA,e)!=item['envelope_hash']or cid in seen:raise MaterialError('material_original_changed')
  if e.get('task_id')!=task or e.get('child_id')!=child or e.get('capture_id')!=cid or type(e.get('lease_epoch'))is not int:raise MaterialError('material_capture_scope')
  for key in ('task_id','child_id','run_id','lease_epoch','capture_id'):
   if type(e.get(key))is not type(r.get(key))or e.get(key)!=r.get(key):raise MaterialError('material_receipt_binding')
  rec=e.get('record')
  if type(rec)is not dict or rec.get('kind')not in ('content','comment')or rec.get('reward_eligible')is not False or r.get('reward_eligible')is not False or r.get('status')!='received'or r.get('envelope_hash')!=item['envelope_hash']:raise MaterialError('material_receipt_invalid')
  try:expected=str(uuid.uuid5(uuid.UUID(e['run_id']),canonical(rec)))
  except (TypeError,ValueError,KeyError):raise MaterialError('material_run_invalid')from None
  if cid!=expected:raise MaterialError('material_capture_identity')
  text=rec.get('text')if rec['kind']=='comment'else rec.get('body')
  if not isinstance(text,str)or not 1<=len(text)<=500000:raise MaterialError('material_text_outside_pack_scope')
  platform=rec.get('platform')
  if not isinstance(platform,str)or not platform:raise MaterialError('material_platform_missing')
  seen.add(cid);title=text[:80];sources.append({'version_id':cid,'source_id':platform+'-ugc','source_kind':'ugc','canonical_body':text,'canonical_body_sha256':hashlib.sha256(text.encode()).hexdigest(),'retrieved_at':r['received_at']})
  candidates.append({'id':cid,'revision':1,'draft':{'title':title,'text':text,'entity_type':rec['kind']},'evidence':[{'source_version_id':cid,'start':0,'end':len(title),'quote':title,'field':'title'}]+[{'source_version_id':cid,'start':start,'end':min(start+5000,len(text)),'quote':text[start:start+5000],'field':'text'}for start in range(0,len(text),5000)],'capture':item,'coverage':snapshot.get('coverage','unknown'),'unscoreable_reason':'No verified restaurant identity or independent dining evidence. Material traceability is not taste, quality or reward.'})
 return {'source_versions':sources,'candidates':candidates,'capture_snapshot':snapshot}

def snapshot_publication_scope(snapshot):
 if snapshot.get('schema')=='crowd-participant-pro-material-snapshot-v1':
  from pro_ack_snapshot import project_id,records
  pid=project_id(snapshot);return pid,pid,records(snapshot)
 return 'confirmed-'+snapshot['task_id'],snapshot['task_id'],{x['capture_id']:x for x in snapshot['captures']}

def _same_or_create(path,raw):
 path=Path(path).absolute()
 if any(x.is_symlink()for x in (path,*path.parents)):raise MaterialError('material_path_symlink')
 if path.exists()or path.is_symlink():
  if read_bytes(path,MAX_SNAPSHOT)!=raw:raise MaterialError('material_job_artifact_changed')
  return
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'wb')as f:f.write(raw);f.flush();os.fsync(f.fileno())

def run(snapshot_path,snapshot_sha256,toolbox_root,toolbox_pins,pack_path,pack_sha256,output,as_of,runtime_root,runtime_cloud_sha256,job_id=None,pro_snapshot_sha256=None,pro_comments_sha256=None):
 # Fixed admin configuration supplies roots/digests; browser callers supply only job scope.
 root=pin_source(toolbox_root,toolbox_pins);blob=read_bytes(snapshot_path,MAX_SNAPSHOT)
 if hashlib.sha256(blob).hexdigest()!=snapshot_sha256:raise MaterialError('material_snapshot_changed')
 if hashlib.sha256(read_bytes(Path(runtime_root)/'cloud_sync.py',MAX_SNAPSHOT)).hexdigest()!=runtime_cloud_sha256:raise MaterialError('material_wire_runtime_changed')
 pack=Path(pack_path).absolute();expected={'pack.yaml','fields.yaml','pointers.json','validation.yaml','rubric.yaml','expectations.yaml'}
 if set(p.name for p in pack.iterdir())!=expected or type(pack_sha256)is not dict or set(pack_sha256)!=expected:raise MaterialError('material_pack_invalid')
 for name in expected:
  if hashlib.sha256(read_bytes(pack/name,MAX_SNAPSHOT)).hexdigest()!=pack_sha256[name]:raise MaterialError('material_pack_changed')
 if 'toolbox'in sys.modules:raise MaterialError('toolbox_already_imported')
 sys.path.insert(0,str(root))
 import toolbox,yaml
 from toolbox.ontology import OntologyManager
 from toolbox.pack_schema import load_pack
 from toolbox.manifest import Manifest
 from toolbox.storage import SqliteStorage
 from toolbox.stages import Stages,exact_ref
 from toolbox.consumer import Consumer
 from toolbox.bindings import utc
 utc(as_of,'as_of')
 if toolbox.__version__!='0.5.1'or not Path(toolbox.__file__).resolve().is_relative_to(root.resolve()):raise MaterialError('toolbox_import_mismatch')
 snapshot=parse_json(blob)
 if snapshot.get('schema')=='crowd-participant-pro-material-snapshot-v1':
  pro_snapshot_module(runtime_root,pro_snapshot_sha256)
  if 'comment_receipts'in snapshot:pro_comments_module(runtime_root,pro_comments_sha256)
 bundle=snapshot_bundle(snapshot,runtime_root);raw=json.dumps(bundle,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode();digest=hashlib.sha256(raw).hexdigest()
 if job_id is not None and (type(job_id)is not str or len(job_id)!=64 or any(x not in '0123456789abcdef'for x in job_id)):raise MaterialError('material_job_id_invalid')
 output=Path(output).absolute()
 if any(p.is_symlink()for p in (output,*output.parents)):raise MaterialError('material_output_symlink')
 output.mkdir(mode=0o700,parents=False,exist_ok=job_id is not None)
 if job_id is not None:
  # The caller persists job scope/as_of; retries cannot silently bind new bytes.
  bound={'job_id':job_id,'snapshot_sha256':snapshot_sha256,'bundle_sha256':digest,'as_of':as_of,'toolbox_pins_sha256':hashlib.sha256(read_bytes(toolbox_pins,MAX_SNAPSHOT)).hexdigest(),'pack_sha256':pack_sha256,'runtime_cloud_sha256':runtime_cloud_sha256}
  marker=output/'material-job-input.json'
  if not marker.exists() and any(output.iterdir()):raise MaterialError('material_job_unbound_directory')
  _same_or_create(marker,json.dumps(bound,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
 store=output/'packs'
 if job_id is not None and any(p.is_symlink()for p in (store,output/'data',output/'inputs')):raise MaterialError('material_output_symlink')
 mgr=OntologyManager(store);packdoc=yaml.safe_load(read_bytes(pack/'pack.yaml',MAX_SNAPSHOT));packid=packdoc['pack']['pack_id']
 installed_pack=store/'packs'/packid/packdoc['pack']['version']
 if job_id is None or not installed_pack.exists():mgr.install(pack)
 contract=load_pack(store,packid)
 if job_id is not None:
  for name in expected:
   if hashlib.sha256(read_bytes(installed_pack/name,MAX_SNAPSHOT)).hexdigest()!=pack_sha256[name]:raise MaterialError('material_pack_changed')
 pid,source_scope,expected_records=snapshot_publication_scope(snapshot);mf={'schemaVersion':'0.4.0','project':{'project_id':pid,'name':'已确认公开素材','domain':'public-source-material','region':'unknown'},'storage':{'backend':'sqlite','path':'data/store.sqlite'},'crawler':{'connector':'snapshot-file','timeout_seconds':30.0,'max_requests':1,'max_bytes':MAX_SNAPSHOT,'per_request_max_bytes':MAX_SNAPSHOT},'ontology':{'packs':[packid]},'pipelines':{k:{'schemaVersion':'0.2.0','target':'data/'+k}for k in ['raw','clean','scored','audit']},'raw':{'sources':[{'source_id':'confirmed-snapshot','kind':'json','url':'snapshot://'+source_scope,'connector':'snapshot-file'}]}}
 if job_id is not None:
  (output/'inputs').mkdir(mode=0o700,exist_ok=True)
  _same_or_create(output/'inputs/confirmed-bundle.json',raw)
  mf['raw']['sources'][0].update(url='snapshot://inputs/confirmed-bundle.json',expected_sha=digest)
 mfpath=output/'manifest.yaml';_same_or_create(mfpath,yaml.safe_dump(mf,allow_unicode=True).encode());manifest=Manifest.load(mfpath);(output/'data').mkdir(exist_ok=job_id is not None);db=SqliteStorage(output/'data/store.sqlite')
 try:
  if job_id is not None:
   from toolbox.jobs import Jobs
   jobs=Jobs(manifest,contract,db,as_of)
   try:
    status=jobs.run(job_id)
    if status.get('state')!='completed':raise MaterialError('material_job_not_completed')
   finally:jobs.close()
   consumer=Consumer(manifest,contract,db,as_of);data=consumer.current()
   receipt=status['attempts'][-1]['outputs']
   consumer.publication(receipt)
  else:
   source='snapshot://'+source_scope;rid=db.write_raw(pid,{'schemaVersion':'0.2.0','project_id':pid,'layer':'RAW','payload':raw,'source_url':source,'source_hash':digest,'batch':snapshot_sha256,'captured_at':as_of,'lineage':{'project':pid,'source_url':source,'source_hash':digest,'batch':snapshot_sha256,'captured_at':as_of,'steps':['durable-capture-snapshot-not-http'],'tool_versions':['ctfs-toolbox:'+toolbox.__version__]}})
   stages=Stages(manifest,contract,db,as_of);chains=[]
   for ods in stages.clean(rid):
    dw=stages.score(ods['record_id'],ods['version']);audit=stages.audit(rid,dw['record_id'],dw['version'])
    if not audit['passed']:raise MaterialError('material_audit_failed')
    chains.append({'raw':exact_ref(db.read(pid,'RAW',rid),'RAW'),'dw':exact_ref(dw,'DW'),'audit':exact_ref(audit['audit'],'APP')})
   consumer=Consumer(manifest,contract,db,as_of);receipt=consumer.publish(chains);data=consumer.current()
  if len(data['items'])!=len(bundle['candidates']):raise MaterialError('material_count_mismatch')
  if {x['identity']['source_record_id']:x['metadata']['capture']for x in data['items']}!=expected_records:raise MaterialError('material_delivery_mapping_changed')
 finally:db.close()
 readonly=SqliteStorage(output/'data/store.sqlite',read_only=True)
 try:
  if Consumer(manifest,contract,readonly,as_of).current()!=data:raise MaterialError('material_reopen_changed')
 finally:readonly.close()
 jsonl=''.join(json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n'for row in data['items'])
 _same_or_create(output/'materials.jsonl',jsonl.encode())
 buffer=io.StringIO(newline='');w=csv.DictWriter(buffer,fieldnames=['source_record_id','score_domain','restaurant_taste_score','record']);w.writeheader()
 for row in data['items']:w.writerow({'source_record_id':row['identity']['source_record_id'],'score_domain':'material_traceability_only','restaurant_taste_score':'','record':json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(',',':'))})
 _same_or_create(output/'materials.csv',buffer.getvalue().encode())
 if data['items']!=[json.loads(v)for v in (output/'materials.jsonl').read_text().splitlines()]or data['items']!=csv_records((output/'materials.csv').read_text()):raise MaterialError('material_export_mismatch')
 result={'state':'completed',**({'source_scope':snapshot['scope'],'source_kind':'participant_pro'}if snapshot.get('schema')=='crowd-participant-pro-material-snapshot-v1'else {'task_id':snapshot['task_id'],'child_id':snapshot['child_id']}),'snapshot_sha256':snapshot_sha256,'items':len(data['items']),'coverage':snapshot.get('coverage','unknown'),'source_calls':0,'budget_debits':0,'restaurant_taste_score':None,'score_domain':'material_traceability_only','as_of':as_of,'tool_version':toolbox.__version__,'publication':receipt,'html':receipt['directory']+'/index.html','json':receipt['directory']+'/report.json','jsonl':'materials.jsonl','csv':'materials.csv'}
 if job_id is not None:result.update(job_id=job_id,processing_driver='existing_toolbox_jobs_snapshot_file',source_calls=0,local_snapshot_reads=1)
 _same_or_create(output/'result.json',(json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode());return result

def read_publication(request,fmt='json'):
 root=pin_source(request['toolbox_root'],request['toolbox_pins'])
 raw_snapshot=read_bytes(request['snapshot_path'],MAX_SNAPSHOT)
 if hashlib.sha256(raw_snapshot).hexdigest()!=request['snapshot_sha256']:raise MaterialError('material_snapshot_changed')
 snapshot=parse_json(raw_snapshot)
 if snapshot.get('schema')=='crowd-participant-pro-material-snapshot-v1':
  pro_snapshot_module(request['runtime_root'],request.get('pro_snapshot_sha256'))
  if 'comment_receipts'in snapshot:pro_comments_module(request['runtime_root'],request.get('pro_comments_sha256'))
 if 'toolbox'in sys.modules:raise MaterialError('toolbox_already_imported')
 sys.path.insert(0,str(root))
 import toolbox
 from toolbox.manifest import Manifest
 from toolbox.storage import SqliteStorage
 from toolbox.pack_schema import load_pack
 from toolbox.consumer import Consumer,render
 if toolbox.__version__!='0.5.1'or not Path(toolbox.__file__).resolve().is_relative_to(root.resolve()):raise MaterialError('toolbox_import_mismatch')
 output=Path(request['output']).absolute()
 # Safely re-open actual persisted data; Consumer.current independently reruns
 # exact RAW/ODS/DW/audit bindings and report bytes for every request.
 mfpath=output/'manifest.yaml';read_bytes(mfpath,65536)
 manifest=Manifest.load(mfpath);store=output/'packs';packid=manifest.ontology['packs'][0];contract=load_pack(store,packid)
 expected_pack={'pack.yaml','fields.yaml','pointers.json','validation.yaml','rubric.yaml','expectations.yaml'}
 if type(request.get('pack_sha256'))is not dict or set(request['pack_sha256'])!=expected_pack:raise MaterialError('material_pack_invalid')
 installed_pack=store/'packs'/contract.pack_id/contract.version
 for name in expected_pack:
  if hashlib.sha256(read_bytes(installed_pack/name,MAX_SNAPSHOT)).hexdigest()!=request['pack_sha256'][name]:raise MaterialError('material_pack_changed')
 # pack_path and runtime_root/runtime_cloud_sha256 are build-only provenance;
 # read trusts exact installed six-file pack bytes, not a mutable source path.
 result=read_json(output/'result.json',65536)
 if result.get('snapshot_sha256')!=request['snapshot_sha256']or result.get('as_of')!=request['as_of']:raise MaterialError('material_read_binding_changed')
 dbpath=output/manifest.storage['path'];read_bytes(dbpath,64*1024*1024);db=SqliteStorage(dbpath,read_only=True)
 try:data=Consumer(manifest,contract,db,request['as_of']).current()
 finally:db.close()
 if type(result.get('items'))is not int or len(data['items'])!=result['items']:raise MaterialError('material_count_mismatch')
 expected_project,_,expected_records=snapshot_publication_scope(snapshot)
 if manifest.project_id!=expected_project or {x['identity']['source_record_id']:x['metadata']['capture']for x in data['items']}!=expected_records:raise MaterialError('material_delivery_mapping_changed')
 if fmt=='html':return render(data).encode('utf-8')
 if fmt=='json':return json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
 if fmt=='jsonl':return ''.join(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n'for x in data['items']).encode()
 if fmt=='csv':
  buffer=io.StringIO();writer=csv.DictWriter(buffer,fieldnames=['source_record_id','score_domain','restaurant_taste_score','record']);writer.writeheader()
  for row in data['items']:writer.writerow({'source_record_id':row['identity']['source_record_id'],'score_domain':'material_traceability_only','restaurant_taste_score':'','record':json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)})
  return buffer.getvalue().encode()
 raise MaterialError('material_format_invalid')

def pack_info(request):
 # Read-only metadata is parsed only by the already configured toolbox Python.
 root=pin_source(request['toolbox_root'],request['toolbox_pins'])
 pack=Path(request['pack_path']).absolute();names={'pack.yaml','fields.yaml','pointers.json','validation.yaml','rubric.yaml','expectations.yaml'}
 if set(p.name for p in pack.iterdir())!=names or type(request.get('pack_sha256'))is not dict or set(request['pack_sha256'])!=names:raise MaterialError('material_pack_invalid')
 raw={name:read_bytes(pack/name,MAX_SNAPSHOT)for name in names}
 if any(hashlib.sha256(blob).hexdigest()!=request['pack_sha256'][name]for name,blob in raw.items()):raise MaterialError('material_pack_changed')
 if 'toolbox'in sys.modules:raise MaterialError('toolbox_already_imported')
 sys.path.insert(0,str(root))
 import toolbox,yaml
 if toolbox.__version__!='0.5.1'or not Path(toolbox.__file__).resolve().is_relative_to(root.resolve()):raise MaterialError('toolbox_import_mismatch')
 parsed={name.split('.')[0]:json.loads(blob)if name=='pointers.json'else yaml.safe_load(blob)for name,blob in raw.items()}
 meta=parsed['pack']['pack']
 return {'pack_id':meta['pack_id'],'version':meta['version'],'hash':hashlib.sha256(json.dumps(parsed,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()}

def main():
 p=argparse.ArgumentParser();p.add_argument('--request',required=True);p.add_argument('--action',choices=['build','read','build-jobs','pack-info'],default='build');p.add_argument('--format',choices=['html','json','jsonl','csv'],default='json');p.add_argument('--job-id');a=p.parse_args();req=read_json(a.request,65536)
 base={'snapshot_path','snapshot_sha256','toolbox_root','toolbox_pins','pack_path','pack_sha256','output','as_of','runtime_root','runtime_cloud_sha256'}
 if type(req)is not dict or set(req)not in (base,base|{'pro_snapshot_sha256'},base|{'pro_snapshot_sha256','pro_comments_sha256'}):raise MaterialError('material_request_invalid')
 if (a.action=='build-jobs')!=(a.job_id is not None):raise MaterialError('material_job_id_required')
 if a.action=='pack-info':print(json.dumps(pack_info(req),sort_keys=True))
 elif a.action=='read':sys.stdout.buffer.write(read_publication(req,a.format))
 else:
  result=run(**req,job_id=a.job_id);print(json.dumps({k:result[k]for k in ['state','items','coverage','source_calls','budget_debits','snapshot_sha256','html','json','jsonl','csv']},ensure_ascii=False))
if __name__=='__main__':
 try:main()
 except Exception as error:
  # Fixed class only: upstream exceptions may contain local paths or source text.
  sys.stderr.write(('material_rejected' if isinstance(error,(ValueError,OSError)) else 'material_failed')+'\n');raise SystemExit(2)from None
