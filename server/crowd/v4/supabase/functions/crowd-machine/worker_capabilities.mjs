import{assert,canonical,hex,sha,uuid}from'./contract.mjs';
const E='invalid_worker_capability',COMMIT='d32dd565277116ba4880c28ccd417a7c376cb62d';
const REASONS=['ready','not_configured','dependency_unavailable','identity_unverified','login_in_progress','unsupported_scope','source_changed','preflight_failed'];
const int=(x,min=0)=>Number.isSafeInteger(x)&&x>=min;
function exact(v,keys){assert(v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).length===keys.length&&keys.every(k=>Object.hasOwn(v,k)),E);}
export function validateReadinessReport(v){
 exact(v,['schema','report_id','sequence','observed_at_ms','host','state','reason_code','source_readiness']);
 assert(v.schema==='crowd-worker-capabilities-v1'&&uuid(v.report_id)&&int(v.sequence,1)&&int(v.observed_at_ms,1),E);
 exact(v.host,['os','arch']);assert(['darwin','linux','windows','android','ios','unknown'].includes(v.host.os)&&['arm64','x64','x86','unknown'].includes(v.host.arch),E);
 assert(['ready','not_ready'].includes(v.state)&&REASONS.includes(v.reason_code)&&Array.isArray(v.source_readiness),E);
 assert(v.state==='ready'?v.reason_code==='ready'&&v.source_readiness.length===1:v.reason_code!=='ready'&&v.source_readiness.length===0,E);
 for(const s of v.source_readiness){
  exact(s,['schema','engine','protocol','platform','mode','scope','comments','replies','media','max_items','max_comments','source_commit','identity_basis','identity_verified_at_ms','session_generation','session_ref','binding_sha256']);
  assert(s.schema==='crowd-pro-source-readiness-v1'&&s.engine==='mediacrawler_pro'&&s.protocol==='vox-acquisition-v1'&&s.platform==='xhs'&&s.mode==='detail'&&s.scope==='xhs_detail_body_comments_v1'&&s.comments===true&&s.replies===true&&s.media===false&&s.max_items===1&&s.max_comments===200&&s.source_commit===COMMIT,E);
  assert(s.identity_basis==='cached_authenticated_self_id'&&int(s.identity_verified_at_ms,1)&&s.identity_verified_at_ms<=v.observed_at_ms&&int(s.session_generation,1)&&hex(s.session_ref)&&hex(s.binding_sha256),E);
  assert(['darwin','linux','windows'].includes(v.host.os)&&v.host.arch!=='unknown',E);
 }
 assert(new TextEncoder().encode(canonical(v)).length<=16384,E);return v;
}
export async function workerCapabilities(action,payload,backend,actor,workerHash){
 if(action==='worker_capabilities'){
  assert(actor==='owner','principal_denied');assert(payload&&typeof payload==='object'&&!Array.isArray(payload)&&Object.keys(payload).every(k=>['limit','after_worker_id'].includes(k)),E);
  if(Object.hasOwn(payload,'limit'))assert(int(payload.limit,1)&&payload.limit<=100,E);
  if(Object.hasOwn(payload,'after_worker_id'))assert(uuid(payload.after_worker_id),E);
 }else{
  assert(actor==='worker','principal_denied');
  if(action==='worker_capability_report'){
   const report=validateReadinessReport(payload),canonical_report=canonical(report);payload={report,canonical_report,report_hash:await sha('crowd-machine-capability-report-v1\n'+canonical_report)};
  }else{assert(action==='worker_capability_status',E);assert(payload&&typeof payload==='object'&&!Array.isArray(payload)&&Object.keys(payload).every(k=>k==='report_id'),E);if(Object.hasOwn(payload,'report_id'))assert(uuid(payload.report_id),E);}
 }
 const r=await backend.rpc('crowd_machine_capability_rpc',{p_owner_scope:'crowd-owner-main',p_actor_kind:actor,p_worker_hash:workerHash,p_action:action,p_payload:payload});
 if(r.error)throw new Error(['principal_denied','worker_revoked',E,'capability_report_conflict','capability_sequence_conflict','capability_observation_stale','capability_report_not_found','capability_hash_mismatch'].includes(r.error.message)?r.error.message:'backend_unavailable');
 return r.data;
}
