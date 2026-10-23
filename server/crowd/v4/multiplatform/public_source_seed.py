"""Public WB observations only. Never copies a profile, whole DB or credential table."""
import contextlib,fcntl,hashlib,json,os,re,sqlite3,stat,uuid
from pathlib import Path
class SeedError(ValueError):pass
TOPIC={'id','nickname','creator_hash','add_ts','last_modify_ts','note_id','content','create_time','create_date_time','liked_count','comments_count','shared_count','note_url','image_list','video_url','source_keyword'}
COMMENT={'id','nickname','creator_hash','add_ts','last_modify_ts','comment_id','note_id','content','create_time','create_date_time','sub_comment_count','parent_comment_id','like_count'}
DERIVED={'id','add_ts','last_modify_ts'}
def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(v):return hashlib.sha256(canonical(v).encode()).hexdigest()
def rawsha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def safe(p):
 p=Path(p)
 if not p.is_absolute() or any(x.is_symlink() for x in (p,*p.parents)):raise SeedError('seed_path_invalid')
 return p

def read_object(p,limit=3_000_000):
 p=safe(p);fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 try:
  before=os.fstat(fd)
  if not stat.S_ISREG(before.st_mode) or before.st_size>limit:raise SeedError('seed_file_invalid')
  raw=os.read(fd,limit+1);after=os.fstat(fd)
  if len(raw)!=before.st_size or (before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns):raise SeedError('seed_file_changed')
  try:v=json.loads(raw)
  except (ValueError,UnicodeError,RecursionError):raise SeedError('seed_file_invalid') from None
  if not isinstance(v,dict):raise SeedError('seed_file_invalid')
  return v,hashlib.sha256(raw).hexdigest()
 finally:os.close(fd)

def build_seed(source_run,account_context,expected):
 """Read only exact finalized public sources; return no authentication values."""
 run=safe(source_run)
 try:rid=str(uuid.UUID(run.name))
 except ValueError:raise SeedError('seed_run_invalid') from None
 if rid!=run.name:raise SeedError('seed_run_invalid')
 if set(expected)!={'manifest_sha256','status_sha256','pagination_sha256','normalized_sha256'}:raise SeedError('seed_pin_invalid')
 manifest,mh=read_object(run/'manifest.json');status,sh=read_object(run/'status.json');pages,ph=read_object(run/'pro-pagination.json');normalized,nh=read_object(run/'normalized.json')
 if (mh,sh,ph,nh)!=(expected['manifest_sha256'],expected['status_sha256'],expected['pagination_sha256'],expected['normalized_sha256']):raise SeedError('seed_source_changed')
 q=manifest['request'];sid=q.get('session_id')
 if (manifest.get('run_id')!=rid or q.get('platform')!='wb' or q.get('source_executor')!='pro' or q.get('mode')!='detail' or q.get('comments') is not True or q.get('replies') is not True or type(q.get('max_comments')) is not int or q['max_comments']<1 or len(q.get('targets',[]))!=1):raise SeedError('seed_request_unsupported')
 if status.get('state')!='failed' or status.get('exit_code')!=74 or status.get('failure_reason')!='wb_embedded_replies_incomplete':raise SeedError('seed_source_not_known_failed')
 if (not isinstance(account_context,dict) or set(account_context)!={'session_id','generation','account_ref'} or account_context.get('session_id')!=sid or type(account_context.get('generation')) is not int or account_context['generation']<1 or not isinstance(account_context.get('account_ref'),str) or not re.fullmatch('[a-f0-9]{64}',account_context['account_ref'])):raise SeedError('seed_account_invalid')
 page_body={k:v for k,v in pages.items() if k!='sha256'}
 if pages.get('sha256')!=digest(page_body) or pages.get('operation_id')!=rid or pages.get('platform')!='wb' or pages.get('invalid') is not False:raise SeedError('seed_page_invalid')
 roots=[p for p in pages.get('pages',[]) if p.get('scope')=='root']
 if len(roots)!=1:raise SeedError('seed_root_window_unsupported')
 page=roots[0]
 if page.get('cursor_in')!=[-1,0] or page.get('checkpoint_committed') is not False or page.get('saved') is not True or not isinstance(page.get('ids'),list) or not page['ids'] or len(set(page['ids']))!=len(page['ids']):raise SeedError('seed_root_page_invalid')
 selected=page['ids'][:q['max_comments']]
 db=safe(run/'pro-observations.sqlite3');before={str(p):rawsha(p) for p in (db,Path(str(db)+'-wal')) if p.exists()};rows=[]
 with contextlib.closing(sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)) as c:
  c.execute('PRAGMA query_only=ON')
  for platform,kind,identity,raw in c.execute('SELECT platform,kind,entity_id,payload FROM vox_crawl_observation WHERE operation_id=? ORDER BY kind,entity_id',(rid,)):
   if platform!='wb' or kind not in ('topic','comment') or len(raw)>1_000_000 or len(rows)>=2000:raise SeedError('seed_observation_invalid')
   try:payload=json.loads(raw)
   except (ValueError,UnicodeError,RecursionError):raise SeedError('seed_observation_invalid') from None
   allowed=TOPIC if kind=='topic' else COMMENT
   if not isinstance(payload,dict) or set(payload)!=allowed or str(payload.get('note_id' if kind=='topic' else 'comment_id'))!=identity:raise SeedError('seed_public_projection_invalid')
   if any(isinstance(v,(dict,list)) or v is not None and type(v) not in (str,int) for v in payload.values()):raise SeedError('seed_public_projection_invalid')
   rows.append({'kind':kind,'entity_id':identity,'payload':payload,'source_observation_sha256':digest(payload)})
 if before!={str(p):rawsha(p) for p in (db,Path(str(db)+'-wal')) if p.exists()}:raise SeedError('seed_database_changed')
 topics=[r for r in rows if r['kind']=='topic'];comments={r['entity_id']:r for r in rows if r['kind']=='comment'}
 if len(topics)!=1 or str(topics[0]['entity_id'])!=page.get('content_id') or any(v not in comments for v in page['ids']):raise SeedError('seed_page_binding_invalid')
 root_rows=[comments[v] for v in page['ids']]
 for row in root_rows:
  p=row['payload']
  if str(p['note_id'])!=page['content_id'] or str(p.get('parent_comment_id') or '') not in ('','0',row['entity_id']):raise SeedError('seed_parent_invalid')
 embedded=[r for r in rows if r['kind']=='comment' and str(r['payload'].get('parent_comment_id')) in selected and r['entity_id'] not in selected]
 norm_records=normalized.get('records')
 if normalized.get('run_id')!=rid or not isinstance(norm_records,list):raise SeedError('seed_normalized_invalid')
 norm_map={}
 for record in norm_records:
  if not isinstance(record,dict) or record.get('kind') not in ('content','comment') or not isinstance(record.get('origin'),dict):raise SeedError('seed_normalized_invalid')
  key=('topic',str(record.get('content_id'))) if record['kind']=='content' else ('comment',str(record.get('comment_id')))
  if key in norm_map:raise SeedError('seed_normalized_invalid')
  norm_map[key]=record
 for row in [topics[0]]+[r for r in root_rows if r['entity_id'] in selected]+embedded:
  record=norm_map.get((row['kind'],row['entity_id']))
  if record is None or record['origin'].get('run_id')!=rid or record['origin'].get('observation_sha256')!=row['source_observation_sha256']:raise SeedError('seed_normalized_binding_invalid')
  row['normalized_record']=record
 body={'schema':'crowd-wb-public-continuation-seed-v1','source_run_id':rid,'source_session_id':sid,'account_context':account_context,'source_pins':expected,'request_sha256':digest(q),'source_observation_count':len(rows),'content_id':page['content_id'],'topic':topics[0],'root_page':page,'raw_root_rows':root_rows,'selected_root_ids':selected,'embedded_rows':embedded,'fresh_source_requests':0,'new_capture_eligible':False,'historical_subject_continuity_proven':False}
 if len(canonical(body).encode())>2_900_000:raise SeedError('seed_size_limit')
 return {**body,'seed_sha256':digest(body)}

def validate_seed(seed):
 if not isinstance(seed,dict) or seed.get('schema')!='crowd-wb-public-continuation-seed-v1' or seed.get('new_capture_eligible') is not False:raise SeedError('seed_invalid')
 if seed.get('seed_sha256')!=digest({k:v for k,v in seed.items() if k!='seed_sha256'}):raise SeedError('seed_changed')
 return seed

def matching_reuse(seed,kind,identity,new_raw):
 """Only explicitly cached reads may call this; fresh HTTP must never be ID-skipped."""
 validate_seed(seed)
 candidates=__import__('public_source_progress').candidates(seed)
 matches=[r for r in candidates if r['kind']==kind and r['entity_id']==identity]
 if len(matches)!=1 or not isinstance(new_raw,dict):raise SeedError('seed_reuse_not_bound')
 old=matches[0]
 if canonical({k:v for k,v in old['payload'].items() if k not in DERIVED})!=canonical({k:v for k,v in new_raw.items() if k not in DERIVED}):raise SeedError('seed_reuse_changed')
 return {'source_kind':'reused_previous_attempt','source_run_id':old['normalized_record']['origin']['run_id'],'source_observation_sha256':old['source_observation_sha256'],'source_record_hash':old['normalized_record'].get('record_hash'),'readback_observation_sha256':digest(new_raw),'seed_sha256':seed['seed_sha256'],'kind':kind,'entity_id':identity,'new_capture_eligible':False}

class ReuseJournal:
 """Explicit cached-store provenance; fresh HTTP writes clear matching row marks."""
 def __init__(self,new_run,seed,existing_only=False):
  validate_seed(seed);self.run=safe(new_run);self.seed=seed
  try:rid=str(uuid.UUID(self.run.name))
  except ValueError:raise SeedError('seed_run_invalid') from None
  if rid!=self.run.name or rid==seed['source_run_id'] or not self.run.is_dir():raise SeedError('seed_run_invalid')
  self.path=safe(self.run/'source-reuse.sqlite3')
  if existing_only and not self.path.is_file():raise SeedError('seed_journal_missing')
  with self.connection() as db:
   db.executescript('CREATE TABLE IF NOT EXISTS binding(new_run_id TEXT,seed_sha256 TEXT,source_run_id TEXT);CREATE TABLE IF NOT EXISTS reused(kind TEXT,entity_id TEXT,readback_sha256 TEXT,metadata TEXT,PRIMARY KEY(kind,entity_id));CREATE TABLE IF NOT EXISTS pending_store(kind TEXT,entity_id TEXT,token TEXT,mode TEXT,PRIMARY KEY(kind,entity_id));')
   binding=list(db.execute('SELECT * FROM binding'))
   expected=(rid,seed['seed_sha256'],seed['source_run_id'])
   if not binding:db.execute('INSERT INTO binding VALUES(?,?,?)',expected)
   elif binding!=[expected]:raise SeedError('seed_journal_binding_invalid')
  self.path.chmod(0o600)
 @contextlib.contextmanager
 def connection(self):
  safe(self.path)
  db=sqlite3.connect(self.path,timeout=2)
  db.execute('PRAGMA synchronous=FULL')
  try:
   with db:yield db
  finally:db.close()
 def begin_store(self,kind,identity,mode):
  if kind not in ('topic','comment') or not isinstance(identity,str) or not re.fullmatch('[1-9][0-9]{0,29}',identity) or mode not in ('cached','fresh'):raise SeedError('seed_identity_invalid')
  if mode=='cached':
   candidates=__import__('public_source_progress').candidates(self.seed)
   if not any(r['kind']==kind and r['entity_id']==identity for r in candidates):raise SeedError('seed_reuse_not_bound')
  token=str(uuid.uuid4())
  with self.connection() as db:
   db.execute('BEGIN IMMEDIATE')
   if db.execute('SELECT 1 FROM pending_store WHERE kind=? AND entity_id=?',(kind,identity)).fetchone():raise SeedError('seed_store_unknown')
   db.execute('INSERT INTO pending_store VALUES(?,?,?,?)',(kind,identity,token,mode))
  return token
 def begin_cached(self,kind,identity):return self.begin_store(kind,identity,'cached')
 def begin_fresh(self,kind,identity):return self.begin_store(kind,identity,'fresh')
 def complete_store(self,kind,identity,new_raw,token,mode):
  if not isinstance(new_raw,dict):raise SeedError('seed_readback_invalid')
  value=matching_reuse(self.seed,kind,identity,new_raw) if mode=='cached' else None
  with self.connection() as db:
   db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT token,mode FROM pending_store WHERE kind=? AND entity_id=?',(kind,identity)).fetchone()
   if row!=(token,mode):raise SeedError('seed_store_token_invalid')
   if value is not None:db.execute('INSERT OR REPLACE INTO reused VALUES(?,?,?,?)',(kind,identity,digest(new_raw),canonical(value)))
   else:db.execute('DELETE FROM reused WHERE kind=? AND entity_id=?',(kind,identity))
   db.execute('DELETE FROM pending_store WHERE kind=? AND entity_id=?',(kind,identity))
  return value
 def complete_cached(self,kind,identity,new_raw,token):return self.complete_store(kind,identity,new_raw,token,'cached')
 def complete_fresh(self,kind,identity,new_raw,token):return self.complete_store(kind,identity,new_raw,token,'fresh')
 def mark_cached(self,*args):raise SeedError('seed_store_intent_required')
 def clear_fresh(self,*args):raise SeedError('seed_store_intent_required')
 def lookup(self,kind,identity,observation_sha256):
  with self.connection() as db:
   if db.execute('SELECT 1 FROM pending_store WHERE kind=? AND entity_id=?',(kind,identity)).fetchone():raise SeedError('seed_store_unknown')
   row=db.execute('SELECT readback_sha256,metadata FROM reused WHERE kind=? AND entity_id=?',(kind,identity)).fetchone()
  if not row:return None
  if row[0]!=observation_sha256:raise SeedError('seed_observation_without_fresh_marker')
  value=json.loads(row[1])
  if value.get('seed_sha256')!=self.seed['seed_sha256'] or value.get('readback_observation_sha256')!=observation_sha256:raise SeedError('seed_journal_changed')
  return value
 def split_records(self,records):
  """Return fresh capture candidates and old-source records separately, without mutation."""
  import copy
  with self.connection() as db:
   if db.execute('SELECT 1 FROM pending_store LIMIT 1').fetchone():raise SeedError('seed_store_unknown')
  fresh=[];reused=[];evidence=[]
  for original in records:
   record=copy.deepcopy(original);kind='topic' if record.get('kind')=='content' else 'comment' if record.get('kind')=='comment' else None
   if kind is None:raise SeedError('seed_record_kind_invalid')
   identity=record.get('content_id') if kind=='topic' else record.get('comment_id');origin=record.get('origin')
   if not isinstance(origin,dict) or origin.get('run_id')!=self.run.name or origin.get('operation_id')!=self.run.name:raise SeedError('seed_record_run_invalid')
   metadata=self.lookup(kind,str(identity),origin.get('observation_sha256'))
   if metadata is None:fresh.append(record);continue
   candidates=__import__('public_source_progress').candidates(self.seed)
   old=next((r for r in candidates if r['kind']==kind and r['entity_id']==str(identity)),None)
   if old is None or 'normalized_record' not in old:raise SeedError('seed_normalized_binding_invalid')
   reused.append(copy.deepcopy(old['normalized_record']));evidence.append({**metadata,'readback_run_id':self.run.name})
  return {'fresh_records':fresh,'reused_previous_attempt_records':reused,'reuse_evidence':evidence}
