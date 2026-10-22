"""One verified native_saved row set -> four lossless component exports.

No acquisition, task, score, pack, Consumer publication or cloud request. The
caller supplies the prepared payload and its actual Owner GET result. JSONL and
CSV provenance is bound by the common manifest; typed row envelopes are intact.
"""
from pathlib import Path
from html.parser import HTMLParser
import argparse,csv,hashlib,html,io,json,os,re,stat
from urllib.parse import urlsplit
from owner_native_saved import FIELDS,SCHEMA,canonical,digest,validate_receipt,MAX_PAYLOAD

EXPORT_SCHEMA='crowd-native-saved-export-v1'
MAX_EXPORT=8*1024*1024
def require(ok):
 if not ok:raise ValueError('native_export_invalid')
def dumps(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def loads(raw):
 def pairs(items):
  result={}
  for key,value in items:
   require(key not in result);result[key]=value
  return result
 return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:require(False))
def validated(value,owner_get):
 validate_receipt(owner_get,value,content=True)
 require(type(value)is dict and set(value)=={'schema','idempotency_key','source','records'}and value['schema']==SCHEMA)
 source=value['source'];require(type(source)is dict and set(source)=={'platform','kind','sdk_commit','snapshot_sha256'}and source['platform']=='xiaohongshu'and source['kind']=='mediacrawler_pro_native_sqlite')
 require(re.fullmatch('[a-f0-9]{40}',source['sdk_commit'])is not None and re.fullmatch('[a-f0-9]{64}',source['snapshot_sha256'])is not None)
 require(len(canonical(value).encode())<=MAX_PAYLOAD)
 records=value['records'];require(type(records)is list and 1<=len(records)<=1000);seen=set();notes=[];parents={}
 for envelope in records:
  require(type(envelope)is dict and set(envelope)=={'native_table','native_id','record','native_row_sha256','url_redaction','record_sha256'})
  table=envelope['native_table'];require(type(table)is str and table in FIELDS);row=envelope['record'];nid=envelope['native_id'];require(type(nid)is str and re.fullmatch('[A-Za-z0-9_.:-]{1,200}',nid)is not None)
  require((table,nid)not in seen);seen.add((table,nid));require(type(row)is dict and set(row)==set(FIELDS[table]))
  require(all(type(v)in(str,int,type(None))and(type(v)is not int or abs(v)<=9007199254740991)for v in row.values()))
  require(row['note_id']and row['note_url']);url=urlsplit(row['note_url']);require(url.scheme=='https'and url.hostname in('www.xiaohongshu.com','m.xiaohongshu.com')and not url.query and not url.fragment and not url.username and not url.password and not url.port and url.path.rstrip('/')=='/explore/'+row['note_id'])
  key='note_id'if table=='xhs_note'else'comment_id';require(row[key]==nid)
  require(type(envelope['native_row_sha256'])is str and re.fullmatch('[a-f0-9]{64}',envelope['native_row_sha256'])is not None)
  require(envelope['record_sha256']==digest('crowd-owner-native-record-v1\n'+canonical({k:envelope[k]for k in('native_table','native_id','record')})))
  red=envelope['url_redaction'];require(type(red)is dict and set(red)=={'field','original_url_sha256','removed_query_keys','removed_fragment'}and red['field']=='note_url'and type(red['removed_fragment'])is bool and re.fullmatch('[a-f0-9]{64}',red['original_url_sha256'])is not None and type(red['removed_query_keys'])is list)
  require(all(type(k)is str and re.fullmatch('[A-Za-z0-9_]{1,64}',k)is not None for k in red['removed_query_keys']));require(red['removed_query_keys']==sorted(set(red['removed_query_keys'])))
  if table=='xhs_note':notes.append(nid)
  else:parents[nid]=row['parent_comment_id']
 require(len(notes)==1 and all(e['record']['note_id']==notes[0]for e in records))
 for cid,parent in parents.items():
  require(parent in('',None)or type(parent)is str and parent in parents and parent!=cid);visited=set();cursor=cid
  while cursor not in('',None):require(cursor not in visited);visited.add(cursor);cursor=parents[cursor]
 # JSON copying keeps the input and Owner receipt immutable for every renderer.
 return loads(dumps(records)),{'schema':EXPORT_SCHEMA,'source':loads(dumps(source)),'idempotency_key':value['idempotency_key'],'receipt':loads(dumps(owner_get['native_saved'])),'record_count':len(records),'source_kind':'native_saved','reward_eligible':False,'participant_capture':False,'domain_score':None,'url_redaction':'note_url query/fragment removed explicitly; other native typed fields retained'}
def formats(value,owner_get):
 rows,provenance=validated(value,owner_get)
 buf=io.StringIO(newline='');writer=csv.DictWriter(buf,fieldnames=['native_table','native_id','record_sha256','record']);writer.writeheader()
 for row in rows:writer.writerow({**{key:row[key]for key in('native_table','native_id','record_sha256')},'record':dumps(row)})
 esc=lambda v:html.escape(v,quote=True)
 parts=['<!doctype html><html lang="zh"><meta charset="utf-8"><title>Pro 原生数据导出</title><style>pre{white-space:pre-wrap;overflow-wrap:anywhere}body{max-width:1100px;margin:auto;padding:24px}article{border-top:1px solid #bbb;padding:16px}dt{font-weight:bold}</style><body><h1>Pro 原生数据导出</h1><p>仅原生数据与中央 Owner 入库回执；不代表参与者奖励、知识审核或领域评价。</p><details><summary>来源及中央回执</summary><pre id="provenance">'+esc(dumps(provenance))+'</pre></details>']
 for row in rows:
  parts.append('<article><h2>'+esc(row['native_table']+' / '+row['native_id'])+'</h2><dl>')
  for key,v in row['record'].items():parts.append('<dt>'+esc(key)+'</dt><dd><pre>'+esc(v if type(v)is str else dumps(v))+'</pre></dd>')
  parts.append('</dl><details><summary>完整 typed 原始行及哈希</summary><pre data-native-record="1">'+esc(dumps(row))+'</pre></details></article>')
 parts.append('</body></html>')
 return {'json':(dumps({'schema':EXPORT_SCHEMA,'provenance':provenance,'records':rows})+'\n').encode(),'jsonl':(''.join(dumps(row)+'\n'for row in rows)).encode(),'csv':buf.getvalue().encode(),'html':''.join(parts).encode()}
class _RecordsParser(HTMLParser):
 def __init__(self):super().__init__(convert_charrefs=True);self.records=[];self.active=False;self.parts=[]
 def handle_starttag(self,tag,attrs):
  if tag=='pre'and dict(attrs).get('data-native-record')=='1':require(not self.active);self.active=True;self.parts=[]
 def handle_data(self,data):
  if self.active:self.parts.append(data)
 def handle_endtag(self,tag):
  if tag=='pre'and self.active:self.records.append(loads(''.join(self.parts)));self.active=False
def parse_records(fmt,body):
 require(type(body)is bytes and len(body)<=MAX_EXPORT)
 text=body.decode('utf8')
 if fmt=='json':return loads(text)['records']
 if fmt=='jsonl':return [loads(line)for line in text.splitlines()]
 if fmt=='csv':
  old=csv.field_size_limit()
  try:
   csv.field_size_limit(MAX_EXPORT);result=[]
   for row in csv.DictReader(io.StringIO(text,newline='')):
    record=loads(row['record']);require(all(row[k]==record[k]for k in('native_table','native_id','record_sha256')));result.append(record)
   return result
  finally:csv.field_size_limit(old)
 if fmt=='html':
  parser=_RecordsParser();parser.feed(text);parser.close();require(not parser.active);return parser.records
 raise ValueError('native_export_format_invalid')
def _create(path,raw):
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'wb')as out:out.write(raw);out.flush();os.fsync(out.fileno())
def write_exports(value,owner_get,output,media_result=None):
 rows,provenance=validated(value,owner_get);content=formats(value,owner_get)
 for fmt,raw in content.items():require(parse_records(fmt,raw)==rows)
 output=Path(output);require(output.is_absolute()and not any(x.is_symlink()for x in(output,*output.parents)));output.mkdir(mode=0o700)
 manifest={'schema':EXPORT_SCHEMA,'batch_id':provenance['receipt']['batch_id'],'batch_hash':provenance['receipt']['batch_hash'],'snapshot_sha256':provenance['source']['snapshot_sha256'],'record_count':len(rows),'provenance':provenance,'cloud_media_bytes_saved':False,'local_media':[],'files':{}}
 if media_result is not None:
  require(media_result.get('pass')is True and media_result.get('source_unchanged')is True and media_result.get('snapshot_unchanged')is True and media_result.get('snapshot_sha256')==value['source']['snapshot_sha256'])
  for asset in media_result['assets']:
   keys=('bytes','sha256','format','width','height','pixel_sha256');require(all(k in asset for k in keys));require(type(asset['bytes'])is int and 0<asset['bytes']<=2097152 and all(type(asset[k])is int and asset[k]>0 for k in('width','height'))and asset['format']in('PNG','JPEG','WEBP'))
   require(all(type(asset[k])is str and re.fullmatch('[a-f0-9]{64}',asset[k])is not None for k in('sha256','pixel_sha256')));manifest['local_media'].append({k:asset[k]for k in keys}|{'storage':'local_only','cloud_saved':False})
 for fmt,raw in content.items():
  name='native.'+fmt;_create(output/name,raw);manifest['files'][name]=hashlib.sha256(raw).hexdigest()
 _create(output/'manifest.json',(dumps(manifest)+'\n').encode());fd=os.open(output,os.O_RDONLY);os.fsync(fd);os.close(fd);return manifest
def _read(path):
 path=Path(path);require(not any(x.is_symlink()for x in(path,*path.parents)));fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 with os.fdopen(fd,'rb')as stream:
  s=os.fstat(stream.fileno());require(stat.S_ISREG(s.st_mode)and s.st_uid==os.getuid()and not s.st_mode&0o077 and s.st_nlink==1 and 0<s.st_size<=MAX_EXPORT);return loads(stream.read(MAX_EXPORT+1))
def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--payload',required=True);parser.add_argument('--owner-get',required=True);parser.add_argument('--output',required=True);parser.add_argument('--local-media-result');args=parser.parse_args()
 media=None
 if args.local_media_result:
  media=_read(args.local_media_result);binding=_read(Path(args.local_media_result).with_name('INPUT.PRIVATE.json'));media={**media,'snapshot_sha256':binding['snapshot_sha256']}
 manifest=write_exports(_read(args.payload),_read(args.owner_get),Path(args.output).absolute(),media)
 print(dumps({k:manifest[k]for k in('batch_id','batch_hash','snapshot_sha256','record_count','files','cloud_media_bytes_saved')}))
if __name__=='__main__':main()
