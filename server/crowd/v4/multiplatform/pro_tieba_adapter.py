"""Own detail orchestration around the installed licensed Tieba SDK. Not registered."""
import asyncio,hashlib,json,os,re,stat
from pathlib import Path
from urllib.parse import urlsplit
from html.parser import HTMLParser

class TiebaStop(BaseException):
 def __init__(self,reason):self.reason=reason;super().__init__(reason)

def canonical(v):return json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)
def digest(v):return hashlib.sha256(canonical(v).encode()).hexdigest()
def numeric(v):return type(v) in (str,int) and bool(re.fullmatch(r'[1-9][0-9]{0,29}',str(v)))

def self_proof(response):
 """Candidate official-sync contract; actual UID field still requires real validation."""
 try:
  u=urlsplit(str(response.url))
  if u.scheme!='https' or u.hostname!='tieba.baidu.com' or u.path!='/c/s/pc/sync' or u.port not in (None,443) or u.username or u.password or u.fragment:return None
  if type(response.status_code)is not int or response.status_code!=200:return ('check_failed',None)
  raw=response.json()
  if type(raw)is not dict:return ('check_failed',None)
  codes=[raw[k] for k in ('error_code','no') if k in raw]
  if not codes or any(type(code)is not int or code!=0 for code in codes):return ('check_failed',None)
  user=raw.get('data',{}).get('user',{});login=user.get('is_login')
  if login is False or type(login)is int and login==0:return ('logged_out',None)
  if not (login is True or type(login)is int and login==1):return ('check_failed',None)
  ids=[v for v in (user.get('id'),user.get('user_id')) if v is not None]
  if not ids or not all(numeric(v) for v in ids) or len(set(map(str,ids)))!=1:return ('check_failed',None)
  return ('authenticated',str(ids[0]))
 except Exception:return ('check_failed',None)

def register_observations(protocol):
 expected={'tieba_note':('tieba','topic','note_id'),'tieba_comment':('tieba','comment','comment_id')}
 for k,v in expected.items():
  if k in protocol.TABLES and protocol.TABLES[k]!=v:raise ValueError('tieba_observation_mapping_conflict')
 protocol.TABLES.update(expected)
 return expected

class CurlBudget:
 """Scoped actual PC transport, sharing the existing run ledger; no private SDK copy."""
 def __init__(self,client_module,ledger,steps,observe=lambda response:None,max_bytes=8*1024*1024,sink=None):
  self.module=client_module;self.ledger=ledger;self.steps=steps;self.observe=observe;self.maximum=max_bytes;self.original=None;self.sink=sink
 def install(self):
  owner=self;cls=self.module.AsyncSession;self.original=cls.request
  async def request(client,method,url,*args,**kw):
   u=urlsplit(str(url));expected={'/c/s/pc/sync':'GET','/c/f/pb/page_pc':'POST','/p/comment':'GET'}
   if u.scheme!='https' or u.hostname!='tieba.baidu.com' or u.port not in (None,443) or u.username or u.password or u.fragment or expected.get(u.path)!=method.upper():raise TiebaStop('tieba_transport_scope_rejected')
   if kw.get('allow_redirects') not in (None,False) or kw.get('max_redirects') not in (None,0):raise TiebaStop('tieba_transport_redirect_rejected')
   if kw.get('proxy') not in (None,'') or kw.get('proxies') not in (None,{}) or kw.get('content_callback') is not None:raise TiebaStop('tieba_transport_options_rejected')
   chunks=[];size=0;oversize=False
   def consume(chunk):
    nonlocal size,oversize
    if type(chunk)is not bytes:raise TiebaStop('tieba_transport_chunk_invalid')
    size+=len(chunk)
    if size>owner.maximum:oversize=True;return 0
    chunks.append(chunk);return len(chunk)
   kw.update(allow_redirects=False,max_redirects=0,proxy='',content_callback=consume)
   client.trust_env=False
   count=owner.ledger.debit('pro')
   if owner.sink is not None:owner.sink.attempts=count;owner.sink.update()
   owner.steps.transport('request_started',count)
   try:response=await owner.original(client,method,url,*args,**kw)
   except BaseException as error:
    try:owner.steps.transport('request_failed',count)
    except Exception:pass
    if isinstance(error,(asyncio.CancelledError,SystemExit,KeyboardInterrupt)):raise
    if oversize:raise SystemExit(76) from None
    raise TiebaStop('tieba_transport_failed') from None
   owner.steps.transport('response_received',count,response)
   if response.status_code in range(300,400):raise TiebaStop('tieba_transport_redirect_rejected')
   if type(response.status_code)is not int or response.status_code>=400:raise TiebaStop('tieba_content_access_denied' if response.status_code==403 else 'tieba_transport_failed')
   if oversize:raise SystemExit(76)
   content=b''.join(chunks) if chunks else response.content
   response.content=content
   if type(content)is not bytes or len(content)>owner.maximum:raise SystemExit(76)
   if not content:raise TiebaStop('tieba_reply_terminal_unverified' if u.path=='/p/comment' else 'tieba_transport_empty')
   if u.path!='/p/comment':
    try:raw=response.json()
    except (ValueError,TypeError):raise TiebaStop('tieba_transport_json_invalid') from None
    if type(raw)is not dict:raise TiebaStop('tieba_transport_json_invalid')
    codes=[raw[k] for k in ('error_code','no') if k in raw]
    if not codes or any(type(code)is not int or code!=0 for code in codes):
     if u.path=='/c/s/pc/sync':raise SystemExit(86)
     raise TiebaStop('tieba_transport_business_failed')
   owner.observe(response)
   return response
  cls.request=request;return self
 def restore(self):
  if self.original is not None:self.module.AsyncSession.request=self.original;self.original=None

class ReplyFields(HTMLParser):
 def __init__(self):super().__init__();self.rows=[]
 def handle_starttag(self,tag,attrs):
  attrs=dict(attrs)
  if tag!='li' or 'j_lzl_s_p' not in attrs.get('class','').split():return
  try:row=json.loads(attrs.get('data-field',''))
  except (ValueError,RecursionError):raise TiebaStop('tieba_reply_shape_invalid') from None
  if not isinstance(row,dict) or not numeric(row.get('spid')):raise TiebaStop('tieba_reply_shape_invalid')
  self.rows.append(row)

class Detail:
 """Preserve root/reply store-before-commit and selected-root child completeness."""
 def __init__(self,journal,readback,save_topic,save_comments,checkpoint,media=None):
  self.journal=journal;self.readback=readback;self.save_topic=save_topic;self.save_comments=save_comments;self.checkpoint=checkpoint;self.media=media;self.pages=[];self.ids=set();self.coverage='partial';self.reason='not_started'
 def persist(self):self.journal({'schema_version':1,'platform':'tieba','pages':self.pages,'coverage':self.coverage,'reason':self.reason})
 async def save(self,note,scope,models,incoming,outgoing,more,parent=None,all_ids=None):
  ids=[str(x.comment_id) for x in models]
  if any(not numeric(x) for x in ids) or len(set(ids))!=len(ids) or self.ids.intersection(ids):raise TiebaStop('tieba_comment_replayed')
  if any(str(x.note_id)!=note or (scope=='reply' and str(x.parent_comment_id)!=parent) or (scope=='root' and str(x.parent_comment_id) not in ('','0',str(x.comment_id))) for x in models):raise TiebaStop('tieba_comment_parent_invalid')
  p={'scope':scope,'content_id':note,'parent_id':parent,'ids':all_ids or ids,'selected_ids':ids,'cursor_in':incoming,'cursor_out':outgoing,'has_more':more,'saved':False,'selected_saved':False,'checkpoint_committed':False,'model_sha256':digest([x.model_dump() for x in models])};self.pages.append(p);self.persist()
  if models:await self.save_comments(note,models)
  durable=await self.readback('comment',ids)
  for x in models:
   row=durable.get(str(x.comment_id))
   if not isinstance(row,dict) or any(row.get(k)!=v for k,v in x.model_dump().items()):raise TiebaStop('tieba_store_not_durable')
  p['selected_saved']=True;p['saved']=bool(ids) and len(ids)==len(p['ids']);self.ids.update(ids);self.persist();return p
 async def replies(self,client,note,root):
  count=root.sub_comment_count
  if type(count)is not int or count<0:raise TiebaStop('tieba_reply_count_invalid')
  got=[];page=1
  while len(got)<count:
   raw=await client.get_note_sub_comments(note,str(root.comment_id),root.tieba_id,page)
   if not isinstance(raw,str) or len(raw.encode())>8*1024*1024:raise TiebaStop('tieba_reply_shape_invalid')
   fields=ReplyFields();fields.feed(raw)
   for row in fields.rows:
    if any(str(row[k])!=str(root.comment_id) for k in ('pid','parent_id','rootid') if k in row):raise TiebaStop('tieba_reply_parent_invalid')
   models=client.page_extractor.extract_tieba_note_sub_comments(raw,root)
   if [str(x.comment_id) for x in models]!=[str(x['spid']) for x in fields.rows]:raise TiebaStop('tieba_reply_extraction_incomplete')
   if not models or len(got)+len(models)>count:raise TiebaStop('tieba_reply_terminal_unverified')
   p=await self.save(note,'reply',models,page,page+1,len(got)+len(models)<count,str(root.comment_id));got.extend(models);p['checkpoint_committed']=False;p['parent_relation_basis']='request_scoped_endpoint';self.persist();page+=1
   if page>1000:raise TiebaStop('tieba_reply_page_limit')
  return got
 async def collect(self,client,note_id,max_roots=3,comments=True,replies=True):
  if not numeric(note_id) or type(max_roots)is not int or max_roots<0 or type(comments)is not bool or type(replies)is not bool:raise ValueError('tieba_request_invalid')
  note_id=str(note_id);raw=await client._get_pc_page_data(note_id,1);note=client.page_extractor.extract_note_detail_from_api(raw)
  if str(note.note_id)!=note_id:raise TiebaStop('tieba_content_identity_invalid')
  await self.save_topic(note)
  saved=await self.readback('topic',[note_id]);row=saved.get(note_id)
  if not isinstance(row,dict) or any(row.get(k)!=v for k,v in note.model_dump().items()):raise TiebaStop('tieba_store_not_durable')
  if type(note.total_replay_page)is not int or note.total_replay_page<0:raise TiebaStop('tieba_page_count_invalid')
  if self.media is not None:await self.media(raw,note_id)
  selected=0;page=1
  if not comments:self.coverage='not_requested';self.reason='comments_not_requested';self.persist();return note
  while page<=note.total_replay_page:
   if page!=1:raw=await client.get_note_comments(note_id,page)
   if not isinstance(raw,dict) or not isinstance(raw.get('post_list'),list):raise TiebaStop('tieba_root_shape_invalid')
   models=client.page_extractor.extract_tieba_note_parent_comments_from_api(raw,note)
   rawids=[str(x.get('id')) for x in raw['post_list'] if isinstance(x,dict)]
   if len(rawids)!=len(raw['post_list']) or rawids!=[str(x.comment_id) for x in models] or not models:raise TiebaStop('tieba_root_extraction_incomplete')
   if any(type(x.get('sub_post_number',0))is not int or x.get('sub_post_number',0)<0 or x.get('sub_post_number',0)!=m.sub_comment_count for x,m in zip(raw['post_list'],models)):raise TiebaStop('tieba_reply_count_invalid')
   chosen=models[:max(0,max_roots-selected)] if max_roots else models
   p=await self.save(note_id,'root',chosen,page,page+1,page<note.total_replay_page,all_ids=rawids)
   p['reply_roots']={str(x.comment_id):x.sub_comment_count for x in chosen};self.persist()
   if replies:
    for root in chosen:await self.replies(client,note_id,root)
   p['replies_complete']=replies or not any(x.sub_comment_count for x in chosen);selected+=len(chosen)
   full=len(chosen)==len(models)
   if full and p['replies_complete']:
    await self.checkpoint(note_id,page+1,False);p['checkpoint_committed']=True
   if max_roots and selected>=max_roots:
    self.coverage='limit_reached';self.reason='selected_roots_limit';self.persist();return note
   if not p['replies_complete']:raise TiebaStop('tieba_replies_not_requested')
   page+=1;self.persist()
  self.coverage='exhausted';self.reason='all_declared_pages_and_selected_replies_saved';self.persist();await self.checkpoint(note_id,page,True);return note

def normalize_rows(observations,run_id):
 """Use established MC typed schema, preserving original Pro observation domain."""
 import mc_runner as m
 records=[]
 for kind,identity,row in observations:
  if kind not in ('topic','comment') or not isinstance(row,dict):raise ValueError('tieba_observation_invalid')
  key='note_id' if kind=='topic' else 'comment_id'
  if str(row.get(key))!=identity or not numeric(identity):raise ValueError('tieba_observation_invalid')
  record=m.normalize('tieba','content' if kind=='topic' else 'comment',row,{'run_id':run_id,'operation_id':run_id,'executor':'mediacrawler_pro','observation_sha256':hashlib.sha256(m.canonical(row).encode()).hexdigest()})
  record['discovery_kind']='detail';record['record_hash']=hashlib.sha256(m.canonical({k:v for k,v in record.items() if k!='record_hash'}).encode()).hexdigest();records.append(record)
 topics={x['content_id'] for x in records if x['kind']=='content'}
 if len(topics)!=1 or any(x['content_id'] not in topics for x in records):raise ValueError('tieba_content_binding_invalid')
 return records
