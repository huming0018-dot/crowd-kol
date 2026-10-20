"""Send one fixed, verified Owner draft to the existing SDK. UNKNOWN never resubmits."""
import datetime,hashlib,json,re
from pathlib import Path
from toolbox.knowledge import AuthContext,KnowledgeStore,KnowledgeError
from owner_knowledge_binding import BindingError,canonical,protected_bytes,sync_directory
from owner_target_proposal import prepare_target
from material_feedback import MaterialFeedback
from publication_pro_share import create
from automatic_materials import write

def sha(raw):return hashlib.sha256(raw).hexdigest()

class OwnerTargetIntake:
 def __init__(self,source_binding,target_binding,client,root,manifest,manifest_sha,feedback_intent):
  self.source,self.target,self.client=source_binding,target_binding,client
  self.root,self.manifest,self.manifest_sha,self.feedback_intent=root,manifest,manifest_sha,feedback_intent
  config=target_binding.config;self.key=config['proposal_id'].removeprefix('prop:')
  if config.get('proposal_channel')!='owner'or not re.fullmatch('[a-z0-9][a-z0-9-]{7,63}',self.key):raise BindingError('knowledge_target_intake_invalid')
  # Stable target identity, independent of runtime paths and browser-selected request IDs.
  self.identity={key:config[key]for key in ('endpoint','owner_scope','scope','workspace','proposal_id','candidate_hash','manager_actor','reviewer_actor')}
  self.identity.update(manifest_sha256=manifest_sha,feedback_intent=feedback_intent)
  self.fingerprint=sha(canonical(self.identity))
  self.path=Path(config['intents'])/('intake-'+self.key+'.json')
 def owner(self,readonly):
  config=self.target.config
  return KnowledgeStore(config['workspace'],AuthContext(**dict(zip(('tenant','project','space'),config['scope'])),role='owner',actor_ref=config['manager_actor']),read_only=readonly)
 def authenticate(self):
  self.source.authenticate(self.client)
  for binding in (self.source,self.target):
   if sha(protected_bytes(binding.config_path))!=binding.config_sha256:raise BindingError('knowledge_binding_changed')
 def journal(self):
  row=json.loads(protected_bytes(self.path))
  if(row['fingerprint']!=self.fingerprint or row['identity']!=self.identity or row['state']not in ('attempted_no_retry','recorded')
     or row['frame']['expected_proposal_id']!=self.target.config['proposal_id']
     or row['frame']['envelope']['submission_id']!=self.key
     or row['frame']['envelope']['payload_ref']['hash']!=sha(canonical(row['frame']['payload']))):raise BindingError('knowledge_target_intake_changed')
  return row
 def receipt(self,store):
  try:return store.get_receipt(self.key)
  except KnowledgeError as error:
   if str(error)=='submission not found':return None
   raise
 def reconcile(self,row):
  store=self.owner(True)
  try:
   receipt=self.receipt(store)
   if receipt is None:return {'state':'outcome_unknown','proposal_id':self.target.config['proposal_id'],'automatic_retry':False}
   frame=row['frame'];env=frame['envelope'];payload=store.get_payload(self.key);proposal=store.get_proposal(frame['expected_proposal_id'])
   if (any(receipt[key]!=env[key]for key in ('submission_id','idempotency_key','contract_version','project_id','channel','purpose','consent_ref','operation'))
       or receipt['actor_ref']!=env['actor']['ref']or receipt['status']!='accepted'
       or receipt['payload_hash']!=env['payload_ref']['hash']or payload['payload_hash']!=receipt['payload_hash']
       or payload['payload_bytes']!=canonical(frame['payload'])
       or proposal['status']not in ('proposed','review','accepted','rejected')
       or proposal['payload_hash']!=receipt['payload_hash']or proposal['channel']!='owner'or proposal['visibility']!='private'
       or proposal['owner_actor']!=env['actor']['ref']or proposal['base_hash']!=env['pack_ref']['hash']
       or proposal['pack_id']!=env['pack_ref']['pack_id']or proposal['version']!=env['pack_ref']['version']):raise BindingError('knowledge_target_intake_receipt_mismatch')
   # Original ACL was established above; verify only this exact accepted submission.
   stored=store._conn.execute('SELECT pack_ref_json,source_refs_json FROM submissions WHERE submission_id=? AND actor_ref=?',(self.key,env['actor']['ref'])).fetchone()
   if not stored or json.loads(stored[0])!=env['pack_ref']or json.loads(stored[1])!=env['source_refs']:raise BindingError('knowledge_target_intake_receipt_mismatch')
  finally:store.close()
  if row['state']!='recorded':
   write(self.path,{**row,'state':'recorded'});sync_directory(self.path.parent)
  return {'state':'target_proposal_recorded','proposal_id':proposal['proposal_id'],'proposal_status':proposal['status'],
          'receipt':receipt,'automatic_retry':False,'human_review_performed':False,'release_or_pin_performed':False}
 def status(self):
  self.authenticate()
  try:row=self.journal()
  except FileNotFoundError:
   store=self.owner(True)
   try:existing=self.receipt(store)
   finally:store.close()
   return {'state':'outcome_unknown'if existing else'not_prepared','proposal_id':self.target.config['proposal_id'],'automatic_retry':False}
  return self.reconcile(row)
 def submit(self):
  self.authenticate()
  with self.target._decision_lock():
   if self.path.exists():return self.reconcile(self.journal())
   store=self.owner(True)
   try:
    if self.receipt(store)is not None:raise BindingError('knowledge_target_intake_orphaned')
    feedback=MaterialFeedback(self.root,self.source,self.client)
    frame=prepare_target(store,self.manifest,self.manifest_sha,feedback_service=feedback,feedback_intent=self.feedback_intent,
      key=self.key,submitted_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),consent_ref='owner-target-review:'+self.key)
   finally:store.close()
   if(frame['expected_proposal_id']!=self.target.config['proposal_id']or frame['envelope']['pack_ref']['hash']!=self.target.config['candidate_hash']):raise BindingError('knowledge_target_intake_changed')
   row={'state':'attempted_no_retry','identity':self.identity,'fingerprint':self.fingerprint,'frame':frame}
   create(self.path,row)  # Durable before the sole native business write.
   store=None
   try:
    store=self.owner(False);store.propose(frame['envelope'],frame['payload'])
   except Exception:
    return {'state':'outcome_unknown','proposal_id':self.target.config['proposal_id'],'automatic_retry':False}
   finally:
    if store is not None:store.close()
   return self.reconcile(row)
