"""Read a pinned, independently checked draft snapshot. Never open the live SDK DB."""
import hashlib,json
import yaml
from owner_knowledge_binding import BindingError,canonical,protected_bytes
from toolbox.knowledge import _pack_hash

FILES={'pack.yaml','fields.yaml','pointers.json','validation.yaml','rubric.yaml','expectations.yaml'}
ARTIFACTS=('owner_view','proposal_header','candidate_payload','candidate_receipt',
           'public_source','artifact','prepared_request','accepted_attempt',
           'source_registration_receipt','same_input_comparison','six_file_diff')

def fail():raise BindingError('knowledge_draft_snapshot_invalid')
def blob(ref):
 if type(ref)is not dict or set(ref)!={'path','sha256','bytes'}:fail()
 raw=protected_bytes(ref['path'],1024*1024)
 if len(raw)!=ref['bytes']or hashlib.sha256(raw).hexdigest()!=ref['sha256']:fail()
 return raw

def preview(path,sha,binding,client):
 binding.authenticate(client)  # Same Owner authority, not an arbitrary private-proposal catalogue.
 raw=protected_bytes(path)
 if hashlib.sha256(raw).hexdigest()!=sha:fail()
 manifest=json.loads(raw)
 if (manifest['schema']!='crowd-m4-external-candidate-manifest-v1'
     or manifest['scope']!='OFFLINE_FIXED_SNAPSHOT_READONLY_NOT_LIVE_PROPOSAL'
     or manifest['scope_tuple']!=binding.config['scope']
     or manifest['actor_mapping']!={'manager':binding.config['manager_actor'],'reviewer':binding.config['reviewer_actor']}
     or manifest['registry_candidates']!=[manifest['proposal_id']]
     or manifest['excluded_source_registration']==manifest['proposal_id']
     or set(manifest['files'])!=FILES):fail()
 artifacts={key:blob(manifest[key])for key in ARTIFACTS}
 value=json.loads(artifacts['owner_view']);header=json.loads(artifacts['proposal_header'])
 receipt=json.loads(artifacts['candidate_receipt']);payload=json.loads(artifacts['candidate_payload'])
 base,target=manifest['proposal_base_ref'],manifest['draft_target_ref']
 if (header['proposal_id']!=manifest['proposal_id']or header['channel']!='model'
     or header['status']!='proposed'or header['visibility']!='private'
     or {key:header[key]for key in ('pack_id','version')}!={key:base[key]for key in ('pack_id','version')}
     or header['base_hash']!=base['hash']or receipt['pack_ref']!=base
     or receipt['submission_id']!=header['submission_id']or receipt['operation']!='propose'
     or receipt['status']!='accepted'or receipt['payload_hash']!=manifest['candidate_payload']['sha256']
     or header['payload_hash']!=receipt['payload_hash']or value['objects']!=payload['objects']
     or value['candidate_id']!=manifest['candidate_id']or value['proposal_base_ref']!=base
     or value['draft_target_ref']!=target or value['schema']!='crowd-m4-external-candidate-view-v1'):fail()
 files={name:blob(ref)for name,ref in manifest['files'].items()}
 loaded={name.split('.')[0]:json.loads(data)if name=='pointers.json'else yaml.safe_load(data)for name,data in files.items()}
 if _pack_hash(loaded)!=target['hash']or loaded['pack']['pack']['version']!=target['version']or loaded['pack']['pack']['pack_id']!=target['pack_id']:fail()
 if (value['knowledge_live_submission']is not False or value['reviewed']is not False
     or value['published']is not False or value['pin_changed']is not False
     or value['actions']!={'preview':True,'decide':False,'release':False,'pin':False}
     or value['generation']['execution_verified']is not False
     or value['generation']['remote_provider_attested']is not False
     or value['generation']['artifact_sha256']!=manifest['artifact']['sha256']
     or payload['execution']['response_sha256']!=manifest['artifact']['sha256']):fail()
 # Return the public view only. Paths, actor mappings and raw private intake stay server-side.
 return {'state':'knowledge_draft_preview','items':[{**value,'diff':artifacts['six_file_diff'].decode('utf-8')}],
         'manifest_sha256':sha,'live_database_changed':False,'decision_available':False}
