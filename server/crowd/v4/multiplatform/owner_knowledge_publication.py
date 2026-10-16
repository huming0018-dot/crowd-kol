"""Explicit release/pin/rollback through the existing 065 SDK, not Consumer publish.
Host supplies a SHA-pinned backend config and original CloudClient. No browser paths,
roles or scope. Unknown writes remain durable and are never automatically retried.
"""
from pathlib import Path
import contextlib,fcntl,hashlib,json,os,re,stat,tempfile,uuid
import yaml
from toolbox.knowledge import KnowledgeStore, _candidate_hash
from owner_knowledge_binding import OwnerKnowledgeBinding, BindingError, canonical, protected_bytes, sync_directory
from material_bridge import read_bytes

FILES=('pack.yaml','fields.yaml','pointers.json','validation.yaml','rubric.yaml','expectations.yaml')
KEYS={'schema','binding_config','binding_sha256','packs_root','intents','rollback_target'}
class PublicationError(ValueError):pass

def digest(raw):return hashlib.sha256(raw).hexdigest()
def parse(raw):
    try:
        value=json.loads(raw,parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
    except (ValueError,RecursionError,UnicodeError):raise PublicationError('knowledge_publication_json_invalid')from None
    if type(value)is not dict:raise PublicationError('knowledge_publication_json_invalid')
    return value

def path_checked(value):
    if type(value)is not str:raise PublicationError('knowledge_publication_path_invalid')
    p=Path(value)
    if not p.is_absolute()or any(q.is_symlink()for q in(p,*p.parents)):raise PublicationError('knowledge_publication_path_invalid')
    return p

def target_checked(value):
    if (type(value)is not dict or set(value)!={'pack_id','version','hash'}
      or any(type(value[k])is not str for k in value)
      or re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}',value['pack_id'])is None
      or re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',value['version'])is None
      or re.fullmatch(r'[a-f0-9]{64}',value['hash'])is None):raise PublicationError('knowledge_publication_target_invalid')
    return value

class OwnerKnowledgePublication:
    def __init__(self,config_path,config_sha256,owner_client):
        raw=protected_bytes(config_path)
        if digest(raw)!=config_sha256:raise PublicationError('knowledge_publication_config_changed')
        c=parse(raw)
        if set(c)!=KEYS or c['schema']!='crowd-owner-publication-v1':raise PublicationError('knowledge_publication_config_invalid')
        self.packs=path_checked(c['packs_root']);self.intents=path_checked(c['intents'])
        self.rollback=target_checked(c['rollback_target'])
        self.binding=OwnerKnowledgeBinding(c['binding_config'],c['binding_sha256'])
        self.config_path,self.config_sha256,self.client=Path(config_path),config_sha256,owner_client
        self.config=c
    def _check(self):
        if digest(protected_bytes(self.config_path))!=self.config_sha256:raise PublicationError('knowledge_publication_config_changed')
        if digest(protected_bytes(self.binding.config_path))!=self.binding.config_sha256:raise PublicationError('knowledge_binding_changed')
        return self.binding.authenticate(self.client)
    def _store(self,readonly=False):
        return KnowledgeStore(Path(self.binding.config['workspace']),self.binding._context(reviewer=True),read_only=readonly)
    @contextlib.contextmanager
    def _lock(self):
        self.intents.mkdir(mode=0o700,exist_ok=True)
        if self.intents.stat().st_mode&0o077:raise PublicationError('knowledge_publication_intents_unsafe')
        fd=os.open(self.intents/'publication.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
        try:
            st=os.fstat(fd)
            if not stat.S_ISREG(st.st_mode)or st.st_uid!=os.getuid()or st.st_nlink!=1 or st.st_mode&0o077:raise PublicationError('knowledge_publication_lock_unsafe')
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise PublicationError('knowledge_publication_busy')from None
            yield
        finally:os.close(fd)
    @contextlib.contextmanager
    def _snapshot(self):
        with tempfile.TemporaryDirectory(prefix='knowledge-release-snapshot-')as td:
            p=Path(td)
            for n in FILES:(p/n).write_bytes(read_bytes(Path(self.binding.config['candidate'])/n,8*1024*1024))
            try:meta=yaml.safe_load((p/'pack.yaml').read_bytes())['pack'];target=target_checked({'pack_id':meta['pack_id'],'version':meta['version'],'hash':_candidate_hash(p)})
            except (ValueError,KeyError,TypeError,RecursionError,yaml.YAMLError):raise PublicationError('knowledge_publication_candidate_invalid')from None
            if target['hash']!=self.binding.config['candidate_hash']or target['version']!=self.binding.config['target_version']or target['pack_id']!=self.rollback['pack_id']:raise PublicationError('knowledge_publication_candidate_changed')
            yield p,target
    def _require_settled_scope(self):
        # The persistent scope lock covers the scan and the next write intent.
        # A different intent must not bypass an unresolved earlier operation.
        for path in self.intents.iterdir():
            if path.name=='publication.lock':continue
            if path.suffix!='.json':raise PublicationError('knowledge_publication_outcome_unknown')
            try:
                if str(uuid.UUID(path.stem))!=path.stem:raise ValueError()
                value=parse(protected_bytes(path,1024*1024))
                if (set(value)!={'state','config_sha256','fingerprint','result'}
                        or value['state']!='completed'
                        or value['config_sha256']!=self.config_sha256
                        or type(value['fingerprint'])is not str
                        or re.fullmatch(r'[a-f0-9]{64}',value['fingerprint'])is None):raise ValueError()
                result=value['result']
                if (type(result)is not dict or set(result)!={'state','action','intent_id','target','receipt','readback_hash','knowledge_pin_changed','consumer_pointer_changed','cloud_pointer_changed','human_identity_claimed','automatic_retry'}
                        or result['state']!='completed' or result['action']not in ('release','pin','rollback')
                        or result['intent_id']!=path.stem or type(result['receipt'])is not dict
                        or result['consumer_pointer_changed']is not False or result['cloud_pointer_changed']is not False
                        or result['human_identity_claimed']is not False or result['automatic_retry']is not False
                        or type(result['knowledge_pin_changed'])is not bool
                        or result['knowledge_pin_changed']!=(result['action']!='release')):raise ValueError()
                target_checked(result['target'])
                if result['readback_hash']!=result['target']['hash']:raise ValueError()
                expected=digest(canonical({'config_sha256':self.config_sha256,'action':result['action'],'payload':{'intent_id':path.stem}}))
                if value['fingerprint']!=expected:raise ValueError()
            except (ValueError,TypeError,KeyError,OSError):
                raise PublicationError('knowledge_publication_outcome_unknown')from None

    def _accepted(self,store,target):
        proposal=store.get_proposal(self.binding.config['proposal_id'])
        if (proposal['status']!='accepted'or proposal['pack_id']!=target['pack_id']or proposal['version']!=target['version']or proposal['base_hash']!=target['hash']):raise PublicationError('knowledge_publication_not_accepted')
        # Original release() independently checks approved decision + exact evidence hash.
    def request(self,body):
        if type(body)is not dict or set(body)!={'action','payload'}or type(body['payload'])is not dict:raise PublicationError('knowledge_publication_request_invalid')
        action,payload=body['action'],body['payload']
        if type(action)is not str or action not in ('release','pin','rollback','status','read'):raise PublicationError('knowledge_publication_action_denied')
        self._check()
        if action=='status':
            intent=self._intent_id(payload);p=self.intents/(intent+'.json')
            try:value=parse(protected_bytes(p,1024*1024))
            except FileNotFoundError:return {'state':'not_found','intent_id':intent,'automatic_retry':False}
            if value['config_sha256']!=self.config_sha256:raise PublicationError('knowledge_publication_intent_conflict')
            return value['result']if value['state']=='completed'else {'state':'outcome_unknown','intent_id':intent,'automatic_retry':False}
        if action=='read':
            if set(payload)!={'version'}or payload['version']not in ('current','candidate','rollback'):raise PublicationError('knowledge_publication_request_invalid')
            with self._snapshot()as(_,target):
                choice=None if payload['version']=='current'else target if payload['version']=='candidate'else self.rollback
                store=self._store(True)
                try:value=store.get_package(target['pack_id'],self.packs,**({'version':choice['version'],'hash_':choice['hash']}if choice else {}))
                finally:store.close()
            return {'state':'read','knowledge_package':value,'consumer_pointer_changed':False,'cloud_pointer_changed':False}
        intent=self._intent_id(payload)
        with self._lock():
            self._check();fingerprint=digest(canonical({'config_sha256':self.config_sha256,'action':action,'payload':payload}));journal=self.intents/(intent+'.json')
            if journal.exists():
                prior=parse(protected_bytes(journal,1024*1024))
                if prior['fingerprint']!=fingerprint:raise PublicationError('knowledge_publication_intent_conflict')
                if prior['state']!='completed':raise PublicationError('knowledge_publication_outcome_unknown')
                return prior['result']
            self._require_settled_scope()
            with self._snapshot()as(candidate,target):
                chosen=self.rollback if action=='rollback'else target
                store=self._store(True)
                try:
                    if action=='release':self._accepted(store,target)
                    else:store.get_package(chosen['pack_id'],self.packs,version=chosen['version'],hash_=chosen['hash'])
                finally:store.close()
                fd=os.open(journal,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
                with os.fdopen(fd,'wb')as o:o.write(canonical({'state':'started','action':action,'config_sha256':self.config_sha256,'fingerprint':fingerprint}));o.flush();os.fsync(o.fileno())
                sync_directory(self.intents)
                # All exceptions after this point leave UNKNOWN; no auto-recovery writes.
                store=self._store()
                try:
                    if action=='release':receipt=store.release(target['pack_id'],target['version'],target['hash'],self.packs,candidate_dir=candidate,idempotency_key=intent)
                    else:receipt=store.pin(chosen['pack_id'],chosen['version'],chosen['hash'],self.packs)
                    readback=store.get_package(chosen['pack_id'],self.packs,version=chosen['version'],hash_=chosen['hash'])
                    if action!='release':
                        active=store.get_package(chosen['pack_id'],self.packs)
                        if active['version']!=chosen['version']or active['pin_hash']!=chosen['hash']:raise PublicationError('knowledge_publication_readback_mismatch')
                finally:store.close()
                if readback['pin_hash']!=chosen['hash']:raise PublicationError('knowledge_publication_readback_mismatch')
                result={'state':'completed','action':action,'intent_id':intent,'target':chosen,'receipt':receipt,'readback_hash':readback['pin_hash'],'knowledge_pin_changed':action!='release','consumer_pointer_changed':False,'cloud_pointer_changed':False,'human_identity_claimed':False,'automatic_retry':False}
                self._complete(journal,{'state':'completed','config_sha256':self.config_sha256,'fingerprint':fingerprint,'result':result})
                return result
    def _intent_id(self,payload):
        if set(payload)!={'intent_id'}or type(payload.get('intent_id'))is not str:raise PublicationError('knowledge_publication_request_invalid')
        try:
            if str(uuid.UUID(payload['intent_id']))!=payload['intent_id']:raise ValueError()
        except ValueError:raise PublicationError('knowledge_publication_request_invalid')from None
        return payload['intent_id']
    def _complete(self,path,value):
        tmp=path.with_suffix('.complete');fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb')as o:o.write(canonical(value));o.flush();os.fsync(o.fileno())
        os.replace(tmp,path);sync_directory(path.parent)
