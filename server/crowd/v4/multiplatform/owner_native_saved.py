"""Fixed saved Pro SQLite -> explicit Owner import. No collector, task or reward action."""
from pathlib import Path
from contextlib import closing
import fcntl,hashlib,json,os,re,sqlite3,stat,uuid
from urllib.parse import urlsplit,urlunsplit,parse_qsl
from cloud_sync import canonical,CloudError
from publication_pro_share import private_dir,create
from automatic_materials import private_json,write

SCHEMA='crowd-owner-native-saved-v1'
MAX_DB=32*1024*1024
MAX_PAYLOAD=262144
FIELDS={
 'xhs_note':('id','nickname','creator_hash','add_ts','last_modify_ts','note_id','type','title','desc','video_url','time','last_update_time','liked_count','collected_count','comment_count','share_count','image_list','tag_list','note_url','source_keyword'),
 'xhs_note_comment':('id','nickname','creator_hash','add_ts','last_modify_ts','comment_id','create_time','note_id','content','sub_comment_count','pictures','parent_comment_id','like_count','note_url','target_comment_id')}
def fail(reason):raise ValueError('native_saved_'+reason)
def digest(value):return hashlib.sha256(value.encode('utf8')if isinstance(value,str)else value).hexdigest()
def _file(path,private=False):
 p=Path(path)
 if any(x.is_symlink()for x in(p,*p.parents)):fail('source_path_invalid')
 s=p.stat()
 if not stat.S_ISREG(s.st_mode)or s.st_uid!=os.getuid()or s.st_nlink!=1 or s.st_mode&0o022 or private and s.st_mode&0o077 or not 0<s.st_size<=MAX_DB:fail('source_invalid')
 if private:
  wal=Path(str(p)+'-wal')
  if wal.is_symlink()or wal.exists()and wal.stat().st_size:fail('snapshot_changed')
 return p
def backup_sqlite(source,destination):
 source=_file(source);destination=Path(destination)
 if any(x.is_symlink()for x in(destination,*destination.parents)):fail('snapshot_path_invalid')
 fd=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);os.close(fd)
 # SQLite backup reads the committed WAL through a single read transaction; never cp/checkpoint source.
 with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True,isolation_level=None))as original:
  original.execute('pragma query_only=on');original.execute('begin');original.execute('select count(*)from sqlite_master').fetchone()
  with closing(sqlite3.connect(destination))as target:original.backup(target);target.commit()
  original.execute('rollback')
 _file(destination,True)
 fd=os.open(destination,os.O_RDONLY);os.fsync(fd);os.close(fd)
 fd=os.open(destination.parent,os.O_RDONLY);os.fsync(fd);os.close(fd)
 return {'snapshot_sha256':digest(destination.read_bytes()),'bytes':destination.stat().st_size}
def _identifier(value):
 if type(value)is not str or not re.fullmatch('[A-Za-z0-9_.:-]{1,200}',value):fail('native_id_invalid')
 return value
def _url(value,note_id):
 if type(value)is not str:fail('source_url_invalid')
 try:u=urlsplit(value);port=u.port
 except ValueError:fail('source_url_invalid')
 if u.scheme!='https'or u.hostname not in ('www.xiaohongshu.com','m.xiaohongshu.com')or u.username or u.password or port or u.path.rstrip('/')!='/explore/'+note_id:fail('source_url_invalid')
 names=sorted({k for k,_ in parse_qsl(u.query,keep_blank_values=True)})
 if any(not re.fullmatch('[A-Za-z0-9_]{1,64}',k)for k in names):fail('query_key_invalid')
 return urlunsplit((u.scheme,u.netloc,u.path,'','')),{'field':'note_url','original_url_sha256':digest(value),'removed_query_keys':names,'removed_fragment':bool(u.fragment)}
def _record(table,row,note_id):
 key='note_id'if table=='xhs_note'else'comment_id';native_id=_identifier(row[key]);public=dict(row)
 if any(type(v)not in(str,int,type(None))for v in row.values()):fail('native_type_invalid')
 for value in row.values():
  if type(value)is int and abs(value)>9007199254740991:fail('native_integer_invalid')
 public['note_url'],redaction=_url(row['note_url'],note_id)
 # All other native columns retain original values/types; URLs elsewhere must never carry credentials.
 for name,value in public.items():
  if type(value)is str and re.search(r'(?:cookie|authorization|access_token|refresh_token|private_key|xsec_token)\s*[=:]',value,re.I):fail('sensitive_record')
 raw_semantic={'native_table':table,'native_id':native_id,'record':row}
 semantic={'native_table':table,'native_id':native_id,'record':public}
 return {**semantic,'native_row_sha256':digest('crowd-owner-native-row-v1\n'+canonical(raw_semantic)),'url_redaction':redaction,'record_sha256':digest('crowd-owner-native-record-v1\n'+canonical(semantic))}
def prepare(snapshot,*,idempotency_key,sdk_commit,note_id):
 snapshot=_file(snapshot,True);note_id=_identifier(note_id)
 if type(idempotency_key)is not str or not 1<=len(idempotency_key)<=160 or any(ord(c)<32 or ord(c)==127 for c in idempotency_key):fail('key_invalid')
 if type(sdk_commit)is not str or not re.fullmatch('[a-f0-9]{40}',sdk_commit):fail('sdk_commit_invalid')
 before=digest(snapshot.read_bytes())
 with closing(sqlite3.connect(snapshot.as_uri()+'?mode=ro',uri=True))as db:
  db.execute('pragma query_only=on');db.row_factory=sqlite3.Row;rows={}
  for table,fields in FIELDS.items():
   if [x[1]for x in db.execute('pragma table_info('+table+')')]!=list(fields):fail('native_schema_invalid')
   rows[table]=[dict(x)for x in db.execute('select '+','.join('"'+k+'"'for k in fields)+' from '+table+' order by '+('note_id'if table=='xhs_note'else'comment_id')+' limit 1001')]
 notes=rows['xhs_note'];comments=rows['xhs_note_comment']
 if len(notes)!=1 or notes[0]['note_id']!=note_id or len(comments)>999:fail('native_counts_invalid')
 ids={_identifier(x['comment_id'])for x in comments}
 if len(ids)!=len(comments):fail('duplicate_native_id')
 parents={}
 for row in comments:
  if row['note_id']!=note_id:fail('foreign_note')
  parent=row['parent_comment_id']
  if parent not in ('',None)and(parent not in ids or parent==row['comment_id']):fail('parent_missing')
  parents[row['comment_id']]=parent
 for cid in ids:
  seen=set();parent=cid
  while parent not in ('',None):
   if parent in seen:fail('parent_cycle')
   seen.add(parent);parent=parents[parent]
 records=[_record('xhs_note',notes[0],note_id)]+[_record('xhs_note_comment',row,note_id)for row in comments]
 value={'schema':SCHEMA,'idempotency_key':idempotency_key,'source':{'kind':'mediacrawler_pro_native_sqlite','platform':'xiaohongshu','sdk_commit':sdk_commit,'snapshot_sha256':before},'records':records}
 if len(canonical(value).encode('utf8'))>MAX_PAYLOAD:fail('payload_limit')
 if digest(snapshot.read_bytes())!=before:fail('snapshot_changed')
 return value
def batch_hash(value):return digest('crowd-owner-native-batch-v1\n'+canonical(value))

ENDPOINT='https://bdwrhshgdeghgyzwpxnl.supabase.co/functions/v1/crowd-machine'
def validate_receipt(reply,value,content=False):
 if type(reply)is not dict or set(reply)!=({'native_saved','replayed','content'}if content else{'native_saved','replayed'})or type(reply['replayed'])is not bool:fail('receipt_invalid')
 r=reply['native_saved'];fields={'schema','batch_id','batch_hash','snapshot_sha256','record_count','record_hashes','redacted_fields','created_at','source_kind','reward_eligible'}
 if type(r)is not dict or set(r)!=fields or r.get('schema')!='crowd-owner-native-saved-receipt-v1' or r.get('source_kind')!='native_saved' or r.get('reward_eligible')is not False:fail('receipt_invalid')
 try:
  if str(uuid.UUID(r['batch_id']))!=r['batch_id']:fail('receipt_invalid')
 except (ValueError,TypeError,AttributeError):fail('receipt_invalid')
 if type(r['created_at'])is not str or not re.match(r'^\d{4}-\d\d-\d\d[T ]',r['created_at']):fail('receipt_invalid')
 expected_hashes=[{k:x[k]for k in('native_table','native_id','record_sha256')}for x in value['records']]
 expected_redacted=[{k:x[k]for k in('native_table','native_id')}|{'field':'note_url'}for x in value['records']]
 if r['batch_hash']!=batch_hash(value)or r['snapshot_sha256']!=value['source']['snapshot_sha256']or type(r['record_count'])is not int or r['record_count']!=len(value['records']):fail('receipt_mismatch')
 # Receipt arrays have no independent ordering authority; all identities/hashes must match exactly.
 order=lambda x:canonical(x)
 if type(r['record_hashes'])is not list or type(r['redacted_fields'])is not list or sorted(r['record_hashes'],key=order)!=sorted(expected_hashes,key=order)or sorted(r['redacted_fields'],key=order)!=sorted(expected_redacted,key=order):fail('receipt_mismatch')
 if content and canonical(reply['content'])!=canonical(value):fail('receipt_mismatch')
 return reply

class NativeSavedBridge:
 def __init__(self,client,journal_root,snapshot,*,snapshot_sha256,sdk_commit,note_id):
  if getattr(client,'role',None)!='owner'or getattr(client,'endpoint',None)!=ENDPOINT:fail('owner_authorization_required')
  if type(snapshot_sha256)is not str or not re.fullmatch('[a-f0-9]{64}',snapshot_sha256):fail('binding_invalid')
  self.client=client;self.folder=private_dir(Path(journal_root));self.snapshot=Path(snapshot);self.expected=snapshot_sha256;self.sdk_commit=sdk_commit;self.note_id=note_id
 def prepared(self,key):
  if digest(_file(self.snapshot,True).read_bytes())!=self.expected:fail('snapshot_changed')
  value=prepare(self.snapshot,idempotency_key=key,sdk_commit=self.sdk_commit,note_id=self.note_id)
  if value['source']['snapshot_sha256']!=self.expected:fail('snapshot_changed')
  return value
 def get(self,key):
  value=self.prepared(key);reply=self.client.call('native_saved_get',{'idempotency_key':key})
  return validate_receipt(reply,value,content=True)
 def put(self,key):
  value=self.prepared(key);h=batch_hash(value);name=digest(canonical({'endpoint':ENDPOINT,'owner_scope':'crowd-owner-main','idempotency_key':key}));path=self.folder/(name+'.json')
  fd=os.open(self.folder/(name+'.lock'),os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
  try:
   try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
   except BlockingIOError:fail('writer_busy')
   if path.exists()or path.is_symlink():
    row=private_json(path)
    if row.get('batch_hash')!=h or canonical(row.get('payload'))!=canonical(value):fail('idempotency_conflict')
    if row.get('state')=='recorded':return {'state':'recorded',**validate_receipt(row['reply'],value),'replayed':True}
    if row.get('state')!='attempted_no_retry':fail('journal_invalid')
    try:remote=self.get(key)
    except (CloudError,ValueError,OSError,TimeoutError):return {'state':'outcome_unknown','idempotency_key':key,'retry':False}
    reply={k:v for k,v in remote.items()if k!='content'}
   else:
    row={'state':'attempted_no_retry','payload':value,'batch_hash':h};create(path,row)
    try:reply=validate_receipt(self.client.call('native_saved_put',value),value)
    except (CloudError,ValueError,OSError,TimeoutError):return {'state':'outcome_unknown','idempotency_key':key,'retry':False}
   recorded={**row,'state':'recorded','reply':reply}
   try:
    write(path,recorded);parent=os.open(self.folder,os.O_RDONLY);os.fsync(parent);os.close(parent)
   except OSError:return {'state':'outcome_unknown','idempotency_key':key,'retry':False}
   return {'state':'recorded',**reply}
  finally:os.close(fd)

def dispatch(app,action,payload):
 # Only a server-owned protected descriptor chooses a source; browser never supplies path/hash/row data.
 if action not in ('native_saved_put','native_saved_get')or type(payload)is not dict or set(payload)!={'idempotency_key'}:fail('request_invalid')
 binding=private_json(Path(app.root)/'owner-native-saved.json')
 if type(binding)is not dict or set(binding)!={'schema','snapshot','snapshot_sha256','sdk_commit','note_id'}or binding['schema']!='crowd-owner-native-saved-binding-v1':fail('binding_invalid')
 bridge=NativeSavedBridge(app.cloud_client,Path(app.root)/'native-saved-import-intents',binding['snapshot'],snapshot_sha256=binding['snapshot_sha256'],sdk_commit=binding['sdk_commit'],note_id=binding['note_id'])
 return bridge.put(payload['idempotency_key'])if action=='native_saved_put'else bridge.get(payload['idempotency_key'])
