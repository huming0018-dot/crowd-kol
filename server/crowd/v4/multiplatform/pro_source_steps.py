"""Project current Pro durable readback into the existing source journal.
These are current readback observations, NEVER historical HTTP or cloud ACK claims.
"""
import contextlib,hashlib,json,os,re,sqlite3,stat,uuid
from pathlib import Path
from mc_source_steps import NativeSteps,canonical,digest,LIMIT
MAX_JSON=3_000_000

def safe_path(path):
 p=Path(path)
 if not p.is_absolute() or any(v.is_symlink() for v in (p,*p.parents)):
  raise ValueError('pro_steps_unsafe_path')
 return p

def safe_json(path):
 path=safe_path(path)
 try:fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 except FileNotFoundError:return None
 try:
  info=os.fstat(fd)
  if not stat.S_ISREG(info.st_mode) or not 0<info.st_size<=MAX_JSON:raise ValueError('pro_steps_invalid_document')
  raw=os.read(fd,MAX_JSON+1);after=os.fstat(fd)
  if len(raw)!=info.st_size or (info.st_size,info.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('pro_steps_document_changed')
  value=json.loads(raw)
  if not isinstance(value,dict):raise ValueError('pro_steps_invalid_document')
  return value
 except (UnicodeError,RecursionError,TypeError):raise ValueError('pro_steps_invalid_document') from None
 finally:os.close(fd)

def relation(platform,scope,entity,row,page,rows):
 from pro_executor import is_root_comment,reply_belongs_to
 key={'bili':'video_id','xhs':'note_id','dy':'aweme_id','wb':'note_id'}[platform]
 if str(row.get(key))!=page['content_id']:return False
 if platform=='bili':
  return is_root_comment(row) if scope=='root' else reply_belongs_to(entity,page['parent_id'],rows,page['content_id'])
 parent=str(row.get('parent_comment_id') or '')
 return parent in (('','0',entity) if platform=='wb' else ('','0')) if scope=='root' else parent==page['parent_id']

def project(run,manifest=None):
 run=safe_path(run);rid=str(uuid.UUID(run.name))
 manifest=safe_json(run/'manifest.json') if manifest is None else manifest
 if manifest is None:return {'facts_added':0,'readback_only':True}
 if not isinstance(manifest,dict):raise ValueError('pro_steps_manifest_binding')
 executor=manifest.get('executor')
 if not isinstance(executor,dict) or executor.get('backend')!='pro':return {'facts_added':0,'readback_only':True}
 request=manifest.get('request')
 if manifest.get('run_id')!=rid or not isinstance(request,dict):raise ValueError('pro_steps_manifest_binding')
 platform=request.get('platform')
 if platform not in ('bili','xhs','dy','wb'):raise ValueError('pro_steps_platform_unsupported')
 from pro_executor import DB_NAME,observations
 source=run/DB_NAME
 if not source.exists():return {'facts_added':0,'readback_only':True}
 safe_path(source)
 for suffix in ('-wal','-shm'):safe_path(run/(DB_NAME+suffix))
 # Mature reader validates operation_id, entity ID, platform, JSON shape and size.
 rows=observations(run,manifest)
 comments={identity:raw for kind,identity,raw in rows if kind=='comment'}
 topics={identity:raw for kind,identity,raw in rows if kind=='topic'}
 facts=[]
 for identity,raw in sorted(topics.items()):
  key=digest({'domain':'pro-current-durable-body-v1','operation':rid,'platform':platform,'entity':identity,'record':raw})
  facts.append((key,{'source_stage':'content_saved','scope':'content','saved_rows':1,'page_sha256':key}))
 doc=safe_json(run/'pro-pagination.json')
 if doc is not None:
  checksum=doc.get('sha256');body={k:v for k,v in doc.items() if k!='sha256'}
  if (type(doc.get('schema_version')) is not int or doc['schema_version']!=1 or doc.get('operation_id')!=rid
      or doc.get('platform',platform)!=platform or digest(body)!=checksum or doc.get('invalid') is not False
      or not isinstance(doc.get('pages'),list) or len(doc['pages'])>1000):raise ValueError('pro_steps_pagination_invalid')
  for index,page in enumerate(doc['pages']):
   if (not isinstance(page,dict) or page.get('scope') not in ('root','reply')
       or type(page.get('saved')) is not bool or type(page.get('checkpoint_committed')) is not bool
       or page.get('invalid',False) is not False or not isinstance(page.get('content_id'),str)
       or page['content_id'] not in topics or not isinstance(page.get('ids'),list)
       or len(page['ids'])>10000 or any(not isinstance(v,str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,200}',v) for v in page['ids'])
       or len(page['ids'])!=len(set(page['ids']))
       or page['scope']=='reply' and (not isinstance(page.get('parent_id'),str) or not page['parent_id'])):
    raise ValueError('pro_steps_page_invalid')
   # Exclude mutable saved/checkpoint flags and later reply metadata. Index is append order,
   # not historic request timing. Stable hash pairs received/readback across status calls.
   stable={k:page.get(k) for k in ('scope','content_id','parent_id','ids','cursor_in','cursor_out','pn','ps','embedded')}
   page_hash=digest({'domain':'pro-current-durable-page-v1','operation':rid,'platform':platform,'index':index,'page':stable})
   facts.append((page_hash+':received',{'source_stage':'page_received','scope':page['scope'],'saved_rows':0,'page_sha256':page_hash}))
   saved=[identity for identity in page['ids'] if identity in comments and relation(platform,page['scope'],identity,comments[identity],page,comments)]
   if saved:
    stage='page_saved' if len(saved)==len(page['ids']) else 'page_partially_saved'
    fact_key=digest({'page':page_hash,'stage':stage,'durable_ids':saved})
    facts.append((fact_key,{'source_stage':stage,'scope':page['scope'],'saved_rows':len(saved),'page_sha256':page_hash}))
 if not facts:return {'facts_added':0,'readback_only':True}
 path=safe_path(run/'mc-source-steps.sqlite3')
 for suffix in ('-wal','-shm'):safe_path(run/('mc-source-steps.sqlite3'+suffix))
 if path.exists() and (not path.is_file() or path.stat().st_size>10_000_000):raise ValueError('pro_steps_journal_invalid')
 owner=NativeSteps(run,rid,platform)
 if owner.error:raise ValueError('pro_steps_journal_unavailable')
 added=0
 try:
  with contextlib.closing(owner.connect()) as db:
   db.execute('BEGIN IMMEDIATE')
   db.execute('CREATE TABLE IF NOT EXISTS pro_source_facts(fact_key TEXT PRIMARY KEY,sequence INTEGER NOT NULL)')
   # Highest observed cumulative counter; responses may finish out of request order.
   # It is not a claimed correlation between this page and a particular request.
   attempts=db.execute("SELECT coalesce(max(json_extract(event,'$.api_attempts')),0) FROM events").fetchone()[0]
   if type(attempts) is not int or not 0<=attempts<=500:raise ValueError('pro_steps_journal_invalid')
   count=db.execute('SELECT count(*) FROM events').fetchone()[0]
   for fact,event in facts:
    if db.execute('SELECT 1 FROM pro_source_facts WHERE fact_key=?',(fact,)).fetchone():continue
    if count>=LIMIT:raise ValueError('pro_steps_limit')
    event.update(api_attempts=attempts,http_status=0,checkpoint_committed=False)
    sequence=db.execute('INSERT INTO events(event) VALUES(?)',(canonical(event),)).lastrowid
    db.execute('INSERT INTO pro_source_facts VALUES(?,?)',(fact,sequence));count+=1;added+=1
   db.commit()
 except (sqlite3.Error,OSError,RecursionError,TypeError,AttributeError):raise ValueError('pro_steps_journal_unavailable') from None
 return {'facts_added':added,'readback_only':True}
