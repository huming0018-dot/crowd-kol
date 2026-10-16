"""Read a pinned existing CTFS publication through its original Consumer gate."""
from pathlib import Path
import argparse,csv,hashlib,io,json,re,sys
from material_bridge import read_bytes,read_json,pin_source,MaterialError
KEYS={'toolbox_root','toolbox_pins','toolbox_pins_sha256','manifest_path','manifest_sha256','pack_root','pack_sha256','project_id','report_hash','as_of'}
PACK_FILES={'pack.yaml','fields.yaml','pointers.json','validation.yaml','rubric.yaml','expectations.yaml'}

def read_publication(request,fmt):
 if type(request)is not dict or set(request)!=KEYS:raise MaterialError('publication_request_invalid')
 if any(type(request[k])is not str for k in KEYS-{'pack_sha256'}):raise MaterialError('publication_request_invalid')
 if any(re.fullmatch('[a-f0-9]{64}',request[k])is None for k in ('manifest_sha256','report_hash','toolbox_pins_sha256')):raise MaterialError('publication_request_invalid')
 root=pin_source(request['toolbox_root'],request['toolbox_pins'],request['toolbox_pins_sha256'])
 if 'toolbox'in sys.modules:raise MaterialError('toolbox_already_imported')
 sys.path.insert(0,str(root))
 import toolbox,yaml
 from toolbox.manifest import Manifest
 from toolbox.pack_schema import load_pack
 from toolbox.storage_factory import make_storage
 from toolbox.consumer import Consumer,render
 from toolbox.bindings import digest
 if toolbox.__version__!='0.5.1'or not Path(toolbox.__file__).resolve().is_relative_to(root.resolve()):raise MaterialError('toolbox_import_mismatch')
 path=Path(request['manifest_path']).absolute();blob=read_bytes(path,65536)
 if hashlib.sha256(blob).hexdigest()!=request['manifest_sha256']:raise MaterialError('publication_manifest_changed')
 expected=yaml.safe_load(blob);manifest=Manifest.load(path)
 # Bind all fields used by the original Manifest to the same verified bytes.
 expected={'schemaVersion':expected['schemaVersion'],'project_id':expected['project']['project_id'],'domain':expected['project']['domain'],'region':expected['project']['region'],**{k:expected.get(k,{})for k in ('storage','pipelines','raw','crawler','ontology')}}
 if manifest.to_dict()!=expected or manifest.project_id!=request['project_id']:raise MaterialError('publication_project_changed')
 if manifest.storage.get('backend')!='sqlite':raise MaterialError('publication_local_storage_required')
 packs=manifest.ontology.get('packs',[])
 if type(packs)is not list or len(packs)!=1:raise MaterialError('publication_pack_invalid')
 contract=load_pack(Path(request['pack_root']),packs[0]);pins=request['pack_sha256']
 if type(pins)is not dict or set(pins)!=PACK_FILES:raise MaterialError('publication_pack_invalid')
 installed=Path(request['pack_root'])/'packs'/contract.pack_id/contract.version
 for name,sha in pins.items():
  if type(sha)is not str or hashlib.sha256(read_bytes(installed/name,8*1024*1024)).hexdigest()!=sha:raise MaterialError('publication_pack_changed')
 read_bytes(path.parent/manifest.storage['path'],64*1024*1024)
 storage=make_storage(manifest.to_dict(),manifest.path.parent,read_only=True)
 try:data=Consumer(manifest,contract,storage,request['as_of']).current()
 finally:storage.close()
 if digest(data)!=request['report_hash']:raise MaterialError('publication_changed')
 if fmt=='html':return render(data).encode()
 if fmt=='json':return json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
 if fmt=='jsonl':return ''.join(json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n'for row in data['items']).encode()
 if fmt=='csv':
  stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=['project_id','source_record_id','record']);writer.writeheader()
  for row in data['items']:writer.writerow({'project_id':data['project_id'],'source_record_id':row['identity']['source_record_id'],'record':json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)})
  return stream.getvalue().encode()
 raise MaterialError('publication_format_invalid')

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--request',required=True);parser.add_argument('--action',choices=['read'],default='read');parser.add_argument('--format',choices=['html','json','jsonl','csv'],default='html');args=parser.parse_args();sys.stdout.buffer.write(read_publication(read_json(args.request,65536),args.format))
if __name__=='__main__':
 try:main()
 except Exception as error:
  sys.stderr.write(('publication_rejected'if isinstance(error,(ValueError,OSError,TypeError,KeyError,RecursionError))else'publication_failed')+'\n');raise SystemExit(2)from None
