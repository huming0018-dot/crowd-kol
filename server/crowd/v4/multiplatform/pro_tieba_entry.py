"""Own Tieba integration using existing SDK transactions/checkpoints and account state."""
import contextvars,hashlib,json,os,re,stat,uuid
from pathlib import Path
from pro_tieba_adapter import Detail,TiebaStop,self_proof,canonical,digest,numeric

MAX=3_000_000

def safe_path(path):
 path=Path(path).absolute()
 if any(x.is_symlink() for x in [path,*path.parents]):raise ValueError('tieba_evidence_path_unsafe')
 return path

def read_json(path):
 path=safe_path(path);fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 try:
  info=os.fstat(fd)
  if not stat.S_ISREG(info.st_mode) or not 0<info.st_size<=MAX:raise ValueError('tieba_evidence_invalid')
  raw=os.read(fd,MAX+1);after=os.fstat(fd)
  if len(raw)!=info.st_size or (info.st_ino,info.st_size,info.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns):raise ValueError('tieba_evidence_changed')
  value=json.loads(raw)
  if not isinstance(value,dict):raise ValueError('tieba_evidence_invalid')
  return value
 except (ValueError,RecursionError,OSError):raise ValueError('tieba_evidence_invalid') from None
 finally:os.close(fd)

class Journal:
 def __init__(self,run,manifest):
  from shared_request_budget import request_fingerprint
  self.run=safe_path(run);self.path=self.run/'pro-pagination.json';self.binding={'operation_id':str(uuid.UUID(manifest['run_id'])),'request_hash':request_fingerprint(manifest['request'])}
  if self.path.exists():
   value=read_json(self.path)
   if any(value.get(k)!=v for k,v in self.binding.items()):raise ValueError('tieba_journal_binding')
   raise TiebaStop('tieba_existing_pagination_requires_validated_resume')
 def __call__(self,payload):
  data={**payload,**self.binding,'invalid':False}
  if (self.run/'tieba-media-source.json').exists():data['media_source_sha256']=digest(read_json(self.run/'tieba-media-source.json'))
  data['sha256']=digest(data)
  raw=(canonical(data)+'\n').encode()
  if len(raw)>MAX:raise ValueError('tieba_evidence_limit')
  safe_path(self.path);tmp=self.path.with_name('.tieba-pagination-'+uuid.uuid4().hex)
  fd=os.open(tmp,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
  try:
   with os.fdopen(fd,'wb') as out:out.write(raw);out.flush();os.fsync(out.fileno())
   os.replace(tmp,self.path)
  finally:tmp.unlink(missing_ok=True)

class Identity:
 def __init__(self,root,session_id,run_id,event=lambda *a:None):
  from account_sessions import AccountSessions
  self.store=AccountSessions(root);self.session=session_id;self.run=run_id;self.event=event;self.slot=contextvars.ContextVar('tieba_official_self',default=None);self.original=None
 def observe_response(self,response):
  slot=self.slot.get();proof=self_proof(response)
  if slot is not None and proof is not None:slot['proof']=proof
 def install(self,client_class):
  owner=self;original=client_class.pong
  async def pong(client,*a,**kw):
   from account_sessions import safe_account_ref
   previous=owner.store.status(owner.session,'tieba')
   if type(previous.get('generation'))is not int or previous['generation']<1 or not previous.get('account_ref'):raise SystemExit(85)
   expected={k:previous[k] for k in ('generation','account_ref')};owner.event('checking',owner.store.observe(owner.session,'tieba','checking',owner.run,_expected_context=expected))
   capture={'proof':('check_failed',None)};token=owner.slot.set(capture)
   try:result=await original(client,*a,**kw)
   except BaseException:
    try:owner.event('check_failed',owner.store.observe(owner.session,'tieba','check_failed',owner.run,_expected_context=expected))
    except (ValueError,OSError):pass
    raise
   finally:owner.slot.reset(token)
   state,uid=capture['proof']
   if result is not True or state!='authenticated':
    try:owner.event(state,owner.store.observe(owner.session,'tieba','logged_out' if state=='logged_out' else 'check_failed',owner.run,_expected_context=expected))
    except ValueError:pass
    raise SystemExit(77 if state=='logged_out' else 86)
   if safe_account_ref('tieba',uid)!=expected['account_ref']:raise SystemExit(78)
   try:value=owner.store.observe(owner.session,'tieba','authenticated',owner.run,uid,_expected_context=expected)
   except ValueError:raise SystemExit(78) from None
   if value.get('authorized_for_run')!=owner.run:raise SystemExit(78)
   owner.event('authenticated',value);return True
  client_class.pong=pong;self.original=(client_class,original);return self
 def restore(self):
  if self.original is not None:cls,fn=self.original;cls.pong=fn;self.original=None

def public_detail(raw):
 """Retain only source post/extractor fields; never persist sync anti/TBS/current login."""
 if type(raw)is not dict:raise TiebaStop('tieba_detail_shape_invalid')
 def fields(value,allowed):
  if value is None:return {}
  if type(value)is not dict:raise TiebaStop('tieba_detail_shape_invalid')
  return {k:v for k,v in value.items() if k in allowed}
 def contents(value):
  if type(value)is str:return value
  if value is None:return []
  if type(value)is not list or len(value)>500:raise TiebaStop('tieba_detail_content_invalid')
  result=[]
  from tieba_media import asset_url
  keys=('origin_src','big_cdn_src','big_src','cdn_src','src','video_url')
  for x in value:
   part=fields(x,{'text','c','type'});chosen=next(((k,x[k]) for k in keys if k in x and asset_url(x[k])),None)
   if chosen is not None:part[chosen[0]]=chosen[1]
   elif any(k in x for k in keys):raise TiebaStop('tieba_media_url_scope_unverified')
   elif set(x)-{'type','text','c'} or type(x.get('type'))is not int or x['type']!=0 or not isinstance(x.get('text',x.get('c')),str):raise ValueError('tieba_zero_media_unverified')
   result.append(part)
  return result
 def post(value):
  item=fields(value,{'id','pid','tid','title','author_id','time','content','sub_post_number'})
  if 'content' in item:item['content']=contents(item['content'])
  return item
 thread=fields(raw.get('thread'),{'id','tid','title','reply_num','create_time','origin_thread_info'})
 if 'origin_thread_info' in thread:
  info=fields(thread['origin_thread_info'],{'abstract','content'});thread['origin_thread_info']={k:contents(v) for k,v in info.items()}
 posts=raw.get('post_list',[]);users=raw.get('user_list',[])
 if type(posts)is not list or len(posts)>50 or type(users)is not list or len(users)>1000:raise TiebaStop('tieba_detail_list_limit')
 value={'thread':thread,'first_floor':post(raw.get('first_floor')),'forum':fields(raw.get('forum') or raw.get('display_forum'),{'id','name'}),'page':fields(raw.get('page'),{'total_page'}),'user_list':[fields(x,{'id','name_show','name'}) for x in users],'post_list':[post(x) for x in posts]}
 source_assets(value)
 if len(canonical(value).encode())>MAX:raise TiebaStop('tieba_detail_evidence_limit')
 return value

def source_assets(raw,*,references=False):
 """Retain the reported URL separately from mature downloader's canonical URL."""
 from tieba_media import asset_url
 keys=('origin_src','big_cdn_src','big_src','cdn_src','src','video_url');seen=set();items=[]
 for post_index,post in enumerate([raw.get('first_floor') or {},*(raw.get('post_list') or [])]):
  content=post.get('content',[])
  if isinstance(content,str):
   if re.search(r'<(?:img|source|video)\b',content,re.I):raise TiebaStop('tieba_html_media_original_url_unverified')
   continue
  if type(content)is not list:raise TiebaStop('tieba_media_content_invalid')
  for part_index,part in enumerate(content):
   if type(part)is not dict:raise TiebaStop('tieba_media_content_invalid')
   chosen=next(((part[k],asset_url(part[k])) for k in keys if k in part and asset_url(part[k])),None)
   if chosen is None:
    if any(k in part for k in keys):raise TiebaStop('tieba_media_url_scope_unverified')
    continue
   original,transport=chosen
   if transport in seen and not references:continue
   seen.add(transport);items.append({'original_url':original,'transport_url':transport,'source_post_id':str(post.get('id') or post.get('pid') or ''),**({'source_slot':post_index,'content_index':part_index}if references else{})})
 if len(seen)>3:raise TiebaStop('tieba_media_source_exceeds_existing_scope')
 return items

def media_projection(pages):
 """Page-bound public snapshots -> existing downloader shape, never platform parsing."""
 if type(pages)is not list or not pages or len(pages)>1000:raise TiebaStop('tieba_media_pages_invalid')
 references=[];unique={}
 for number,page in enumerate(pages,1):
  if type(page)is not dict or set(page)!={'page','raw','sha256'} or type(page['page'])is not int or page['page']!=number or page['sha256']!=digest(page['raw']) or public_detail(page['raw'])!=page['raw']:raise TiebaStop('tieba_media_pages_invalid')
  for item in source_assets(page['raw'],references=True):
   ref={**item,'page':number,'page_sha256':page['sha256']};references.append(ref);unique.setdefault(item['transport_url'],item)
 if len(unique)>3:raise TiebaStop('tieba_media_source_exceeds_existing_scope')
 # Topic fields remain the first original native page. Only the downloader's
 # post list is a compact projection, so its existing first50 bound cannot
 # silently omit media from later pages. Full page bodies/occurrences stay above.
 raw={**pages[0]['raw'],'post_list':[{'id':x['source_post_id'],'content':[{'origin_src':x['original_url']}]}for x in unique.values()]}
 if len(canonical({'pages':pages,'raw':raw,'references':references}).encode())>MAX:raise TiebaStop('tieba_media_source_limit')
 return raw,references

def verify_media_source(source):
 try:
  if source.get('schema_version')!=2 or type(source.get('schema_version'))is not int:raise ValueError('tieba_media_source_version')
  raw,refs=media_projection(source['pages'])
  if source.get('raw')!=raw or source.get('references')!=refs:raise ValueError('tieba_media_projection_changed')
  assets=source_assets(raw)
  if not assets:
   def text_only(value):
    if isinstance(value,list):return all(text_only(x)for x in value)
    if isinstance(value,dict):
     if any(k in value for k in ('origin_src','big_cdn_src','big_src','cdn_src','src','video_url')):return False
     if 'type'in value and (type(value['type'])is not int or value['type']!=0 or not isinstance(value.get('text',value.get('c')),str)):return False
     return all(text_only(x)for x in value.values())
    if isinstance(value,str)and re.search(r'<(?:img|source|video)\b',value,re.I):return False
    return True
   if not all(text_only(page['raw'])for page in source['pages']):raise ValueError('tieba_zero_media_unverified')
  return assets
 except (TiebaStop,KeyError,TypeError):raise ValueError('tieba_media_source_invalid') from None

async def run_detail(run,manifest,executor,handler):
 """Native DetailHandler hook: real original stores/CheckpointRepoManager retained."""
 from repo.platform_save_data import tieba as store
 from model.m_checkpoint import Checkpoint
 request=manifest['request'];targets=request['targets']
 if request['platform']!='tieba' or request['mode']!='detail' or type(request['max_items'])is not int or request['max_items']!=1 or len(targets)!=1 or request.get('platform_options',{})!={}:raise TiebaStop('tieba_scope_unsupported')
 note_id=executor.bridge().execution_target('tieba','detail',targets[0]);note_id=note_id.rstrip('/').split('/')[-1].split('?')[0]
 if not numeric(note_id):raise TiebaStop('tieba_target_invalid')
 journal=Journal(run,manifest);manager=handler.checkpoint_manager;rid=manifest['run_id']
 await manager.save_checkpoint(Checkpoint(id=rid,platform='tieba',mode='detail'))
 await manager.add_note_to_checkpoint(rid,note_id)
 async def readback(kind,ids):return {entity:row for k,entity,row in executor.observations(run,manifest) if k==kind and entity in ids}
 async def topic(model):
  await store.update_tieba_note(model)
  await manager.update_note_to_checkpoint(rid,note_id,True,False)
 async def commit(note,cursor,complete):await manager.update_note_comment_cursor(rid,note,str(cursor),is_success_crawled_comments=complete)
 # Media bytes run after source commit in the owned child; raw URL/source data
 # is retained privately in the run, never cloud telemetry.
 def media(raw,note,row,page):
  path=safe_path(Path(run)/'tieba-media-source.json');previous=read_json(path) if path.exists()else None
  if previous is not None:
   verify_media_source(previous)
   bound=read_json(Path(run)/'pro-pagination.json')
   if previous.get('run_id')!=rid or previous.get('content_id')!=note or previous.get('source_observation_sha256')!=digest(row) or bound.get('media_source_sha256')!=digest(previous):raise TiebaStop('tieba_media_source_changed')
  pages=[] if previous is None else previous['pages']
  if type(page)is not int or page!=len(pages)+1:raise TiebaStop('tieba_media_page_replayed')
  projected=public_detail(raw);pages=pages+[{'page':page,'raw':projected,'sha256':digest(projected)}];merged,refs=media_projection(pages)
  data={'schema_version':2,'run_id':rid,'content_id':note,'raw':merged,'pages':pages,'references':refs,'source_observation_sha256':digest(row)};rawbytes=(canonical(data)+'\n').encode()
  if len(rawbytes)>MAX:raise TiebaStop('tieba_media_source_limit')
  tmp=path.with_name('.tieba-media-'+uuid.uuid4().hex)
  try:
   fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
   with os.fdopen(fd,'wb')as out:out.write(rawbytes);out.flush();os.fsync(out.fileno())
   if previous is None:os.link(tmp,path)
   else:
    if digest(read_json(path))!=digest(previous):raise TiebaStop('tieba_media_source_changed')
    os.replace(tmp,path)
   fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
   try:os.fsync(fd)
   finally:os.close(fd)
  finally:tmp.unlink(missing_ok=True)
  return digest(projected)
 async def media_source(raw,note,page):
  rows=await readback('topic',[note]);return media(raw,note,rows[note],page)
 detail=Detail(journal,readback,topic,store.batch_update_tieba_note_comments,commit,media_source if request['media'] else None)
 try:await detail.collect(handler.tieba_client,note_id,request['max_comments'],request['comments'],request['replies'])
 except BaseException:
  detail.coverage='partial';detail.reason='tieba_detail_failed_or_unknown';detail.persist();raise
 return detail

def install_detail(run,manifest,executor,handler_class):
 original=handler_class.get_specified_notes
 async def handle(handler,note_id_list=None):
  if note_id_list is not None:raise TiebaStop('tieba_unbound_target_override')
  return await run_detail(run,manifest,executor,handler)
 handler_class.get_specified_notes=handle
 class Hook:
  def restore(self):handler_class.get_specified_notes=original
 return Hook()

def summary(run,manifest,executor):
 """Re-read journal, operation observations and actual original checkpoint."""
 from shared_request_budget import request_fingerprint
 try:
  value=read_json(Path(run)/'pro-pagination.json');claim=value.pop('sha256',None)
  if claim!=digest(value) or type(value.get('schema_version'))is not int or value['schema_version']!=1 or value.get('operation_id')!=manifest['run_id'] or value.get('request_hash')!=request_fingerprint(manifest['request']):raise ValueError('tieba_journal_binding')
  if value.get('coverage') not in ('limit_reached','exhausted','not_requested'):raise ValueError('tieba_pagination_partial')
  pages=value.get('pages');rows={identity:row for kind,identity,row in executor.observations(run,manifest) if kind=='comment'};topics={identity:row for kind,identity,row in executor.observations(run,manifest) if kind=='topic'}
  if not isinstance(pages,list) or len(pages)>1000 or len(topics)!=1:raise ValueError('tieba_journal_invalid')
  content=next(iter(topics));seen=set();roots={};children={};nextcursor=1;committed_any=False
  if manifest['request'].get('media'):
   source=read_json(Path(run)/'tieba-media-source.json');verify_media_source(source)
   if source.get('run_id')!=manifest['run_id'] or source.get('content_id')!=content or source.get('source_observation_sha256')!=digest(topics[content]) or value.get('media_source_sha256')!=digest(source):raise ValueError('tieba_media_source_changed')
  for p in pages:
   if not isinstance(p,dict) or p.get('scope') not in ('root','reply') or p.get('content_id')!=content or p.get('selected_saved') is not True or type(p.get('checkpoint_committed'))is not bool or type(p.get('has_more'))is not bool:raise ValueError('tieba_page_invalid')
   ids=p.get('selected_ids');allids=p.get('ids')
   if not isinstance(ids,list) or not ids or not isinstance(allids,list) or len(set(allids))!=len(allids) or len(set(ids))!=len(ids) or ids!=allids[:len(ids)] or any(not numeric(x) for x in allids) or seen.intersection(ids):raise ValueError('tieba_page_ids_invalid')
   seen.update(ids)
   model_fields=('comment_id','parent_comment_id','content','creator_hash','user_nickname','publish_time','sub_comment_count','note_id','note_url','tieba_id','tieba_name','tieba_link')
   models=[]
   for identity in ids:
    row=rows.get(identity)
    if not isinstance(row,dict) or row.get('note_id')!=content:raise ValueError('tieba_page_not_durable')
    models.append({k:row[k] for k in model_fields})
    if p['scope']=='root':
     if row.get('parent_comment_id') not in ('','0',identity):raise ValueError('tieba_parent_invalid')
     roots[identity]=row
    else:
     if p.get('parent_id') not in roots or row.get('parent_comment_id')!=p['parent_id']:raise ValueError('tieba_parent_invalid')
     children.setdefault(p['parent_id'],set()).add(identity)
   if digest(models)!=p.get('model_sha256'):raise ValueError('tieba_page_hash_changed')
   if type(p.get('cursor_in'))is not int or type(p.get('cursor_out'))is not int or p['cursor_in']<1 or p['cursor_out']!=p['cursor_in']+1 or type(p.get('saved'))is not bool or p['saved'] is not (len(ids)==len(allids)):raise ValueError('tieba_cursor_invalid')
   if p['scope']=='reply' and p['checkpoint_committed'] is not False:raise ValueError('tieba_reply_checkpoint_invalid')
   if p['scope']=='root':
    if manifest['request'].get('media'):
     page=source['pages'][p['cursor_in']-1]
     if p.get('media_page_sha256')!=page['sha256'] or [str(x.get('id'))for x in page['raw']['post_list']]!=allids:raise ValueError('tieba_media_page_changed')
    if p['saved'] is False and p['checkpoint_committed'] is not False:raise ValueError('tieba_partial_root_checkpoint_invalid')
    expected={x:rows[x]['sub_comment_count'] for x in ids}
    declared=p.get('reply_roots')
    if not isinstance(declared,dict) or set(declared)!=set(expected) or any(type(n)is not int or n<0 for n in declared.values()) or declared!=expected or p.get('replies_complete') is not True or any(type(n)is not int or n<0 for n in expected.values()):raise ValueError('tieba_reply_declaration_changed')
    if p.get('checkpoint_committed') is True:
     if p['cursor_in']!=nextcursor or type(p['cursor_out'])is not int or p['cursor_out']!=nextcursor+1:raise ValueError('tieba_cursor_invalid')
     nextcursor+=1;committed_any=True
  if manifest['request'].get('media') and len(source['pages'])!=(len([p for p in pages if p['scope']=='root']) or 1):raise ValueError('tieba_media_pages_changed')
  if set(rows)!=seen or any(len(children.get(root,set()))!=row['sub_comment_count'] for root,row in roots.items()):raise ValueError('tieba_replies_incomplete')
  cp=executor.checkpoint(run,manifest);notes=cp.get('crawled_note_list') if isinstance(cp,dict) else None
  if not isinstance(notes,list) or len(notes)!=1 or notes[0].get('note_id')!=content or notes[0].get('is_success_crawled') is not True or notes[0].get('current_note_comment_cursor')!=(str(nextcursor) if committed_any else None) or notes[0].get('is_success_crawled_comments') is not (value['coverage']=='exhausted'):raise ValueError('tieba_checkpoint_mismatch')
  if value['coverage']=='limit_reached' and (cp.get('is_completed') is not False or cp.get('acquisition_committed') is not False):raise ValueError('tieba_global_complete_mismatch')
  return {'coverage':value['coverage'],'page_count':len(pages),'root_count':len(roots),'reply_count':len(rows)-len(roots),'checkpoint_verified':True,'cloud_ack':False}
 except (ValueError,OSError,KeyError,TypeError,RecursionError,IndexError):return {'coverage':'unknown','reason':'tieba_evidence_unverified','cloud_ack':False}

def finalize_scope(run,manifest,executor,assets):
 """Commit selected task scope only after durable media + three export readbacks."""
 import csv,io,tempfile
 from results_store import ResultsStore
 from pro_tieba_adapter import normalize_rows
 run=safe_path(run);coverage=summary(run,manifest,executor)
 if coverage.get('coverage') not in ('limit_reached','exhausted','not_requested'):raise TiebaStop('tieba_scope_not_durable')
 rows=executor.observations(run,manifest);records=normalize_rows(rows,manifest['run_id']);request=manifest['request'];source=read_json(run/'tieba-media-source.json') if request['media'] else None
 if request['media']:
  expected=verify_media_source(source)
  if len(assets)!=len(expected):raise TiebaStop('tieba_media_partial')
  for item,target in zip(assets,expected):
   path=safe_path(run/item['path'])
   if not path.is_relative_to(run) or item.get('content_id')!=source['content_id'] or item.get('original_url')!=target['original_url'] or item.get('transport_url')!=target['transport_url'] or item.get('source_page_sha256')!=digest(source):raise TiebaStop('tieba_media_identity_changed')
   fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
   try:
    info=os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or not 0<info.st_size<=25*1024*1024:raise TiebaStop('tieba_media_bytes_invalid')
    content=b''
    while True:
     chunk=os.read(fd,65536)
     if not chunk:break
     content+=chunk
     if len(content)>25*1024*1024:raise TiebaStop('tieba_media_bytes_invalid')
    after=os.fstat(fd)
    if len(content)!=item['bytes'] or hashlib.sha256(content).hexdigest()!=item['sha256'] or (info.st_ino,info.st_size,info.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns):raise TiebaStop('tieba_media_bytes_changed')
   finally:os.close(fd)
   if item.get('kind')!='image':raise TiebaStop('tieba_media_kind_unverified')
   from saved_media_attachments import decode_bytes
   pixels=decode_bytes(content)
   if any(item.get(k)!=v for k,v in pixels.items()):raise TiebaStop('tieba_media_pixels_changed')
 if source is not None:assets=[{**x,'source_references':[ref for ref in source['references']if ref['transport_url']==x['transport_url']]}for x in assets]
 exports=run/'output/tieba/verification-exports';safe_path(exports);exports.mkdir(parents=True,exist_ok=True)
 receipts={};packages={}
 # Reuse original ResultsStore serialization, with disposable verification DB.
 # The canonical workbench DB remains the ordinary later import destination.
 with tempfile.TemporaryDirectory(prefix='tieba-export-') as temp:
  store=ResultsStore(Path(temp).resolve());store.ingest({'run_id':manifest['run_id'],'records':records,'media':assets,'source':{'executor':'mediacrawler_pro','local_committed':False,'cloud_ack':False}})
  for fmt in ('json','jsonl','csv'):
   package=store.export(fmt);path=exports/('scope.'+fmt)
   fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
   with os.fdopen(fd,'wb') as out:out.write(package['data']);out.flush();os.fsync(out.fileno())
   data=path.read_bytes()
   if hashlib.sha256(data).hexdigest()!=package['sha256']:raise TiebaStop('tieba_export_bytes_changed')
   receipts[fmt]={'path':str(path.relative_to(run)),'bytes':len(data),'sha256':package['sha256'],'rows':package['row_count']};packages[fmt]=data
 j=json.loads(packages['json']);jl=[json.loads(x) for x in packages['jsonl'].decode().splitlines()][1:];cr=[json.loads(x['record']) for x in csv.DictReader(io.StringIO(packages['csv'].decode('utf-8-sig')))]
 if j['items']!=jl or jl!=cr or len(jl)!=len(records)+len(assets):raise TiebaStop('tieba_export_fields_changed')
 evidence={'schema_version':1,'run_id':manifest['run_id'],'task_scope_committed':True,'platform_exhausted':coverage['coverage']=='exhausted','coverage':coverage,'source_rows':len(records),'media_rows':len(assets),'assets':assets,'request_hash':__import__('shared_request_budget').request_fingerprint(manifest['request']),'exports':receipts,'cloud_ack':False,'sdk_checkpoint_global_complete_unchanged':True}
 raw=(canonical(evidence)+'\n').encode();path=run/'tieba-task-scope.json';fd=os.open(safe_path(path),os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'wb') as out:out.write(raw);out.flush();os.fsync(out.fileno())
 if read_json(path)!=evidence:raise TiebaStop('tieba_scope_commit_not_durable')
 return evidence

def read_scope(run,manifest,executor):
 """Restart readback performs no collection, media request or file mutation."""
 import csv,io
 from results_store import _record
 from pro_tieba_adapter import normalize_rows
 from shared_request_budget import request_fingerprint
 try:
  run=safe_path(run);value=read_json(run/'tieba-task-scope.json')
  if type(value.get('schema_version'))is not int or value['schema_version']!=1 or value.get('run_id')!=manifest['run_id'] or value.get('request_hash')!=request_fingerprint(manifest['request']) or value.get('task_scope_committed') is not True or value.get('cloud_ack') is not False:raise ValueError('tieba_scope_binding')
  current=summary(run,manifest,executor)
  if current!=value['coverage']:raise ValueError('tieba_scope_pages_changed')
  records=normalize_rows(executor.observations(run,manifest),manifest['run_id']);assets=value.get('assets')
  if not isinstance(assets,list):raise ValueError('tieba_scope_media_invalid')
  if type(value.get('platform_exhausted'))is not bool or value['platform_exhausted'] is not (current['coverage']=='exhausted') or type(value.get('source_rows'))is not int or value['source_rows']!=len(records) or type(value.get('media_rows'))is not int or value['media_rows']!=len(assets) or value.get('sdk_checkpoint_global_complete_unchanged') is not True:raise ValueError('tieba_scope_counts_or_completion_changed')
  if manifest['request'].get('media'):
   source=read_json(run/'tieba-media-source.json');expected=verify_media_source(source)
   if len(expected)!=len(assets) or any(x.get('content_id')!=source['content_id'] or x.get('original_url')!=wanted['original_url'] or x.get('transport_url')!=wanted['transport_url'] or x.get('source_page_sha256')!=digest(source) or x.get('source_references')!=[ref for ref in source['references']if ref['transport_url']==wanted['transport_url']] for x,wanted in zip(assets,expected)):raise ValueError('tieba_scope_media_source_changed')
  for asset in assets:
   path=safe_path(run/asset['path'])
   if not path.is_relative_to(run):raise ValueError('tieba_scope_asset_path')
   fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
   try:
    info=os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or not 0<info.st_size<=25*1024*1024:raise ValueError('tieba_scope_asset_size')
    total=0;hasher=hashlib.sha256();chunks=[]
    while True:
     chunk=os.read(fd,65536)
     if not chunk:break
     total+=len(chunk);hasher.update(chunk);chunks.append(chunk)
     if total>25*1024*1024:raise ValueError('tieba_scope_asset_size')
    after=os.fstat(fd)
    if total!=asset['bytes'] or hasher.hexdigest()!=asset['sha256'] or (info.st_ino,info.st_size,info.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns):raise ValueError('tieba_scope_asset_changed')
   finally:os.close(fd)
   if asset.get('kind')!='image':raise ValueError('tieba_scope_media_kind')
   from saved_media_attachments import decode_bytes
   pixels=decode_bytes(b''.join(chunks))
   if any(asset.get(k)!=v for k,v in pixels.items()):raise ValueError('tieba_scope_pixel_changed')
  packages={}
  for fmt in ('json','jsonl','csv'):
   rec=value['exports'][fmt];path=safe_path(run/rec['path'])
   if not path.is_relative_to(run):raise ValueError('tieba_scope_export_path')
   fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
   try:
    info=os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or not 0<info.st_size<=20*1024*1024:raise ValueError('tieba_scope_export_size')
    raw=os.read(fd,20*1024*1024+1)
    if len(raw)!=rec['bytes'] or hashlib.sha256(raw).hexdigest()!=rec['sha256']:raise ValueError('tieba_scope_export_changed')
    packages[fmt]=raw
   finally:os.close(fd)
  js=json.loads(packages['json']);jl=[json.loads(x) for x in packages['jsonl'].decode().splitlines()][1:];cr=[json.loads(x['record']) for x in csv.DictReader(io.StringIO(packages['csv'].decode('utf-8-sig')))]
  if js['items']!=jl or jl!=cr or len(jl)!=len(records)+len(assets):raise ValueError('tieba_scope_export_mismatch')
  expected=[_record(x) for x in records]+[_record({**x,'kind':'media'},'tieba') for x in assets]
  if sorted((x['version_hash'],x['body_hash']) for x in jl)!=sorted((x[3],x[4]) for x in expected):raise ValueError('tieba_scope_export_source_changed')
  matched={(x[0],x[3]):x for x in expected}
  for item in jl:
   prepared=matched.get((item.get('entity_ref'),item.get('version_hash')))
   if prepared is None or any(k not in item or canonical(item[k])!=canonical(v) for k,v in prepared[2].items()) or item.get('run_id')!=manifest['run_id']:raise ValueError('tieba_scope_export_fields_changed')
  return value
 except (ValueError,KeyError,TypeError,OSError,RecursionError):raise ValueError('tieba_task_scope_unverified') from None
