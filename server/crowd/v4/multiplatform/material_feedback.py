"""Explicit private service feedback on a verified ready material. No review/release/source."""
from pathlib import Path
import datetime,fcntl,hashlib,json,os,stat,subprocess,tempfile,uuid
from contextlib import contextmanager
from owner_knowledge_binding import BindingError,canonical
from toolbox.knowledge import AuthContext,KnowledgeStore,KnowledgeError
from publication_pro_share import private_dir,create
from automatic_materials import write

# Feedback stores both input and canonical payload; bound encoded bytes, not characters.
MAX_JOURNAL_BYTES=65536
def read(path):
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 with os.fdopen(fd,'rb')as stream:
  info=os.fstat(stream.fileno())
  if not stat.S_ISREG(info.st_mode)or info.st_uid!=os.getuid()or info.st_nlink!=1 or info.st_mode&0o077 or not 0<info.st_size<=MAX_JOURNAL_BYTES:fail('journal_invalid')
  raw=stream.read(MAX_JOURNAL_BYTES+1);after=os.fstat(stream.fileno())
  if len(raw)!=info.st_size or (info.st_ino,info.st_size,info.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns):fail('journal_changed')
  return json.loads(raw)

KINDS=('preference','ignore','want_to_know','experienced')
GAP_TYPES=('regression-miss','taxonomy-gap','rubric-gap')
ACTIONS=('material_feedback_preview','material_feedback_submit','material_feedback_status','material_feedback_inbox','material_feedback_gap_preview','material_feedback_gap_submit','material_feedback_gap_status','material_feedback_gap_list')
def digest(value):return hashlib.sha256(value).hexdigest()
def fail(code):raise BindingError('material_feedback_'+code)
def identifier(value):
 try:
  if type(value)is not str or str(uuid.UUID(value))!=value:raise ValueError()
 except (ValueError,TypeError,AttributeError):fail('request_invalid')
 return value

def source(root,key):
 """Existing Consumer validates protected runtime; reverse-bind every item to original ACK."""
 from participant_material_delivery import publication
 from pro_ack_snapshot import validate_context,scope,validate_group,project_id,records
 from material_bridge import read_bytes
 from workbench_material_call import command
 from automatic_materials import AutomaticMaterials
 state=publication(root,key)
 if state.get('state')!='ready':fail('not_ready')
 ctx=validate_context(state['context']);selected=scope({k:ctx[k]for k in ('task_id','subject','installation_id','dispatch_id')})
 expected=Path(root)/'data-products/participant-pro-ack-inputs'/(ctx['group_sha256']+'.json')
 if Path(ctx['group_path'])!=expected:fail('scope_mismatch')
 raw=read_bytes(expected,8*1024*1024)
 if digest(raw)!=ctx['group_sha256']:fail('scope_mismatch')
 snapshot=validate_group(json.loads(raw))
 if snapshot['scope']!=selected or snapshot['group_cursor']!=ctx['group_cursor']or state.get('source_scope')!=selected or type(state.get('items'))is not int or state['items']!=len(snapshot['receipts']):fail('scope_mismatch')
 pointer=state['publication_pointer'];argv=command(pointer,'read','json')
 with tempfile.TemporaryFile()as out:
  proc=subprocess.run(argv,stdout=out,stderr=subprocess.DEVNULL,timeout=15,close_fds=True)
  if proc.returncode or os.fstat(out.fileno()).st_size>8*1024*1024:fail('read_unavailable')
  out.seek(0);report_raw=out.read();report=json.loads(report_raw)
 expected_rows=records(snapshot);items={}
 if report.get('project_id')!=project_id(snapshot)or type(report.get('items'))is not list or len(report['items'])!=state['items']:fail('scope_mismatch')
 for item in report['items']:
  request=item.get('identity',{}).get('source_record_id')
  if request in items or request not in expected_rows or item.get('metadata',{}).get('capture')!=expected_rows[request]:fail('scope_mismatch')
  items[request]=item
 if set(items)!=set(expected_rows):fail('scope_mismatch')
 auto=AutomaticMaterials(root)
 try:pack=auto.pack_info(pointer)
 finally:auto.close()
 if publication(root,key)!=state:fail('current_changed')
 return {'pro_key':key,'job_id':state['job_id'],'source_project':report['project_id'],'source_scope':selected,'group_sha256':ctx['group_sha256'],'report_sha256':digest(report_raw),'pack_ref':pack,'items':items}

class MaterialFeedback:
 def __init__(self,root,binding,client,resolver=source):
  self.root=Path(root);self.binding=binding;self.client=client;self.resolver=resolver
  if not self.root.is_absolute()or not self.root.is_dir()or any(p.is_symlink()for p in (self.root,*self.root.parents)):fail('root_invalid')
  self.binding_key=digest(canonical({k:binding.config[k]for k in ('scope','workspace','endpoint','owner_scope')}))
  self.actor='central_owner_service:'+self.binding_key
  # These are the existing authorized feedback storage scope, not the source project.
  self.scope=dict(zip(('tenant','project','space'),binding.config['scope']))
  self.folder=private_dir(self.root/'material-feedback-intents'/self.binding_key)
 def check(self):self.binding.authenticate(self.client)
 def store(self,readonly=False):return KnowledgeStore(self.binding.config['workspace'],AuthContext(**self.scope,role='consumer',actor_ref=self.actor),read_only=readonly)
 @contextmanager
 def lock(self):
  fd=os.open(self.folder/'scope.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
  try:fcntl.flock(fd,fcntl.LOCK_EX);yield
  finally:os.close(fd)
 def journals(self):
  files=list(self.folder.glob('*.json'))
  if len(files)>2000:fail('journal_limit')
  return [read(p)for p in files]
 def _feedback_verify(self,store,row):
  iid=identifier(row['intent_id']);v=row['payload'];receipt=store.get_receipt(iid);value=store.get_payload(iid);event=store.get_feedback('fb:'+iid)
  if digest(canonical(v))!=row['payload_sha256'] or receipt['actor_ref']!=self.actor or receipt['project_id']!=self.scope['project'] or receipt['operation']!='feedback' or value['payload_hash']!=row['payload_sha256'] or json.loads(value['payload_bytes'])!=v or event['payload_hash']!=row['payload_sha256'] or event['submission_id']!=iid or event['target_ref']!=row['target_ref'] or event['kind']!=v['kind'] or v['kind']!=row['input']['kind']:fail('receipt_mismatch')
  return event
 def response(self,row):
  return {'state':'pending_feedback'if row['state']=='recorded'else 'outcome_unknown','intent_id':row['intent_id'],'feedback_id':row.get('feedback_id'),'pro_key':row['input']['pro_key'],'request':row['input']['request'],'kind':row['input']['kind'],'principal_kind':'central_owner_service','human_uid':None,'knowledge_scope':self.scope,'source_project':row['payload']['source_project'],'pack_ref':row['payload']['pack_ref'],'reviewed':False,'published':False,'pin_changed':False}
 def inbox(self,payload):
  if set(payload)!={'after'}:fail('request_invalid')
  after=payload['after']
  if after is not None:identifier(after)
  self.check()
  with self.lock():
   paths=sorted(self.folder.glob('*.json'),key=lambda p:p.stem)
   if len(paths)>2000:fail('journal_limit')
   for path in paths:identifier(path.stem)
   selected=[p for p in paths if after is None or p.stem>after]
   page=selected[:20];items=[];store=None
   try:
    for path in page:
     row=read(path)
     if row['intent_id']!=path.stem:fail('journal_invalid')
     if row['state']!='recorded':
      items.append({'state':'outcome_unknown','intent_id':row['intent_id'],'principal_kind':'central_owner_service','human_uid':None,'reviewed':False,'published':False})
      continue
     if store is None:store=self.store(True)
     event=self._feedback_verify(store,row)
     v=row['payload']
     items.append({'state':'pending_feedback','intent_id':row['intent_id'],'feedback_id':event['event_id'],'principal_kind':'central_owner_service','human_uid':None,'source_project':v['source_project'],'pro_key':v['pro_key'],'job_id':v['job_id'],'request':v['request'],'record_hash':v['record_hash'],'pack_ref':v['pack_ref'],'kind':v['kind'],'reason':v['reason'],'quote':v['quote'],'reviewed':False,'published':False})
   finally:
    if store:store.close()
   return {'state':'material_feedback_inbox','knowledge_scope':self.scope,'items':items,'next_cursor':page[-1].stem if len(selected)>20 else None,'indexed':len(paths),'reviewed':False,'published':False}
 def preview(self,payload):
  if set(payload)!={'pro_key'}:fail('request_invalid')
  self.check();s=self.resolver(self.root,payload['pro_key'])
  with self.lock():history=[self.response(r)for r in self.journals()if r['input']['pro_key']==payload['pro_key']]
  rows=[]
  for request,item in s['items'].items():
   cap=item['metadata']['capture'];record=cap['pro_payload']['record']
   rows.append({'request':request,'proof_id':cap['proof_id'],'record_hash':record['record_hash'],'title':item['identity'].get('title',''),'body':record.get('body','')})
  return {'state':'feedback_preview','pro_key':s['pro_key'],'expected_job':s['job_id'],'pack_ref':s['pack_ref'],'source_project':s['source_project'],'knowledge_scope':self.scope,'items':rows,'feedback':history,'principal_kind':'central_owner_service','human_uid':None,'reviewed':False}
 def status(self,payload):
  if set(payload)!={'intent_id'}:fail('request_invalid')
  iid=identifier(payload['intent_id']);self.check()
  with self.lock():
   path=self.folder/(iid+'.json')
   if not path.exists():return {'state':'not_found','intent_id':iid}
   row=read(path)
   if row['state']!='recorded':
    try:store=self.store(True)
    except KnowledgeError as error:
     if str(error)!='read-only store must already exist and not be a symlink':raise
     return self.response(row)
    try:
     try:receipt=store.get_receipt(iid)
     except KnowledgeError as error:
      if str(error)!='submission not found':raise
      return self.response(row)
     event=self._feedback_verify(store,row)
     row.update(state='recorded',feedback_id=event['event_id']);write(path,row)
    finally:store.close()
   return self.response(row)
 def submit(self,p):
  fields={'intent_id','pro_key','expected_job','request','record_hash','kind','reason','quote','experience_confirmed','consent_private'}
  if set(p)!=fields:fail('request_invalid')
  iid=identifier(p['intent_id']);identifier(p['request'])
  if p['kind']not in KINDS or type(p['reason'])is not str or not 1<=len(p['reason'].strip())<=2000 or type(p['quote'])is not str or len(p['quote'])>2000 or type(p['experience_confirmed'])is not bool or p['consent_private']is not True or (p['kind']=='experienced'and not p['experience_confirmed']):fail('request_invalid')
  self.check()
  with self.lock():
   path=self.folder/(iid+'.json')
   if path.exists():
    old=read(path)
    if old['input']!=p:fail('request_conflict')
    return self.response(old) # Original receipt status only; never replay the SDK write.
   for row in self.journals():
    if row['state']!='recorded'and row['input']['request']==p['request']:return self.response(row)
   s=self.resolver(self.root,p['pro_key'])
   if s['job_id']!=p['expected_job']:fail('current_changed')
   item=s['items'].get(p['request'])
   if item is None:fail('scope_mismatch')
   capture=item['metadata']['capture'];record=capture['pro_payload']['record'];body=record.get('body','')
   if record['record_hash']!=p['record_hash']or type(body)is not str:fail('record_changed')
   if p['quote']and p['quote']not in body:fail('quote_mismatch')
   target='material:'+s['pro_key']+':'+s['job_id']+':'+p['request']
   value={'schema':'crowd-material-feedback-v1','principal_kind':'central_owner_service','human_uid':None,'knowledge_scope':self.scope,'binding_sha256':self.binding.config_sha256,'source_project':s['source_project'],'source_scope':s['source_scope'],'pro_key':s['pro_key'],'job_id':s['job_id'],'group_sha256':s['group_sha256'],'report_sha256':s['report_sha256'],'pack_ref':s['pack_ref'],'request':p['request'],'proof_id':capture['proof_id'],'record_hash':record['record_hash'],'body_sha256':digest(body.encode()),'kind':p['kind'],'reason':p['reason'],'quote':p['quote'],'quote_sha256':digest(p['quote'].encode()),'experience_confirmed':p['experience_confirmed']}
   h=digest(canonical(value));now=datetime.datetime.now(datetime.timezone.utc).isoformat()
   env={'contract_version':'ctfs-knowledge-envelope/0.1','submission_id':iid,'project_id':self.scope['project'],'pack_ref':s['pack_ref'],'channel':'consumer','actor':{'ref':self.actor},'purpose':'feedback_material','consent_ref':None,'consent':{'scope':'private','granted_at':now,'granted_by':'central_owner_service'},'source_refs':[{'category':'crowd_observation','locator':target,'version':s['job_id'],'hash':record['record_hash']}],'payload_ref':{'store':'inline','key':iid,'type':'feedback','hash':h},'operation':'feedback','idempotency_key':iid}
   row={'state':'attempted_no_retry','intent_id':iid,'input':p,'payload':value,'payload_sha256':h,'target_ref':target}
   # Prove both attempted and known terminal representations remain queryable before any write.
   if max(len(canonical(row)),len(canonical({**row,'state':'recorded','feedback_id':'fb:'+iid})))>MAX_JOURNAL_BYTES:fail('journal_limit')
   create(path,row) # Durable intent precedes SDK transaction. Errors remain UNKNOWN.
   store=None
   try:
    store=self.store();receipt=store.feedback(env,value,p['kind'],target)
    row.update(state='recorded',feedback_id=receipt['feedback_id']);write(path,row)
    return self.response(row)
   except Exception:return self.response(row)
   finally:
    if store:store.close()
 def _gap_feedback(self,iid):
  identifier(iid)
  try:row=read(self.folder/(iid+'.json'))
  except FileNotFoundError:fail('gap_feedback_not_found')
  if row.get('state')!='recorded' or row.get('intent_id')!=iid or row.get('feedback_id')!='fb:'+iid:fail('gap_feedback_unsettled')
  value=row['payload']
  if value.get('kind')!='want_to_know' or row['input'].get('kind')!='want_to_know' or digest(canonical(value))!=row['payload_sha256']:fail('gap_feedback_invalid')
  st=self.store(True)
  try:
   self._feedback_verify(st,row)
  finally:st.close()
  return row
 def _gap_path(self,iid):
  folder=self.folder/'gaps'
  if folder.is_symlink()or(folder.exists()and(not folder.is_dir()or folder.stat().st_uid!=os.getuid()or folder.stat().st_mode&0o077)):fail('journal_invalid')
  return folder/(identifier(iid)+'.json')
 def _gap_response(self,row):
  return {'state':'pending_gap'if row['state']=='recorded'else 'outcome_unknown','feedback_intent':row['input']['feedback_intent'],'gap_intent':row['gap_intent'],'gap_id':row['event']['gap_id'],'gap_type':row['event']['gap_type'],'gap_sha256':row['event_sha256'],'reviewed':False,'published':False}
 def _gap_verify(self,row,feedback):
  if row['feedback_sha256']!=feedback['payload_sha256'] or row['input']['feedback_intent']!=feedback['intent_id'] or digest(canonical(row['event']))!=row['event_sha256']:fail('gap_receipt_mismatch')
  expected=str(uuid.uuid5(uuid.NAMESPACE_URL,self.actor+'\n'+feedback['intent_id']))
  if row['gap_intent']!=expected or row['event']['gap_id']!=expected or row['envelope']['pack_ref']!=feedback['payload']['pack_ref'] or row['envelope']['source_refs'][-1]!={'category':'consumer_preference','locator':'material-gap-intent:'+expected,'version':expected,'hash':row['event_sha256']}:fail('gap_receipt_mismatch')
  st=self.store(True)
  try:
   try:receipt=st.get_receipt(expected)
   except KnowledgeError as error:
    if str(error)=='submission not found' and row['state']!='recorded':return False
    raise
   # list_gaps establishes the existing consumer actor ACL before this one-row RO lookup.
   authorized=[v for v in st.list_gaps()if v['gap_id']==expected and v['submission_id']==expected and v['created_by']==self.actor]
   if len(authorized)!=1 or receipt['operation']!='gap' or receipt['actor_ref']!=self.actor or receipt['project_id']!=self.scope['project']:fail('gap_receipt_mismatch')
   v=st._conn.execute('SELECT gap_id,gap_type,submission_id,title,description,status,source_channel,evidence_refs_json,related_entity,created_by,created_at,receipt_seq FROM gaps WHERE gap_id=? AND created_by=?',(expected,self.actor)).fetchone()
   fields=('gap_id','gap_type','submission_id','title','description','status','source_channel','evidence_refs','related_entity','created_by','created_at','receipt_seq')
   actual=dict(zip(fields,v));actual['evidence_refs']=json.loads(actual['evidence_refs'])
   if actual!=row['event'] or [e['source_ref']for e in st.get_evidence(expected)]!=row['envelope']['source_refs']:fail('gap_receipt_mismatch')
  finally:st.close()
  return True
 def gap_preview(self,p):
  if set(p)!={'feedback_intent'}:fail('request_invalid')
  self.check()
  with self.lock():
   f=self._gap_feedback(p['feedback_intent']);v=f['payload'];path=self._gap_path(f['intent_id'])
   existing=None
   if path.exists():
    row=read(path);self._gap_verify(row,f);existing=self._gap_response(row)
   return {'state':'gap_preview','feedback_intent':f['intent_id'],'feedback_id':f['feedback_id'],'feedback_sha256':f['payload_sha256'],'kind':'want_to_know','pack_ref':v['pack_ref'],'source_project':v['source_project'],'pro_key':v['pro_key'],'job_id':v['job_id'],'request':v['request'],'record_hash':v['record_hash'],'reason':v['reason'],'quote':v['quote'],'allowed_gap_types':list(GAP_TYPES),'existing':existing,'reviewed':False,'published':False}
 def gap_submit(self,p):
  fields={'feedback_intent','expected_feedback_sha256','gap_type','title','description','consent_private'}
  if set(p)!=fields or p['gap_type']not in GAP_TYPES or type(p['title'])is not str or not 1<=len(p['title'].strip())<=200 or type(p['description'])is not str or not 1<=len(p['description'].strip())<=4000 or p['consent_private']is not True:fail('request_invalid')
  self.check()
  with self.lock():
   f=self._gap_feedback(p['feedback_intent']);path=self._gap_path(f['intent_id'])
   if p['expected_feedback_sha256']!=f['payload_sha256']:fail('gap_feedback_changed')
   if path.exists():
    row=read(path)
    if row['input']!=p:fail('request_conflict')
    self._gap_verify(row,f)
    return self._gap_response(row) # No replay, including UNKNOWN.
   v=f['payload'];iid=str(uuid.uuid5(uuid.NAMESPACE_URL,self.actor+'\n'+f['intent_id']));now=datetime.datetime.now(datetime.timezone.utc).isoformat()
   lineage={k:v[k]for k in ('source_project','source_scope','pro_key','job_id','group_sha256','report_sha256','pack_ref','request','proof_id','record_hash','body_sha256')}
   lineage.update(feedback_id=f['feedback_id'],feedback_sha256=f['payload_sha256'])
   desc={'schema':'crowd-material-feedback-gap-v1','description':p['description'],'lineage':lineage}
   event={'gap_id':iid,'gap_type':p['gap_type'],'title':p['title'],'description':canonical(desc).decode(),'status':'pending','source_channel':'consumer','evidence_refs':[f['feedback_id'],f['target_ref']],'related_entity':f['feedback_id'],'created_by':self.actor,'created_at':now,'submission_id':iid,'receipt_seq':None}
   h=digest(canonical(event))
   # SDK gap persists {}; bind the entire event in a separate typed source identity.
   refs=[{'category':'consumer_preference','locator':f['feedback_id'],'version':f['intent_id'],'hash':f['payload_sha256']},{'category':'crowd_observation','locator':f['target_ref'],'version':v['job_id'],'hash':v['record_hash']},{'category':'consumer_preference','locator':'material-gap-intent:'+iid,'version':iid,'hash':h}]
   env={'contract_version':'ctfs-knowledge-envelope/0.1','submission_id':iid,'project_id':self.scope['project'],'pack_ref':v['pack_ref'],'channel':'consumer','actor':{'ref':self.actor},'purpose':'feedback_gap','consent_ref':None,'consent':{'scope':'private','granted_at':now,'granted_by':'central_owner_service'},'source_refs':refs,'payload_ref':{'store':'inline','key':iid,'type':'gap','hash':digest(canonical({}))},'operation':'gap','idempotency_key':iid}
   row={'state':'attempted_no_retry','gap_intent':iid,'input':p,'event':event,'event_sha256':h,'feedback_sha256':f['payload_sha256'],'envelope':env}
   if max(len(canonical(row)),len(canonical({**row,'state':'recorded'})))>MAX_JOURNAL_BYTES:fail('journal_limit')
   private_dir(path.parent);create(path,row)
   st=None
   try:
    st=self.store();st.gap(env,event)
    recorded={**row,'state':'recorded'};write(path,recorded);row=recorded
   except Exception:pass # Original durable intent retained, never automatically replayed.
   finally:
    if st:st.close()
   return self._gap_response(row)
 def gap_status(self,p):
  if set(p)!={'feedback_intent'}:fail('request_invalid')
  self.check()
  with self.lock():
   f=self._gap_feedback(p['feedback_intent']);path=self._gap_path(f['intent_id'])
   if not path.exists():return {'state':'not_found','feedback_intent':f['intent_id']}
   row=read(path)
   if self._gap_verify(row,f)and row['state']!='recorded':row['state']='recorded';write(path,row)
   return self._gap_response(row)
 def gap_list(self,p):
  if set(p)!={'after'}:fail('request_invalid')
  after=p['after']
  if after is not None:identifier(after)
  self.check()
  with self.lock():
   paths=list(self._gap_path('00000000-0000-0000-0000-000000000000').parent.glob('*.json'))
   if len(paths)>2000:fail('journal_limit')
   items=[]
   selected=[path for path in sorted(paths)if after is None or path.stem>after];page=selected[:20]
   for path in page:
    f=self._gap_feedback(identifier(path.stem));row=read(path);self._gap_verify(row,f)
    item=self._gap_response(row);desc=json.loads(row['event']['description'])
    item.update(title=row['event']['title'],description=desc['description'],lineage=desc['lineage'],pack_ref=f['payload']['pack_ref'])
    if len(canonical(items+[item]))>524288:break
    items.append(item)
   return {'state':'material_feedback_gaps','items':items,'next_cursor':items[-1]['feedback_intent'] if len(selected)>len(items) else None,'reviewed':False,'published':False}
 def request(self,action,payload):
  if type(payload)is not dict:fail('request_invalid')
  return {'material_feedback_preview':self.preview,'material_feedback_submit':self.submit,'material_feedback_status':self.status,'material_feedback_inbox':self.inbox,'material_feedback_gap_preview':self.gap_preview,'material_feedback_gap_submit':self.gap_submit,'material_feedback_gap_status':self.gap_status,'material_feedback_gap_list':self.gap_list}[action](payload)
