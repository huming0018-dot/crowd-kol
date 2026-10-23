"""Compose the reviewed review and publication services on the existing Host CLI."""
from pathlib import Path
import hashlib,json,os,uuid
from owner_knowledge_binding import BindingError,canonical,protected_bytes
from owner_knowledge_service import OwnerKnowledgeService
from owner_knowledge_publication import OwnerKnowledgePublication,PublicationError,parse
from toolbox.knowledge import KnowledgeError
from material_bridge import read_bytes

KEYS={'review_config','review_sha256','publication_config','publication_sha256'}
WRITES={'publication_release':'release','publication_pin':'pin','publication_rollback':'rollback'}
REVIEW_ACTIONS={'preview','decide','status','publication_preview','publication_status','publication_read',*WRITES}
TARGET_KEYS={'target_service_config','target_service_sha256'}
class OwnerKnowledgePublicationService:
 def __init__(self,path,sha,client,_allow_target=True):
  raw=protected_bytes(path)
  if hashlib.sha256(raw).hexdigest()!=sha:raise BindingError('knowledge_host_config_changed')
  cfg=parse(raw)
  base=KEYS|{'material_root'};draft={'draft_manifest','draft_manifest_sha256'}
  if set(cfg)not in (KEYS,base,base|draft,base|TARGET_KEYS,base|draft|TARGET_KEYS,base|{'intake_feedback_intent'})or(not _allow_target and TARGET_KEYS.intersection(cfg)):raise BindingError('knowledge_host_config_invalid')
  self.path,self.sha,self.client=path,sha,client
  self.material_root=cfg.get('material_root')
  self.draft=({key:cfg[key]for key in ('draft_manifest','draft_manifest_sha256')}if 'draft_manifest'in cfg else None)
  self.review=OwnerKnowledgeService(cfg['review_config'],cfg['review_sha256'],client)
  self.publication=OwnerKnowledgePublication(cfg['publication_config'],cfg['publication_sha256'],client)
  if self.review.binding.config_sha256!=self.publication.binding.config_sha256:raise BindingError('knowledge_host_binding_mismatch')
  self.intake_feedback_intent=cfg.get('intake_feedback_intent')
  if self.intake_feedback_intent is not None:
   if self.review.binding.config.get('proposal_channel')!='owner'or type(self.intake_feedback_intent)is not str or str(uuid.UUID(self.intake_feedback_intent))!=self.intake_feedback_intent:raise BindingError('knowledge_target_intake_invalid')
  self.target=None
  if 'target_service_config'in cfg:
   self.target=OwnerKnowledgePublicationService(cfg['target_service_config'],cfg['target_service_sha256'],client,_allow_target=False)
   original,target=self.review.binding.config,self.target.review.binding.config
   if (any(original[key]!=target[key]for key in ('endpoint','owner_scope','scope','workspace','manager_actor','reviewer_actor'))
       or original['proposal_id']==target['proposal_id']or target.get('proposal_channel')!='owner'
       or original['intents']==target['intents']or self.publication.intents==self.target.publication.intents
       or self.material_root!=self.target.material_root):raise BindingError('knowledge_target_binding_mismatch')
 def _check(self):
  if hashlib.sha256(protected_bytes(self.path)).hexdigest()!=self.sha:raise BindingError('knowledge_host_config_changed')
  self.review._check_config()
 def publication_preview(self):
  self._check();p=self.publication;p._check()
  with p._snapshot()as(_,target):
   store=p._store(True)
   try:
    try:proposal=store.get_proposal(p.binding.config['proposal_id'])
    except KnowledgeError:proposal=None
    accepted=(proposal is not None and proposal['status']=='accepted' and proposal['pack_id']==target['pack_id'] and proposal['version']==target['version'] and proposal['base_hash']==target['hash'])
    def package(choice):
     # Missing release/pin is expected initially; corrupt committed bytes are not.
     if choice:
      row=store._conn.execute("SELECT 1 FROM package_releases WHERE pack_id=? AND version=? AND status='committed'",(target['pack_id'],choice['version'])).fetchone()
     else:
      scope=p.binding.config['scope']
      row=store._conn.execute('SELECT 1 FROM project_package_pins WHERE tenant=? AND project=? AND space=? AND pack_id=?',(*scope,target['pack_id'])).fetchone()
     if row is None:return None
     value=store.get_package(target['pack_id'],p.packs,**({'version':choice['version'],'hash_':choice['hash']}if choice else {}))
     return {'version':value['version'],'hash':value['pin_hash']}
    candidate,current,rollback=package(target),package(None),package(p.rollback)
   finally:store.close()
  settled=True
  try:
   if p.intents.exists()or p.intents.is_symlink():p._require_settled_scope()
  except (ValueError,OSError):settled=False
  return {'state':'publication_preview','proposal_id':p.binding.config['proposal_id'],'candidate_hash':target['hash'],
   'accepted':accepted,'candidate_release':candidate,'current_knowledge_pin':current,'rollback_release':rollback,
   'unresolved_write':not settled,'actions':{'release':accepted and candidate is None and settled,
    'pin':accepted and candidate is not None and current!=candidate and settled,
    'rollback':rollback is not None and current is not None and current!=rollback and settled},
   'message':'知识发布与knowledge pin单独操作；当前素材/领域消费者及云指针不会自动切换。',
   'rollback_notice':None if rollback else '旧版尚无本知识库的已完成发布记录，不能回滚；现有051消费者旧版不等于知识发布记录。',
   'consumer_pointer_changed':False,'cloud_pointer_changed':False,'human_uid':None}
 def material_releases(self,payload,resolve=False):
  """Read existing COMMITTED releases in the bound knowledge scope; never grant/release/pin."""
  import base64,re
  self._check();p=self.publication;p._check()
  if type(payload)is not dict or set(payload)!=({'pack_id','version','hash'}if resolve else {'pack_id'})or type(payload.get('pack_id'))is not str or not re.fullmatch('[a-z0-9][a-z0-9-]{0,63}',payload['pack_id']):raise BindingError('knowledge_request_invalid')
  if p.intents.exists():p._require_settled_scope()
  store=p._store(True)
  try:
   rows=store._conn.execute("SELECT version,hash FROM package_releases WHERE pack_id=? AND status='committed'ORDER BY created_at,version",(payload['pack_id'],)).fetchall()
   if len(rows)>200:raise BindingError('knowledge_release_limit')
   choices=[]
   for version,hash_ in rows:
    package=store.get_package(payload['pack_id'],p.packs,version=version,hash_=hash_)
    choices.append({'pack_id':package['pack_id'],'version':package['version'],'hash':package['pin_hash']})
   if not resolve:return {'state':'release_catalog','releases':choices,'knowledge_pin_changed':False}
   if payload not in choices:raise BindingError('knowledge_release_not_committed')
   folder=p.packs/'packs'/payload['pack_id']/payload['version']
   raw={name:read_bytes(folder/name,1024*1024)for name in ('pack.yaml','fields.yaml','pointers.json','validation.yaml','rubric.yaml','expectations.yaml')}
   import yaml
   parsed={name.split('.')[0]:json.loads(blob)if name=='pointers.json'else yaml.safe_load(blob)for name,blob in raw.items()}
   if hashlib.sha256(canonical(parsed)).hexdigest()!=payload['hash']:raise BindingError('knowledge_release_changed')
   files={name:base64.b64encode(blob).decode()for name,blob in raw.items()}
   return {'release':payload,'files':files}
  finally:store.close()

 def request(self,body):
  self._check()
  if type(body)is not dict or set(body)!={'action','payload'}or type(body['action'])is not str or type(body['payload'])is not dict:raise BindingError('knowledge_request_invalid')
  action=body['action']
  if action in ('target_prepare','target_prepare_status'):
   if body['payload']!={}:raise BindingError('knowledge_request_invalid')
   if not self.target or not self.target.intake_feedback_intent or not self.draft:raise BindingError('knowledge_target_not_configured')
   from owner_target_intake import OwnerTargetIntake
   intake=OwnerTargetIntake(self.review.binding,self.target.review.binding,self.client,self.material_root,
     self.draft['draft_manifest'],self.draft['draft_manifest_sha256'],self.target.intake_feedback_intent)
   return intake.submit()if action=='target_prepare'else intake.status()
  if action=='proposal_choices':
   if body['payload']!={}:raise BindingError('knowledge_request_invalid')
   self.review.binding.authenticate(self.client)
   items=[{'key':'original','title':'原知识提案（'+self.review.binding.config['target_version']+'）','proposal_id':self.review.binding.config['proposal_id']}]
   if self.target:items.append({'key':'target','title':'素材反馈提案（'+self.target.review.binding.config['target_version']+'）','proposal_id':self.target.review.binding.config['proposal_id']})
   return {'state':'knowledge_proposal_choices','items':items,'default_key':'target'if self.target else'original'}
  if action.startswith('target_')and action[7:]in REVIEW_ACTIONS:
   if not self.target:raise BindingError('knowledge_target_not_configured')
   return self.target.request({'action':action[7:],'payload':body['payload']})
  if action=='draft_preview':
   if body['payload']!={}:raise BindingError('knowledge_request_invalid')
   if not self.draft:
    self.review.binding.authenticate(self.client)
    return {'state':'knowledge_draft_preview','items':[],'live_database_changed':False,'decision_available':False}
   from knowledge_draft_preview import preview
   value=preview(self.draft['draft_manifest'],self.draft['draft_manifest_sha256'],self.review.binding,self.client)
   return {**value,'prepare_available':bool(getattr(self,'target',None) and self.target.intake_feedback_intent)}
  if action in ('material_feedback_preview','material_feedback_submit','material_feedback_status','material_feedback_inbox','material_feedback_gap_preview','material_feedback_gap_submit','material_feedback_gap_status','material_feedback_gap_list'):
   if not self.material_root:raise BindingError('material_feedback_not_configured')
   from material_feedback import MaterialFeedback
   return MaterialFeedback(self.material_root,self.review.binding,self.client).request(action,body['payload'])
  if action in ('material_releases','material_release_resolve'):return self.material_releases(body['payload'],resolve=action=='material_release_resolve')
  if action in ('preview','decide','status'):
   value=self.review.request(body)
   if action=='preview':value={**value,'preview_expires_at':self.review.previews[value['preview_token']]['created']+300}
   return value
  if action=='publication_preview' and body['payload']=={}:return self.publication_preview()
  if action in WRITES:
   # V2 rechecks accepted/COMMITTED and durable UNKNOWN under its scope lock.
   value=self.publication.request({'action':WRITES[action],'payload':body['payload']})
  elif action in ('publication_status','publication_read'):
   value=self.publication.request({'action':'status'if action=='publication_status'else 'read','payload':body['payload']})
  else:raise BindingError('knowledge_action_denied')
  messages={'release':'知识包发布已完成，knowledge pin与消费者指针保持。','pin':'knowledge pin已切换；051消费者与云指针仍保持。','rollback':'knowledge pin已回到原已发布版本；消费者与云指针仍保持。'}
  return {**value,'message':messages.get(value.get('action'),'原发布记录仍待核对；不会自动再次提交。'if value.get('state')=='outcome_unknown'else '已读取原发布记录。')}

def main():
 import argparse
 from cloud_sync import CloudClient
 parser=argparse.ArgumentParser()
 parser.add_argument('--service-config',required=True);parser.add_argument('--service-sha256',required=True)
 parser.add_argument('--cloud-config',required=True);parser.add_argument('--body-fd',type=int,required=True)
 args=parser.parse_args()
 try:
  parts=[];length=0
  while True:
   chunk=os.read(args.body_fd,min(4096,32769-length))
   if not chunk:break
   parts.append(chunk);length+=len(chunk)
   if length>32768:raise BindingError('knowledge_request_too_large')
  service=OwnerKnowledgePublicationService(args.service_config,args.service_sha256,CloudClient(args.cloud_config,role='owner'))
  print(canonical(service.request(parse(b''.join(parts)))).decode());return 0
 except (BindingError,PublicationError)as error:
  print(canonical({'error':str(error)}).decode());return 2
 except Exception:
  print(canonical({'error':'knowledge_service_unavailable'}).decode());return 2
if __name__=='__main__':raise SystemExit(main())
