"""Fixed-config065 Owner target preview; original034 helper stays untouched."""
from pathlib import Path
from collections import Counter
import difflib,hashlib,json,tempfile
from toolbox.knowledge import KnowledgeStore,AuthContext,_candidate_hash
from owner_knowledge_binding import protected_bytes

FILES={'pack.yaml','fields.yaml','pointers.json','validation.yaml','rubric.yaml','expectations.yaml'}
def sha(raw):return hashlib.sha256(raw).hexdigest()
def preview(config):
    required={'workspace','scope','author_actor','reviewer_actor','proposal_id','candidate_pack',
      'candidate_files','candidate_hash','old_pack','old_files','comparison','comparison_sha256','payload_sha256'}
    if set(config)!=required or len(config['scope'])!=3 or config['author_actor']==config['reviewer_actor']:
        raise ValueError('target_preview_config_invalid')
    if set(config['candidate_files'])!=FILES or set(config['old_files'])!=FILES:
        raise ValueError('target_preview_files_invalid')
    comparison_raw=protected_bytes(config['comparison'],1024*1024)
    if sha(comparison_raw)!=config['comparison_sha256']:raise ValueError('target_comparison_changed')
    comparison=json.loads(comparison_raw)
    oldbytes={n:protected_bytes(Path(config['old_pack'])/n,1024*1024)for n in FILES}
    newbytes={n:protected_bytes(Path(config['candidate_pack'])/n,1024*1024)for n in FILES}
    if ({n:sha(b)for n,b in oldbytes.items()}!=config['old_files']or
        {n:sha(b)for n,b in newbytes.items()}!=config['candidate_files']):raise ValueError('target_files_changed')
    with tempfile.TemporaryDirectory(prefix='owner-target-preview-')as directory:
        for n,b in newbytes.items():(Path(directory)/n).write_bytes(b)
        if _candidate_hash(Path(directory))!=config['candidate_hash']:raise ValueError('target_hash_changed')
    auth=AuthContext(**dict(zip(('tenant','project','space'),config['scope'])),role='owner',actor_ref=config['author_actor'])
    store=KnowledgeStore(config['workspace'],auth,read_only=True)
    try:
        proposal=store.get_proposal(config['proposal_id']);sid=proposal['submission_id']
        stored=store.get_payload(sid);receipt=store.get_receipt(sid);evidence=store.get_evidence(sid)
        # Original065 receipt does not return pack_ref. Only after its original
        # Owner ACL succeeds, read this one authorized submission's real ref.
        row=store._conn.execute('SELECT pack_ref_json FROM submissions WHERE submission_id=? AND actor_ref=?',
                                (sid,config['author_actor'])).fetchone()
        target={'pack_id':'social-observations','version':'0.1.2','hash':config['candidate_hash']}
        if (row is None or json.loads(row[0])!=target or receipt['status']!='accepted'
            or sha(stored['payload_bytes'])!=stored['payload_hash']):raise ValueError('target_proposal_changed')
        payload=json.loads(stored['payload_bytes'])
        if (proposal['channel']!='owner'or proposal['owner_actor']!=config['author_actor']or
            proposal['visibility']!='private'or proposal['status']not in {'proposed','review','accepted','rejected'}or
            proposal['base_hash']!=config['candidate_hash']or proposal['version']!='0.1.2'or
            proposal['pack_id']!='social-observations'or
            stored['payload_hash']!=config['payload_sha256']or
            receipt['payload_hash']!=stored['payload_hash']or proposal['payload_hash']!=stored['payload_hash']or
            receipt['channel']!='owner'or receipt['actor_ref']!=config['author_actor']or
            payload['target_ref']!=target or
            payload['candidate_hash']!=config['candidate_hash']or payload['candidate_files']!=config['candidate_files']or
            payload['same_input_comparison_sha256']!=config['comparison_sha256']):
            raise ValueError('target_proposal_changed')
    finally:store.close()
    files=[{'name':n,'old_sha256':sha(oldbytes[n]),'candidate_sha256':sha(newbytes[n]),
      'changed':oldbytes[n]!=newbytes[n],'diff':''.join(difflib.unified_diff(oldbytes[n].decode().splitlines(True),
      newbytes[n].decode().splitlines(True),fromfile='0.1.0/'+n,tofile='0.1.2/'+n))}for n in sorted(FILES)]
    items=[item for task in comparison['tasks']for item in task['items']]
    sources_preserved=bool(items)and all(item['capture_exact']is True for item in items)
    quotes_preserved=bool(items)and all(item['evidence_exact']is True for item in items)
    unknowns=dict(Counter(claim['field']for obj in payload['objects']for claim in obj.get('claims',[])if claim.get('status')=='unknown'))
    return {'state':'pending_human_review'if proposal['status']=='proposed'else proposal['status'],
      'preview_only':True,'proposal_id':proposal['proposal_id'],'proposal_status':proposal['status'],'channel':'owner','visibility':'private',
      'candidate_hash':config['candidate_hash'],'pack_id':proposal['pack_id'],'version':proposal['version'],
      'files':files,'observed_gap':payload['source_lineage']['gap_id'],'source_lineage':payload['source_lineage'],
      'same_raw_sha256':payload['source_lineage']['record_hash'],'same_input_comparison':comparison,
      'added_unknowns':unknowns,'unknown_counts_scope':'candidate_unknown_claims_only_not_material_delta',
      'unchanged_fields':['identity','capture','evidence','traceability_score','as_of'],
      'source_versions_preserved':sources_preserved,'quotes_preserved':quotes_preserved,'evidence_refs':evidence,
      'role_state':{'proposal_author_role':'owner','reviewer_actor_distinct':True,
        'proposal_status':proposal['status'],'preview_performed_review_or_release':False,'human_identity_claimed':False},
      'actions':{'approve':{'enabled':False,'blocked_reason':'explicit_owner_decision_required'},
                 'reject':{'enabled':False,'blocked_reason':'explicit_owner_decision_required'}},
      'generation':payload['generation'],'generation_base_ref':payload['generation_base_ref'],
      'required_before_actions':['Existing authenticated Owner endpoint and exact protected target binding.',
        'Distinct existing reviewer with exact proposal+target hash grant; explicit human decision.',
        'Original065 release requires accepted review naming exact six-file candidate hash; no automatic pin.']}
