"""Fixed original-session DY entry; no official UID or private-history login claim."""
import hashlib,inspect,json
from pathlib import Path
from pro_session_identity import OriginalSessionScope,SessionScopeError
from pro_cursor_pages import CursorPagination,cursor,more

MODE='fixed_original_session_v1'
class DouyinStop(BaseException):
 def __init__(self,reason):self.reason=reason

def supports(request):
 return (request.get('platform')=='dy' and request.get('source_executor')=='pro' and request.get('mode') in ('detail','homefeed','trending')
  and type(request.get('max_items')) is int and request['max_items']==1 and request.get('platform_options')=={}
  and request.get('wordcloud',False) is False and type(request.get('max_comments')) is int and request['max_comments']>0)

def install_scope(root,run,manifest,sink,client,httpx):
 from account_sessions import AccountSessions
 from pro_executor import binding_for
 store=AccountSessions(root);request=manifest['request'];prior=store.status(request['session_id'],'dy')
 # Explicit existing AccountSessions confirmation, not an invented platform self-ID.
 if manifest['executor'].get('session_identity_mode')!=MODE or prior.get('identity_status')!='manually_confirmed_same_account' or prior.get('authorized_for_run')!=manifest['run_id'] or prior.get('pending_run_id')!=manifest['run_id']:
  sink.update(phase='failed',failure_reason='pro_login_verification_failed');raise SystemExit(85)
 hook=OriginalSessionScope(store,request['session_id'],'dy',manifest['run_id'],manifest['executor']['binding'],
  lambda:binding_for(root,request),previous_pending_run_id=prior.get('pending_run_id'))
 hook.install(client,httpx)
 import functools
 from repo.platform_save_data import douyin as store
 saved=[]
 for name in ('update_douyin_aweme','update_dy_aweme_comment'):
  original=getattr(store,name)
  def guarded(fn):
   @functools.wraps(fn)
   async def save(*args,**kwargs):
    hook.validate()
    try:result=await fn(*args,**kwargs)
    except Exception:raise DouyinStop('dy_comment_persistence_failed') from None
    hook.validate();return result
   return save
  saved.append((store,name,original));setattr(store,name,guarded(original))
 original_request=client.request;once=inspect.unwrap(original_request)
 if Path(inspect.getfile(once)).resolve()!=Path(__import__(client.__module__,fromlist=['x']).__file__).resolve():raise SessionScopeError()
 async def request_once(instance,*args,**kwargs):
  hook.validate()
  try:value=await once(instance,*args,**kwargs)
  except Exception:raise DouyinStop('dy_request_outcome_unknown') from None
  hook.validate();return value
 client.request=request_once
 if request['mode']=='homefeed':
  native_feed=client.get_homefeed_aweme_list
  async def feed(instance,*args,**kwargs):
   hook.validate()
   from pro_executor import observations,DB_NAME
   if (Path(run)/DB_NAME).exists() and any(kind=='topic' for kind,entity,row in observations(Path(run),manifest)):
    return None  # Native <= loop otherwise requests another feed after cap1.
   return await native_feed(instance,*args,**kwargs)
  saved.append((client,'get_homefeed_aweme_list',native_feed));client.get_homefeed_aweme_list=feed
 original_restore=hook.restore
 def restore():
  for obj,name,fn in saved:setattr(obj,name,fn)
  client.request=original_request;original_restore()
 hook.restore=restore
 def observed(response):
  hook.validate()
  u=response.request.url
  if u.host=='www.douyin.com' and u.path.startswith('/aweme/v1/web/') and response.status_code==200:
   try:data=response.json()
   except ValueError:raise DouyinStop('dy_response_shape_invalid') from None
   key='StatusCode' if u.path=='/aweme/v1/web/module/feed/' else 'status_code'
   if type(data) is not dict or type(data.get(key)) is not int or data[key]!=0:raise DouyinStop('dy_response_shape_invalid')
 hook.observe_response=observed
 sink.update(account_identity_status='fixed_original_session',official_uid_verified=False,platform_login_currently_verified=False)
 return hook

class DouyinPagination(CursorPagination):
 def __init__(self,run,manifest,adapter,scope):super().__init__(run,manifest,adapter);self.scope=scope;self.originals=[];self.terminal_error=None
 def install(self,processor,store):
  # Keep both original processor pagination loops. Only select the MC-compatible
  # root prefix and refuse advancing the original cursor past an unsaved tail.
  from media_platform.douyin.client import DouYinApiClient as client
  from repo.checkpoint.checkpoint_store import CheckpointRepoManager as manager
  import sys
  module=sys.modules[processor.__module__];old_limit=module.PER_NOTE_MAX_COMMENTS_COUNT
  # Native mixed root+reply limit would stop before three selected roots when
  # the first short page has many replies. The client scope ends root iteration.
  module.PER_NOTE_MAX_COMMENTS_COUNT=0
  self.originals.append((module,'PER_NOTE_MAX_COMMENTS_COUNT',old_limit))
  owner=self;native_task=processor.get_comments_async_task
  async def scoped_task(instance,*args,**kwargs):
   try:return await native_task(instance,*args,**kwargs)
   except BaseException as error:
    owner.terminal_error=error
    return None  # Original batch uses asyncio.wait without retrieving task errors.
  owner=self;root=client.get_aweme_comments;reply=client.get_sub_comments;save=store.batch_update_dy_aweme_comments;commit=manager.update_note_comment_cursor
  async def roots(instance,aweme_id,cursor=0):
   owner.scope.validate();models,data=await root(instance,aweme_id,cursor);owner.scope.validate()
   page=owner.record('root',aweme_id,models,data,cursor)
   if page['invalid'] or any(str(m.aweme_id)!=aweme_id or str(m.parent_comment_id or '') not in ('','0') for m in models):raise DouyinStop('dy_root_scope_invalid')
   selected_before=sum(len(p.get('selected_ids',[])) for p in owner.pages[:-1] if p['scope']=='root')
   selected=models[:max(0,owner.manifest['request']['max_comments']-selected_before)]
   page.update(selected_ids=[str(m.comment_id) for m in selected],selection_limit=owner.manifest['request']['max_comments'],selection_completed=False,selected_saved=False)
   owner.persist()
   # The native final checkpoint will keep the incoming cursor if this page has
   # a deliberately unprocessed tail. Its success flag denotes the task scope.
   returned=dict(data)
   if selected_before+len(selected)>=owner.manifest['request']['max_comments']:returned['has_more']=0
   if len(selected)!=len(models):returned['cursor']=cursor
   return selected,returned
  async def replies(instance,comment_id,cursor=0,aweme_id=''):
   owner.scope.validate();models,data=await reply(instance,comment_id,cursor,aweme_id);owner.scope.validate()
   page=owner.record('reply',aweme_id,models,data,cursor,comment_id)
   if page['invalid'] or any(str(m.aweme_id)!=aweme_id or str(m.parent_comment_id)!=str(comment_id) for m in models):raise DouyinStop('dy_reply_scope_invalid')
   return models,data
  async def saved(aweme_id,comments):
   owner.scope.validate();result=await save(aweme_id,comments);owner.scope.validate()
   ids=[str(m.comment_id) for m in comments]
   rows={entity:row for kind,entity,row in owner.adapter.observations(owner.run,owner.manifest) if kind=='comment'}
   matched=[p for p in owner.pages if p['content_id']==aweme_id and (p.get('selected_ids') if p['scope']=='root' else p['ids'])==ids]
   if comments and not matched:raise DouyinStop('dy_comment_persistence_failed')
   for model in comments:
    row=rows.get(str(model.comment_id))
    if row is None or row.get('aweme_id')!=aweme_id or str(row.get('content'))!=str(model.content) or str(row.get('parent_comment_id') or '')!=str(model.parent_comment_id or ''):raise DouyinStop('dy_comment_persistence_failed')
   for page in matched:
    if page['scope']=='root':page['selected_saved']=True;page['saved']=len(page['selected_ids'])==len(page['ids'])
    else:page['saved']=True
   owner.persist();return result
  async def committed(instance,*args,**kwargs):
   owner.scope.validate();bound=inspect.signature(commit).bind(instance,*args,**kwargs);bound.apply_defaults();a=bound.arguments
   result=await commit(instance,*args,**kwargs);owner.scope.validate()
   if result is True and a['checkpoint_id']==owner.manifest['run_id'] and a['is_success_crawled_comments'] is True:
    cp=owner.adapter.checkpoint(owner.run,owner.manifest)
    if any(str(n['note_id'])==str(a['note_id']) and str(n['current_note_comment_cursor'])==str(a['comment_cursor']) and n['is_success_crawled_comments'] is True for n in cp['crawled_note_list']):
     for page in owner.pages:
      if page['scope']=='root' and page['content_id']==str(a['note_id']):page['selection_completed']=True;page['checkpoint_committed']=page['saved']
   owner.persist();return result
  for obj,key,replacement in ((processor,'get_comments_async_task',scoped_task),(client,'get_aweme_comments',roots),(client,'get_sub_comments',replies),(store,'batch_update_dy_aweme_comments',saved),(manager,'update_note_comment_cursor',committed)):
   self.originals.append((obj,key,getattr(obj,key)));setattr(obj,key,replacement)
  return self
 def rethrow(self):
  if self.terminal_error is not None:raise self.terminal_error
 def restore(self):
  for obj,key,value in reversed(self.originals):setattr(obj,key,value)
  self.originals=[]

def summary(run,manifest,adapter):
 try:
  from pro_source_steps import safe_json
  doc=safe_json(Path(run)/'pro-pagination.json');expected=doc.pop('sha256')
  if type(doc.get('schema_version')) is not int or doc['schema_version']!=1 or expected!=hashlib.sha256(adapter.bridge().canonical(doc).encode()).hexdigest() or doc.get('operation_id')!=manifest['run_id'] or doc.get('platform')!='dy' or doc.get('invalid') is not False:raise ValueError()
  pages=doc['pages']
  if type(pages) is not list or any(type(p) is not dict or p.get('invalid') is not False or type(p.get('has_more')) is not bool or type(p.get('cursor_in')) is not int or type(p.get('cursor_out')) is not int or p['cursor_in']<0 or p['cursor_out']<0 or type(p.get('ids')) is not list or len(p['ids'])!=len(set(p['ids'])) for p in pages):raise ValueError()
  for page in pages:
   if page.get('scope') not in ('root','reply') or not all(type(i) is str and adapter.bridge().opaque(i)==i for i in page['ids']) or page['has_more'] and page['cursor_in']==page['cursor_out']:raise ValueError()
   if page['scope']=='root' and (type(page.get('reply_roots')) is not dict or set(page['reply_roots'])!=set(page['ids']) or any(type(n) is not int or n<0 for n in page['reply_roots'].values())):raise ValueError()
  roots=[p for p in pages if p['scope']=='root'];rows={entity:row for kind,entity,row in adapter.observations(run,manifest) if kind=='comment'};allids=[];rootids=[];prior=None
  topics={entity for kind,entity,row in adapter.observations(run,manifest) if kind=='topic'}
  if {p['content_id'] for p in pages}!=topics or len(topics)!=1 or any(str(row.get('aweme_id')) not in topics for row in rows.values()):raise ValueError()
  for p in roots:
   ids=p['selected_ids'];limit=manifest['request']['max_comments']
   if p['invalid'] or p['selected_ids']!=p['ids'][:max(0,limit-len(rootids))] or type(p['selection_limit']) is not int or p['selection_limit']!=limit or p['selected_saved'] is not True or p['selection_completed'] is not True or p['saved'] is not (len(ids)==len(p['ids'])) or p['checkpoint_committed'] is not p['saved'] or p['cursor_in']!=(0 if prior is None else prior['cursor_out']):raise ValueError()
   rootids+=ids;allids+=ids;prior=p
   for entity in ids:
    if entity not in rows or str(rows[entity].get('parent_comment_id') or '') not in ('','0'):raise ValueError()
    children=[x for x in pages if x['scope']=='reply' and x['parent_id']==entity];childids=[];previous=None
    for child in children:
     if child['invalid'] or child['saved'] is not True or child['cursor_in']!=(0 if previous is None else previous['cursor_out']) or previous is not None and not previous['has_more']:raise ValueError()
     childids+=child['ids'];previous=child
    count=p['reply_roots'][entity] if manifest['request']['replies'] else 0
    if (count and (not children or children[-1]['has_more'] or len(set(childids))<count)) or len(childids)!=len(set(childids)):raise ValueError()
    for childid in childids:
     if childid not in rows or str(rows[childid].get('parent_comment_id'))!=entity:raise ValueError()
    allids+=childids
  if roots and len(rootids)<manifest['request']['max_comments'] and roots[-1]['has_more']:raise ValueError()
  if not roots or len(allids)!=len(set(allids)) or set(rows)!=set(allids):raise ValueError()
  cp=adapter.checkpoint(run,manifest);notes=cp['crawled_note_list'];last=roots[-1];out=last['cursor_out'] if last['saved'] else last['cursor_in']
  if not any(str(n['note_id'])==last['content_id'] and str(n['current_note_comment_cursor'])==str(out) and n['is_success_crawled_comments'] is True and type(n['saved_comment_count']) is int and n['saved_comment_count']==len(allids) for n in notes):raise ValueError()
  return {'coverage':'limit_reached' if len(rootids)>=manifest['request']['max_comments'] else 'exhausted','reason':'selected_root_scope_completed','selected_roots':len(rootids),'comments':len(allids),'full_root_page_saved':all(p['saved'] for p in roots)}
 except (OSError,ValueError,TypeError,KeyError,AttributeError):return {'coverage':'unknown','reason':'dy_pagination_evidence_invalid'}
