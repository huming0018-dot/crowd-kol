"""Compose existing 065 Owner propose; never grant, review, release or pin.

Caller must first authenticate the existing Owner endpoint. All paths and actor
mapping are protected backend inputs, not browser-supplied authority.
"""
from pathlib import Path
import hashlib,json,re
from toolbox.bindings import canonical
from toolbox.knowledge import KnowledgeError
from owner_knowledge_binding import protected_bytes
from knowledge_draft_preview import preview as draft_preview

def sha(raw):return hashlib.sha256(raw).hexdigest()

def feedback_lineage(service,intent):
    """Reuse current authorized feedback/gap verification, without model input."""
    service.check()
    feedback=service._gap_feedback(intent)
    row=json.loads(protected_bytes(service._gap_path(intent)))
    if row['state']!='recorded' or not service._gap_verify(row,feedback):
        raise KnowledgeError('target gap unresolved')
    value=feedback['payload']
    return {'feedback_id':feedback['feedback_id'],'feedback_sha256':feedback['payload_sha256'],
      'gap_id':row['event']['gap_id'],'gap_event_sha256':row['event_sha256'],
      'source_project':value['source_project'],'pro_key':value['pro_key'],'job_id':value['job_id'],
      'request':value['request'],'record_hash':value['record_hash'],
      'private_feedback_in_model_input':False,'scope':service.binding.config['scope']}

def candidate(owner,manifest_path,manifest_sha256):
    raw=protected_bytes(manifest_path)
    if sha(raw)!=manifest_sha256:raise KnowledgeError('target manifest changed')
    manifest=json.loads(raw)
    scope=[owner.auth.tenant,owner.auth.project,owner.auth.space]
    if (owner.auth.role!='owner' or owner.auth.actor_ref!=manifest['actor_mapping']['manager']
        or scope!=manifest['scope_tuple']
        or owner.auth.actor_ref==manifest['actor_mapping']['reviewer']):
        raise KnowledgeError('target Owner context mismatch')
    # Original protected draft reader checks every17 ref, pack canonical hash,
    # original model receipt/payload, external-unverified and base/target split.
    class Authority:
        config={'scope':scope,'manager_actor':owner.auth.actor_ref,
                'reviewer_actor':manifest['actor_mapping']['reviewer']}
        def authenticate(self,client):
            if client is not owner:raise KnowledgeError('target Owner context mismatch')
    view=draft_preview(manifest_path,manifest_sha256,Authority(),owner)
    return manifest,view['items'][0]

def prepare_target(owner,manifest_path,manifest_sha256,*,feedback_service,feedback_intent,
                   key,submitted_at,consent_ref):
    if type(key)is not str or not re.fullmatch('[a-z0-9][a-z0-9-]{7,63}',key):
        raise KnowledgeError('fixed target intent required')
    if type(consent_ref)is not str or not consent_ref:raise KnowledgeError('target consent required')
    manifest,view=candidate(owner,manifest_path,manifest_sha256)
    if feedback_service.binding.config['scope']!=manifest['scope_tuple']:
        raise KnowledgeError('target feedback scope mismatch')
    lineage=feedback_lineage(feedback_service,feedback_intent)
    public_raw=protected_bytes(manifest['public_source']['path'])
    if sha(public_raw)!=manifest['public_source']['sha256']:raise KnowledgeError('target public source changed')
    public=json.loads(public_raw)
    if public['record_hash']!=lineage['record_hash']or public['request']!=lineage['request']:
        raise KnowledgeError('target feedback source mismatch')
    target=manifest['draft_target_ref']
    payload={'schema':'crowd-owner-materialized-target-v1','candidate_hash':target['hash'],
      'candidate_files':{n:r['sha256']for n,r in manifest['files'].items()},
      'target_ref':target,'generation_base_ref':manifest['proposal_base_ref'],
      'generation_proposal_id':manifest['proposal_id'],'generation_manifest_sha256':manifest_sha256,
      'same_input_comparison_sha256':manifest['same_input_comparison']['sha256'],
      'source_lineage':lineage,'objects':view['objects'],
      'generation':{'provider':'ExternalArtifactProvider','execution_verified':False,
                    'artifact_sha256':manifest['artifact']['sha256']},
      'claim_status':'pending_unknown_observation_not_restaurant_quality_fact'}
    # Original Owner contract: target pack_ref identifies the candidate that
    # human review/release must name. Generation's0.1.1 base stays separate.
    sources=[{'category':'model_proposal','locator':manifest['proposal_id'],
              'version':manifest['proposal_base_ref']['version'],'hash':manifest['candidate_payload']['sha256']},
             {'category':'consumer_preference','locator':lineage['feedback_id'],
              'version':feedback_intent,'hash':lineage['feedback_sha256']},
             {'category':'consumer_preference','locator':'material-gap-intent:'+lineage['gap_id'],
              'version':lineage['gap_id'],'hash':lineage['gap_event_sha256']}]
    envelope={'contract_version':'ctfs-knowledge-envelope/0.1','submission_id':key,
      'project_id':owner.auth.project,'pack_ref':target,'channel':'owner','actor':{'ref':owner.auth.actor_ref},
      'purpose':'materialized_target_review','consent_ref':consent_ref,'consent':{'scope':'private',
      'granted_at':submitted_at,'granted_by':owner.auth.actor_ref},'source_refs':sources,
      'payload_ref':{'store':'inline','key':key,'type':'proposal','hash':sha(canonical(payload))},
      'operation':'propose','idempotency_key':key,'submitted_at':submitted_at}
    return {'envelope':envelope,'payload':payload,'expected_proposal_id':'prop:'+key}

def propose_target(owner,manifest_path,manifest_sha256,**arguments):
    prepared=prepare_target(owner,manifest_path,manifest_sha256,**arguments)
    envelope,payload=prepared['envelope'],prepared['payload']
    receipt=owner.propose(envelope,payload)
    return {'receipt':receipt,'payload':payload,'envelope':envelope,
            'proposal':owner.get_proposal(prepared['expected_proposal_id']),'human_review_performed':False,
            'release_or_pin_performed':False}
