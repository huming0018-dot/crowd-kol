"""Public failed-attempt cache entry points. Caller must verify Owner grant first.
No credentials/profile/whole upstream database is copied, and no HTTP is issued here.
"""
from pathlib import Path
import re
from public_source_seed import (SeedError,ReuseJournal,read_object,build_seed,canonical,validate_seed)
from pro_weibo_adapter import WeiboAdapterStop

class SeedHook:
 def __init__(self,run,manifest,adapter,client_type,store):
  self.run=Path(run);self.manifest=manifest;self.adapter=adapter;self.client_type=client_type;self.store=store;self.originals=None
  context=manifest.get('source_continuation');request=manifest['request']
  if (not isinstance(context,dict) or context.get('kind')!='wb-replies-v1' or context.get('new_content_quota') is not False
      or context.get('reward_eligible') is not False or not isinstance(context.get('proof'),dict)
      or request.get('platform')!='wb' or request.get('mode')!='detail' or request.get('comments') is not True or request.get('replies') is not True):
   raise SeedError('seed_context_invalid')
  self.seed,_=read_object(self.run/'public-source-seed.json');validate_seed(self.seed)
  if (context.get('seed_sha256')!=self.seed['seed_sha256'] or context['proof'].get('seed_sha256')!=self.seed['seed_sha256']
      or __import__('source_continuation_chain').seed_source(context)!=self.seed['source_run_id']
      or canonical(context.get('account_context'))!=canonical(self.seed['account_context'])
      or request.get('session_id')!=self.seed['source_session_id']):raise SeedError('seed_context_binding_invalid')
  old=self.run.parent/self.seed['source_run_id'];old_manifest,old_sha=read_object(old/'manifest.json')
  if old_sha!=self.seed['source_pins']['manifest_sha256']:raise SeedError('seed_source_changed')
  rebuilt=build_seed(old,self.seed['account_context'],self.seed['source_pins'])
  if canonical(rebuilt)!=canonical(__import__('public_source_progress').base_seed(self.seed)):raise SeedError('seed_source_changed')
  if 'public_progress'in self.seed and (context['proof'].get('progress',{}).get('progress_sha256')!=self.seed['public_progress']['progress_sha256'] or context.get('source_local_run_id')!=self.seed['public_progress']['latest_local_run_id']):raise SeedError('progress_grant_changed')
  old_request=old_manifest['request'];mutable={'max_api_requests','timeout_seconds'}
  if canonical({k:v for k,v in request.items() if k not in mutable})!=canonical({k:v for k,v in old_request.items() if k not in mutable}):raise SeedError('seed_request_changed')
  for key in mutable:
   if key in old_request and (type(request.get(key)) is not int or not 1<=request[key]<=old_request[key]):raise SeedError('seed_budget_changed')
  self.journal=ReuseJournal(self.run,self.seed);self.cached_models={};self.topic_used=False;self.root_used=False
 def authorize(self):
  from account_sessions import AccountSessions
  account=AccountSessions(self.run.parent.parent).status(self.manifest['request']['session_id'],'wb');ctx=self.seed['account_context']
  if (account.get('generation')!=ctx['generation'] or account.get('account_ref')!=ctx['account_ref'] or
      account.get('state') not in ('authenticated','resumed') or account.get('authorized_for_run')!=self.run.name
      or account.get('pending_run_id')!=self.run.name):raise SystemExit(78)
 def model(self,cls,payload,**extra):
  # SQLite affinity may store original string timestamps/counters as INTEGER.
  # Recreate the native model types, then verify exact durable DB readback later.
  value={k:v for k,v in payload.items() if k!='id'}
  for key,field in cls.model_fields.items():
   if field.annotation is str and type(value.get(key)) is int:value[key]=str(value[key])
  return cls.model_validate({**value,**extra})
 def remember(self,model,kind,identity):
  self.cached_models[id(model)]=(model,kind,str(identity));return model
 def cached(self,model,kind,identity):
  entry=self.cached_models.get(id(model));return entry is not None and entry[0] is model and entry[1:]==(kind,str(identity))
 def readback(self,kind,identity):
  found=[raw for k,entity,raw in self.adapter.observations(self.run,self.manifest) if k==kind and entity==str(identity)]
  if len(found)!=1:raise SeedError('seed_store_readback_missing')
  return found[0]
 def install(self):
  owner=self;cls=self.client_type;store=self.store
  original_topic=cls.get_note_info_by_id;original_root=cls.get_note_comments
  original_save_topic=store.update_weibo_note;original_save_comment=store.update_weibo_note_comment
  from pro_weibo_adapter import WeiboPagination
  original_replies=WeiboPagination.collect_replies
  async def topic(client,note_id,*args,**kwargs):
   owner.authorize()
   if str(note_id)!=owner.seed['content_id'] or args or kwargs or owner.topic_used:raise WeiboAdapterStop('wb_seed_topic_replayed')
   owner.topic_used=True
   from model.m_weibo import WeiboNote
   row=owner.seed['topic'];model=owner.model(WeiboNote,row['payload'])
   return owner.remember(model,'topic',row['entity_id'])
  async def roots(client,note_id,max_id,max_id_type=0):
   owner.authorize()
   if str(note_id)==owner.seed['content_id'] and max_id==-1 and max_id_type==0:
    if owner.root_used:raise WeiboAdapterStop('wb_seed_root_replayed')
    owner.root_used=True
    from model.m_weibo import WeiboComment
    models=[]
    for row in owner.seed['raw_root_rows']:
     children=[]
     for child in __import__('public_source_progress').candidates(owner.seed):
      if child['kind']=='comment' and child['entity_id']!=row['entity_id'] and str(child['payload']['parent_comment_id'])==row['entity_id']:
       child_model=owner.model(WeiboComment,child['payload'])
       children.append(owner.remember(child_model,'comment',child['entity_id']))
     model=owner.model(WeiboComment,row['payload'],sub_comments=children)
     models.append(owner.remember(model,'comment',row['entity_id']))
    page=owner.seed['root_page']
    return models,{'max_id':page['cursor_out'][0],'max_id_type':page['cursor_out'][1]}
   return await original_root(client,note_id,max_id,max_id_type)
  async def replies(pagination,processor,note_id,model,callback):
   owner.authorize();parent=str(model.comment_id);cached=owner.seed.get('progress_reply_pages',{}).get(parent)
   if cached is None:return await original_replies(pagination,processor,note_id,model,callback)
   from model.m_weibo import WeiboComment
   rows={r['entity_id']:r for r in __import__('public_source_progress').candidates(owner.seed)if r['kind']=='comment'}
   children=[owner.remember(owner.model(WeiboComment,rows[v]['payload']),'comment',v)for v in cached['ids']]
   page=pagination.page(note_id,'reply',children,cached['cursor_in'],cached['cursor_out'],False,parent)
   page.update(embedded=False,targets=cached['targets'],declared_count=cached['declared_count'])
   if cached['reply_coverage']=='missing_unknown':page.update(reply_coverage='missing_unknown',observed_count=cached['observed_count'],missing_count=cached['missing_count'])
   await pagination.save(page,children,callback);return children
  async def save(model,kind,identity,original):
   owner.authorize();cached=owner.cached(model,kind,identity)
   token=(owner.journal.begin_cached if cached else owner.journal.begin_fresh)(kind,str(identity))
   # Pending is intentional on any exception/cancellation or crash between DBs.
   value=await original(model)
   owner.authorize()
   raw=owner.readback(kind,identity)
   (owner.journal.complete_cached if cached else owner.journal.complete_fresh)(kind,str(identity),raw,token)
   return value
  async def save_topic(model):return await save(model,'topic',model.note_id,original_save_topic)
  async def save_comment(model):return await save(model,'comment',model.comment_id,original_save_comment)
  def guarded(method):
   async def invoke(*args,**kwargs):
    try:return await method(*args,**kwargs)
    except SeedError as error:
     reason=str(error)
     raise WeiboAdapterStop('wb_'+reason if re.fullmatch('seed_[a-z_]{1,70}',reason) else 'wb_seed_unknown') from None
   return invoke
  cls.get_note_info_by_id=guarded(topic);cls.get_note_comments=guarded(roots)
  store.update_weibo_note=guarded(save_topic);store.update_weibo_note_comment=guarded(save_comment)
  WeiboPagination.collect_replies=replies
  self.originals=(original_topic,original_root,original_save_topic,original_save_comment,original_replies);return self
 def restore(self):
  if self.originals:
   topic,root,st,sc,replies=self.originals;
   __import__('pro_weibo_adapter').WeiboPagination.collect_replies=replies;self.client_type.get_note_info_by_id=topic;self.client_type.get_note_comments=root
   self.store.update_weibo_note=st;self.store.update_weibo_note_comment=sc;self.originals=None

def install_seed(run,manifest,adapter,client_type,store):
 try:return SeedHook(run,manifest,adapter,client_type,store).install()
 except SeedError as error:
  reason=str(error)
  raise WeiboAdapterStop('wb_'+reason if re.fullmatch('seed_[a-z_]{1,70}',reason) else 'wb_seed_unknown') from None


def reused_rows(run,manifest,rows):
 """Read-only origin classification; never creates a missing journal on status."""
 context=manifest.get('source_continuation')
 if context is None:return set(),None
 if not isinstance(context,dict) or context.get('kind')!='wb-replies-v1':raise SeedError('seed_context_invalid')
 seed,_=read_object(Path(run)/'public-source-seed.json');validate_seed(seed)
 if (context.get('seed_sha256')!=seed['seed_sha256'] or not isinstance(context.get('proof'),dict) or context['proof'].get('seed_sha256')!=seed['seed_sha256']
     or __import__('source_continuation_chain').seed_source(context)!=seed['source_run_id'] or canonical(context.get('account_context'))!=canonical(seed['account_context'])):
  raise SeedError('seed_context_binding_invalid')
 journal=ReuseJournal(run,seed,existing_only=True);journal.split_records([])
 found=set()
 from public_source_seed import digest
 for kind,identity,raw in rows:
  if journal.lookup(kind,identity,digest(raw)) is not None:found.add((kind,identity))
 return found,seed
