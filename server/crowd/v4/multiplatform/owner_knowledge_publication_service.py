"""Compose the reviewed review and publication services on the existing Host CLI."""
from pathlib import Path
import hashlib,json,os
from owner_knowledge_binding import BindingError,canonical,protected_bytes
from owner_knowledge_service import OwnerKnowledgeService
from owner_knowledge_publication import OwnerKnowledgePublication,PublicationError,parse
from toolbox.knowledge import KnowledgeError

KEYS={'review_config','review_sha256','publication_config','publication_sha256'}
WRITES={'publication_release':'release','publication_pin':'pin','publication_rollback':'rollback'}
class OwnerKnowledgePublicationService:
 def __init__(self,path,sha,client):
  raw=protected_bytes(path)
  if hashlib.sha256(raw).hexdigest()!=sha:raise BindingError('knowledge_host_config_changed')
  cfg=parse(raw)
  if set(cfg)!=KEYS:raise BindingError('knowledge_host_config_invalid')
  self.path,self.sha,self.client=path,sha,client
  self.review=OwnerKnowledgeService(cfg['review_config'],cfg['review_sha256'],client)
  self.publication=OwnerKnowledgePublication(cfg['publication_config'],cfg['publication_sha256'],client)
  if self.review.binding.config_sha256!=self.publication.binding.config_sha256:raise BindingError('knowledge_host_binding_mismatch')
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
 def request(self,body):
  self._check()
  if type(body)is not dict or set(body)!={'action','payload'}or type(body['action'])is not str or type(body['payload'])is not dict:raise BindingError('knowledge_request_invalid')
  action=body['action']
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
