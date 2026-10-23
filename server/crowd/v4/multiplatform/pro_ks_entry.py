"""Selected-scope orchestration of original KS SDK; no platform parser or self API."""
import copy,hashlib,json,os,re,stat
from pathlib import Path
from pro_ks_adapter import Evidence,digest,canonical
class KuaishouStop(BaseException):
 def __init__(self,reason):self.reason=reason;super().__init__(reason)

def supports(request):
 return (request.get('source_executor')=='pro' and request.get('platform')=='ks' and request.get('mode')=='detail' and type(request.get('max_items'))is int and request['max_items']==1 and isinstance(request.get('targets'),list)and len(request['targets'])==1 and isinstance(request['targets'][0],str)and bool(re.fullmatch('[A-Za-z0-9_-]{1,128}',request['targets'][0]))and request.get('media')is False and request.get('comments')is True and request.get('replies')is True and type(request.get('max_comments'))is int and request['max_comments']==0 and request.get('platform_options',{})=={} and request.get('wordcloud',False)is False)

def register_observations(protocol):
 mapping={'kuaishou_video':('ks','topic','video_id'),'kuaishou_video_comment':('ks','comment','comment_id')}
 for key,value in mapping.items():
  if key in protocol.TABLES and protocol.TABLES[key]!=value:raise ValueError('ks_observation_mapping_conflict')
 protocol.TABLES.update(mapping);return mapping

def read(path):
 path=Path(path)
 if any(p.is_symlink()for p in (path,*path.parents)):raise ValueError('ks_evidence_symlink')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 try:
  st=os.fstat(fd)
  if not stat.S_ISREG(st.st_mode)or st.st_nlink!=1 or st.st_size>8*1024*1024 or stat.S_IMODE(st.st_mode)!=0o600:raise ValueError('ks_evidence_file')
  blob=os.read(fd,st.st_size+1);end=os.fstat(fd)
  if len(blob)!=st.st_size or (st.st_ino,st.st_size,st.st_mtime_ns)!=(end.st_ino,end.st_size,end.st_mtime_ns):raise ValueError('ks_evidence_changed')
 finally:os.close(fd)
 return json.loads(blob)

def context(manifest):
 from shared_request_budget import request_fingerprint
 if not supports(manifest['request']):raise ValueError('ks_scope_unsupported')
 return {'run_id':manifest['run_id'],'request_hash':request_fingerprint(manifest['request']),'content_id':manifest['request']['targets'][0]}

def account_guard(run,manifest):
 from account_sessions import AccountSessions
 store=AccountSessions(Path(run).parent.parent);r=manifest['request'];current=store.status(r['session_id'],'ks')
 expected={k:current.get(k)for k in ('generation','account_ref')}
 if type(expected['generation'])is not int or not isinstance(expected['account_ref'],str)or not re.fullmatch('[a-f0-9]{64}',expected['account_ref']):raise KuaishouStop('ks_original_identity_unverified')
 def guard():
  now=store.status(r['session_id'],'ks')
  if (Path(run)/'stop').exists()or (Path(run)/'stop.json').exists():raise KuaishouStop('ks_stop_requested')
  if any(now.get(k)!=v for k,v in expected.items())or now.get('state')!='authenticated'or now.get('authorized_for_run')!=manifest['run_id']:raise KuaishouStop('ks_original_identity_changed')
  return expected
 return guard

def snapshot(path,value,executor,*,first=False):
 blob=(canonical(value)+'\n').encode()
 if len(blob)>8*1024*1024:raise KuaishouStop('ks_evidence_size')
 if first:
  fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb')as f:f.write(blob);f.flush();os.fsync(f.fileno())
 else:executor.bridge().write(path,value)

class DetailHook:
 def __init__(self,run,manifest,executor,handler_type,client_type,guard=None):
  self.run=Path(run).resolve();self.manifest=manifest;self.executor=executor;self.handler_type=handler_type;self.client_type=client_type;self.context=context(manifest);self.guard=guard or account_guard(run,manifest);self.originals=[];self.evidence=Evidence(self.context['content_id']);self.failure=None;self.active=False;self.identity=None
 def save(self,state):
  value={'schema':'crowd-pro-ks-saved-scope-v1',**self.context,'identity_context':self.identity,'state':state,'detail':self.evidence.detail,'pages':self.evidence.pages,'errors':self.evidence.errors}
  value['sha256']=digest(value);snapshot(self.run/'ks-evidence.json',value,self.executor)
 def install(self):
  owner=self;original_handle=self.handler_type.handle;original_post=self.client_type.post;original_v2=self.client_type.post_v2
  async def post(client,uri,data,*args,**kwargs):
   if not owner.active:return await original_post(client,uri,data,*args,**kwargs)
   owner.guard()
   if uri!=''or data.get('operationName')!='visionVideoDetail'or data.get('variables',{}).get('photoId')!=owner.context['content_id']:raise KuaishouStop('ks_detail_request_scope')
   response=await original_post(client,uri,data,*args,**kwargs);owner.guard();owner.evidence.detail_response(response);owner.save('running');return response
  async def post_v2(client,uri,data,*args,**kwargs):
   if not owner.active:return await original_v2(client,uri,data,*args,**kwargs)
   owner.guard();kind='reply'if 'rootCommentId'in data else'root';cursor=data.get('pcursor')
   from constant.kuaishou import KUAISHOU_COMMENT_LIST_V2,KUAISHOU_SUB_COMMENT_LIST_V2
   if data.get('photoId')!=owner.context['content_id']or uri!=(KUAISHOU_SUB_COMMENT_LIST_V2 if kind=='reply'else KUAISHOU_COMMENT_LIST_V2)or not isinstance(cursor,str):raise KuaishouStop('ks_comment_request_scope')
   try:response=await original_v2(client,uri,data,*args,**kwargs)
   except BaseException:
    owner.evidence.failed(kind,cursor);owner.save('unknown');raise
   owner.guard();owner.evidence.page(kind,cursor,response,str(data['rootCommentId'])if kind=='reply'else None);owner.save('running');return response
  async def handle(handler,*args,**kwargs):
   owner.identity=owner.guard();path=owner.run/'ks-evidence.json'
   if path.exists():raise KuaishouStop('ks_existing_capture_requires_reconciliation')
   value={'schema':'crowd-pro-ks-saved-scope-v1',**owner.context,'identity_context':owner.identity,'state':'attempted_no_retry','detail':None,'pages':[],'errors':[]};value['sha256']=digest(value);snapshot(path,value,owner.executor,first=True);owner.active=True
   from model.m_checkpoint import Checkpoint
   import config
   await handler.checkpoint_manager.save_checkpoint(Checkpoint(id=owner.manifest['run_id'],platform='ks',mode='detail'))
   # Existing handler resumes this selected checkpoint, never a previous run.
   prior=(config.ENABLE_CHECKPOINT,config.SPECIFIED_CHECKPOINT_ID)
   config.ENABLE_CHECKPOINT=True;config.SPECIFIED_CHECKPOINT_ID=owner.manifest['run_id']
   try:
    result=await original_handle(handler,*args,**kwargs);owner.guard();owner.save('saved');finalize_scope(owner.run,owner.manifest,owner.executor);return result
   except BaseException as error:
    owner.failure=error
    try:owner.save('unknown')
    except BaseException:pass
    raise
   finally:owner.active=False;config.ENABLE_CHECKPOINT,config.SPECIFIED_CHECKPOINT_ID=prior
  for cls,name,fn in [(self.client_type,'post',post),(self.client_type,'post_v2',post_v2),(self.handler_type,'handle',handle)]:self.originals.append((cls,name,getattr(cls,name)));setattr(cls,name,fn)
  return self
 def restore(self):
  for cls,name,fn in reversed(self.originals):setattr(cls,name,fn)
  self.originals=[]
 def rethrow(self):
  if self.failure is not None:raise self.failure

def install_detail(run,manifest,executor,handler_type,client_type,guard=None):return DetailHook(run,manifest,executor,handler_type,client_type,guard).install()

def project(run,manifest,executor):
 value=read(Path(run)/'ks-evidence.json');signature=value.pop('sha256')
 if digest(value)!=signature or any(value.get(k)!=v for k,v in context(manifest).items())or value['state']!='saved':raise ValueError('ks_capture_unverified')
 e=Evidence(value['content_id']);e.detail=value['detail'];e.pages=value['pages'];e.errors=value['errors']
 rows=executor.observations(run,manifest);videos=[x for kind,entity,x in rows if kind=='topic'];comments=[x for kind,entity,x in rows if kind=='comment']
 cp=executor.checkpoint(run,manifest)
 if not cp or cp.get('failed_search_pages')or len(cp['crawled_note_list'])!=1:raise ValueError('ks_checkpoint_missing')
 note=cp['crawled_note_list'][0]
 if note.get('note_id')!=value['content_id']or note.get('is_success_crawled')is not True or note.get('is_success_crawled_comments')is not True or note.get('current_note_comment_cursor')!='no_more':raise ValueError('ks_checkpoint_partial')
 result=e.project(videos,comments,manifest['run_id']);result['source'].pop('actual_platform_source',None)
 for r in result['records']:r['origin'].pop('actual_platform_source',None);r.pop('record_hash',None);r['record_hash']=digest(r)
 return result

def finalize_scope(run,manifest,executor):
 result=project(run,manifest,executor)
 value={'schema':'crowd-pro-ks-task-scope-v1',**context(manifest),'records_sha256':digest(result['records']),'source_rows':len(result['records']),'media_references':result['source']['media_references'],'media_bytes':0,'local_committed':True,'platform_exhausted':True,'cloud_ack':False};value['sha256']=digest(value)
 path=Path(run)/'ks-task-scope.json'
 if path.exists():raise KuaishouStop('ks_existing_scope_no_retry')
 snapshot(path,value,executor,first=True);return value

def read_scope(run,manifest,executor):
 value=read(Path(run)/'ks-task-scope.json');signature=value.pop('sha256');result=project(run,manifest,executor)
 if digest(value)!=signature or any(value.get(k)!=v for k,v in context(manifest).items())or value.get('records_sha256')!=digest(result['records'])or value.get('source_rows')!=len(result['records'])or value.get('media_references')!=result['source']['media_references']or value.get('media_bytes')!=0 or value.get('local_committed')is not True or value.get('platform_exhausted')is not True or value.get('cloud_ack')is not False:raise ValueError('ks_scope_changed')
 return {**value,'sha256':signature},result

def summary(run,manifest,executor):
 try:
  value,_=read_scope(run,manifest,executor);return {'coverage':'exhausted','source_rows':value['source_rows'],'media_bytes':0,'cloud_ack':False}
 except (ValueError,OSError,KeyError,TypeError):return {'coverage':'unknown','reason':'ks_evidence_unverified','cloud_ack':False}
