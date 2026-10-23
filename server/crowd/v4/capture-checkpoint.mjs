import { createHash } from 'node:crypto';
import { canonicalJson } from './capture-contract.mjs';
class Rejected extends Error {}
const check=(value,code)=>{if(!value)throw new Rejected(code);};
const uuid=value=>typeof value==='string'&&/^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/.test(value);
const hex=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
const ref=value=>typeof value==='string'&&/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(value);
const snapshot=value=>JSON.parse(canonicalJson(value));
const shape=(value,keys)=>check(value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).length===keys.length&&keys.every(key=>Object.hasOwn(value,key)),'invalid_checkpoint_request');
export const checkpointHash=value=>createHash('sha256').update('crowd-checkpoint-v1\n'+canonicalJson(value)).digest('hex');
async function guarded(work){try{return {data:await work(),error:null};}catch(failure){return {data:null,error:{code:failure instanceof Rejected?failure.message:'checkpoint_unavailable'}};}}
function principal(value){const p=snapshot(value);shape(p,['owner_scope','actor_ref']);check(ref(p.owner_scope)&&ref(p.actor_ref),'invalid_checkpoint_principal');return p;}
async function actorLock(tx,p){const row=(await tx.query('select enabled from capture_receiver.actors where owner_scope=$1 and actor_ref=$2 for update',[p.owner_scope,p.actor_ref])).rows[0];check(row?.enabled,'actor_not_authorized');}
async function registeredRun(tx,p,id){
  check(uuid(id),'invalid_checkpoint_request');
  const run=(await tx.query('select * from capture_budget.runs where owner_scope=$1 and run_id=$2 and actor_ref=$3 for share',[p.owner_scope,id,p.actor_ref])).rows[0];
  check(run,'run_not_authorized');
  const task=(await tx.query('select * from capture_budget.tasks where owner_scope=$1 and task_id=$2 for share',[p.owner_scope,run.task_id])).rows[0];
  const binding={owner_scope:p.owner_scope,actor_ref:p.actor_ref,session_ref:run.session_ref,task_ref:task.task_ref,task_id:task.task_id,
    run_id:run.run_id,lease_epoch:run.lease_epoch,credential_epoch:run.credential_epoch,platform:task.platform,source_kind:run.source_kind,
    parser_version:run.parser_version,normalization_version:run.normalization_version,requested_fields:run.requested_fields,
    target_scope_hash:checkpointHash(task.allowed_targets)};
  return {run,task,binding,bindingHash:checkpointHash(binding)};
}
function pageManifest(input){
  const value=snapshot(input);shape(value,['manifest_version','binding','page']);check(value.manifest_version===1,'unsupported_checkpoint_contract');
  const page=value.page;shape(page,['page_id','sequence','previous_page_hash','cursor_ref','reported_coverage','stop_reason','items']);
  check(uuid(page.page_id)&&Number.isInteger(page.sequence)&&page.sequence>=1&&page.sequence<=1000,'invalid_checkpoint_page');
  check(page.sequence===1?page.previous_page_hash===null:hex(page.previous_page_hash),'invalid_page_chain');
  check(page.cursor_ref===null||typeof page.cursor_ref==='string'&&page.cursor_ref.startsWith('cursor:')&&uuid(page.cursor_ref.slice(7)),'invalid_cursor_ref');
  check(page.reported_coverage==='complete'?page.stop_reason===null:page.reported_coverage==='partial'
    &&['partial_failure','partial_capture','truncated_by_budget','source_incomplete'].includes(page.stop_reason),'invalid_reported_coverage');
  check(Array.isArray(page.items)&&page.items.length<=20,'invalid_checkpoint_page');
  const seen=new Set();
  for(const item of page.items){
    if(item.kind==='capture'){
      shape(item,['kind','capture_id','envelope_hash']);check(uuid(item.capture_id)&&hex(item.envelope_hash),'invalid_checkpoint_item');
      check(!seen.has(item.capture_id),'duplicate_checkpoint_item');seen.add(item.capture_id);
    }else{
      shape(item,['kind','item_ref','error_code']);check(item.kind==='failure'&&typeof item.item_ref==='string'&&item.item_ref.startsWith('item:')&&uuid(item.item_ref.slice(5))
        &&['parse_failed','not_found','private','auth_required','risk_paused','timeout','source_error','receiver_rejected'].includes(item.error_code),'invalid_checkpoint_item');
      check(!seen.has(item.item_ref),'duplicate_checkpoint_item');seen.add(item.item_ref);check(page.reported_coverage==='partial','invalid_reported_coverage');
    }
  }
  return value;
}
function captureMatches(capture,config){
  const e=capture.envelope,b=config.binding;
  return ['owner_scope','actor_ref','session_ref','run_id','lease_epoch','credential_epoch','source_kind'].every(key=>e[key]===b[key])
    &&canonicalJson(e.task_ref)===canonicalJson(b.task_ref)&&e.payload.platform===b.platform
    &&capture.parser_version===b.parser_version&&capture.normalization_version===b.normalization_version
    &&canonicalJson(capture.requested_fields)===canonicalJson(b.requested_fields)
    &&config.task.allowed_targets.some(target=>canonicalJson(target)===canonicalJson(e.target_ref));
}
async function refresh(tx,p,config){
  const id=config.run.run_id;
  await tx.query(`insert into capture_checkpoint.watermarks(owner_scope,run_id,binding_hash,reported_coverage) values($1,$2,$3,'none') on conflict do nothing`,[p.owner_scope,id,config.bindingHash]);
  const prior=(await tx.query('select * from capture_checkpoint.watermarks where owner_scope=$1 and run_id=$2 for update',[p.owner_scope,id])).rows[0];
  check(prior.binding_hash===config.bindingHash,'checkpoint_binding_changed');
  const pages=(await tx.query('select * from capture_checkpoint.pages where owner_scope=$1 and run_id=$2 order by sequence',[p.owner_scope,id])).rows;
  let sequence=0,cursor=null,lastHash=null,reported=pages.length?'complete':'none',blocked=null;
  for(const page of pages){
    if(page.reported_coverage==='partial')reported='partial';
  }
  for(const page of pages){
    if(page.sequence!==sequence+1){blocked='missing_page';break;}
    if(page.previous_page_hash!==lastHash){blocked='page_chain_mismatch';break;}
    const items=(await tx.query(`select i.capture_id,i.envelope_hash,i.item_ref,i.error_code,c.envelope_hash as stored_hash,
      c.envelope,c.parser_version,c.normalization_version,c.requested_fields,c.receipt
      from capture_checkpoint.items i left join capture_receiver.captures c on c.owner_scope=i.owner_scope and c.capture_id=i.capture_id
      where i.owner_scope=$1 and i.run_id=$2 and i.sequence=$3 order by i.item_index`,[p.owner_scope,id,page.sequence])).rows;
    if(!items.length){blocked='empty_page_unverified';break;}
    for(const item of items){
      if(item.item_ref){blocked='item_failed';break;}
      if(!item.envelope){blocked='capture_missing';break;}
      if(item.stored_hash!==item.envelope_hash){blocked='capture_hash_mismatch';break;}
      if(!captureMatches(item,config)){blocked='capture_binding_mismatch';break;}
      if(item.receipt.status!=='received'||item.receipt.envelope_hash!==item.stored_hash
        ||!['capture_id','run_id','lease_epoch','credential_epoch','admission_id'].every(key=>item.receipt[key]===item.envelope[key])){blocked='receipt_invalid';break;}
      if(item.envelope.completeness.status==='partial')reported='partial';
    }
    if(blocked)break;
    sequence=page.sequence;cursor=page.cursor_ref;lastHash=page.manifest_hash;
    // ACK all declared items, but stop at an explicitly incomplete discovery page.
    if(['truncated_by_budget','source_incomplete','partial_failure'].includes(page.manifest.page.stop_reason)){blocked='partial_discovery';break;}
  }
  await tx.query(`update capture_checkpoint.watermarks set acknowledged_sequence=$3,cursor_ref=$4,last_page_hash=$5,
    reported_coverage=$6,blocked_reason=$7,updated_at=clock_timestamp() where owner_scope=$1 and run_id=$2`,[p.owner_scope,id,sequence,cursor,lastHash,reported,blocked]);
  return {run_id:id,acknowledged_sequence:sequence,cursor_ref:cursor,last_page_hash:lastHash,
    reported_coverage:reported,source_coverage:'unverified',blocked_reason:blocked,known_pages:pages.length};
}

export async function submitCheckpointPage(db,authenticatedPrincipal,input){
  return guarded(async()=>{
    const p=principal(authenticatedPrincipal),manifest=pageManifest(input),page=manifest.page;
    return db.transaction(async tx=>{
      await actorLock(tx,p);const config=await registeredRun(tx,p,manifest.binding?.run_id);
      check(canonicalJson(manifest.binding)===canonicalJson(config.binding),'checkpoint_binding_mismatch');
      const digest=checkpointHash(manifest);
      const old=(await tx.query('select manifest_hash from capture_checkpoint.pages where owner_scope=$1 and run_id=$2 and (sequence=$3 or page_id=$4)',[p.owner_scope,config.run.run_id,page.sequence,page.page_id])).rows;
      if(old.length){check(old.length===1&&old[0].manifest_hash===digest,'page_reused');return {manifest_hash:digest,checkpoint:await refresh(tx,p,config)};}
      const neighbors=(await tx.query('select sequence,manifest_hash,previous_page_hash from capture_checkpoint.pages where owner_scope=$1 and run_id=$2 and sequence in ($3,$4)',[p.owner_scope,config.run.run_id,page.sequence-1,page.sequence+1])).rows;
      for(const neighbor of neighbors)check(neighbor.sequence<page.sequence?neighbor.manifest_hash===page.previous_page_hash:neighbor.previous_page_hash===digest,'page_chain_mismatch');
      await tx.query('insert into capture_checkpoint.pages(owner_scope,run_id,sequence,page_id,manifest_hash,previous_page_hash,cursor_ref,reported_coverage,manifest) values($1,$2,$3,$4,$5,$6,$7,$8,$9)',
        [p.owner_scope,config.run.run_id,page.sequence,page.page_id,digest,page.previous_page_hash,page.cursor_ref,page.reported_coverage,manifest]);
      for(const [index,item]of page.items.entries()){
        if(item.kind==='capture'){
          const used=(await tx.query('select 1 from capture_checkpoint.items where owner_scope=$1 and run_id=$2 and capture_id=$3',[p.owner_scope,config.run.run_id,item.capture_id])).rows[0];
          check(!used,'capture_already_listed');
        }
        await tx.query('insert into capture_checkpoint.items values($1,$2,$3,$4,$5,$6,$7,$8)',[p.owner_scope,config.run.run_id,page.sequence,index,item.capture_id??null,item.envelope_hash??null,item.item_ref??null,item.error_code??null]);
      }
      return {manifest_hash:digest,checkpoint:await refresh(tx,p,config)};
    });
  });
}
export async function readCheckpoint(db,authenticatedPrincipal,runId){
  return guarded(async()=>{const p=principal(authenticatedPrincipal);return db.transaction(async tx=>{
    await actorLock(tx,p);const config=await registeredRun(tx,p,runId);
    return {binding:config.binding,binding_hash:config.bindingHash,checkpoint:await refresh(tx,p,config)};
  });});
}

export async function readRecoveryAdvice(db,authenticatedPrincipal,grantId){
  return guarded(async()=>{const p=principal(authenticatedPrincipal);check(uuid(grantId),'invalid_checkpoint_request');return db.transaction(async tx=>{
    await actorLock(tx,p);
    const grant=(await tx.query('select * from capture_checkpoint.recovery_grants where grant_id=$1 and owner_scope=$2 and actor_ref=$3 for update',[grantId,p.owner_scope,p.actor_ref])).rows[0];
    check(grant&&!grant.revoked,'recovery_not_authorized');
    const source=await registeredRun(tx,p,grant.source_run_id),target=await registeredRun(tx,p,grant.target_run_id);
    check(grant.source_binding_hash===source.bindingHash&&grant.target_binding_hash===target.bindingHash,'recovery_binding_mismatch');
    check(source.task.task_id===target.task.task_id&&canonicalJson(source.task.task_ref)===canonicalJson(target.task.task_ref),'recovery_task_mismatch');
    check(['session_ref','credential_epoch','platform','source_kind','parser_version','normalization_version','target_scope_hash'].every(key=>source.binding[key]===target.binding[key])
      &&canonicalJson(source.binding.requested_fields)===canonicalJson(target.binding.requested_fields),'cursor_incompatible');
    const session=(await tx.query('select * from capture_budget.sessions where owner_scope=$1 and session_ref=$2 for share',[p.owner_scope,target.run.session_ref])).rows[0];
    check(session?.active&&session.actor_ref===p.actor_ref&&session.platform===target.binding.platform&&session.credential_epoch===target.run.credential_epoch,'recovery_session_invalid');
    check(target.task.current_run_id===target.run.run_id&&target.task.lease_epoch===target.run.lease_epoch,'recovery_target_stale');
    check(!target.task.cancelled&&!target.task.paused&&!target.run.paused,'recovery_target_paused');
    const checkpoint=await refresh(tx,p,source);
    // Fresh database time after ledger work/locks; a stale grant is never returned as advice.
    const time=(await tx.query(`with t as materialized(select clock_timestamp() as at)
      select g.issued_at<=t.at and g.expires_at>t.at as grant_valid,r.lease_until>t.at and task.expires_at>t.at as target_valid
      from t,capture_checkpoint.recovery_grants g,capture_budget.runs r,capture_budget.tasks task
      where g.grant_id=$1 and r.owner_scope=$2 and r.run_id=$3 and task.owner_scope=$2 and task.task_id=$4`,[grantId,p.owner_scope,target.run.run_id,target.task.task_id])).rows[0];
    check(time.grant_valid,'recovery_grant_expired');check(time.target_valid,'recovery_target_expired');
    const blockers=['source_coverage_unverified','old_outbox_drain_unverified'];
    if(checkpoint.blocked_reason)blockers.push(checkpoint.blocked_reason);
    if(checkpoint.reported_coverage==='partial')blockers.push('partial_coverage');
    return {source_run_id:source.run.run_id,target_run_id:target.run.run_id,acknowledged_prefix:checkpoint,
      candidate_cursor_ref:checkpoint.blocked_reason===null&&checkpoint.reported_coverage==='complete'?checkpoint.cursor_ref:null,
      automatic_resume_allowed:false,old_outbox_drain:'unverified',blockers};
  });});
}
