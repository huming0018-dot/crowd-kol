import {assert,canonical,hex,sha,uuid} from './contract.mjs';
const fields=['task_id','child_id','worker_id','claim_id','run_id','lease_epoch','local_run_id','expected_revision','idempotency_key','expected_finish_hash','capture_count','capture_digest','account_context','proof'];
const proofFields=['continuation_kind','failure_reason','executor_inactive','local_state','exit_code','api_attempts','status_sha256','manifest_sha256','account_state_sha256','seed_sha256','runtime_sha256','identity_binding'];
const exact=(v,keys)=>v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).length===keys.length&&keys.every(k=>Object.hasOwn(v,k));
export async function continuationPayload(payload){
 const denied='source_continuation_denied';assert(exact(payload,fields),denied);
 assert(['task_id','child_id','worker_id','claim_id','run_id','local_run_id'].every(k=>uuid(payload[k])),denied);
 assert(['lease_epoch','expected_revision'].every(k=>Number.isSafeInteger(payload[k])&&payload[k]>=1),denied);
 assert(Number.isSafeInteger(payload.capture_count)&&payload.capture_count>=1&&payload.capture_count<=2000&&hex(payload.capture_digest)&&hex(payload.expected_finish_hash),denied);
 assert(typeof payload.idempotency_key==='string'&&payload.idempotency_key.length>=1&&payload.idempotency_key.length<=160&&!/[\x00-\x1f]/.test(payload.idempotency_key),denied);
 const a=payload.account_context;assert(exact(a,['session_id','generation','account_ref'])&&uuid(a.session_id)&&Number.isSafeInteger(a.generation)&&a.generation>=1&&hex(a.account_ref),denied);
 const p=payload.proof;assert(exact(p,proofFields)&&p.continuation_kind==='wb-replies-v1'&&p.failure_reason==='wb_embedded_replies_incomplete'&&p.executor_inactive===true&&p.local_state==='failed'&&p.exit_code===74&&Number.isSafeInteger(p.api_attempts)&&p.api_attempts>=0&&p.api_attempts<=500&&['first_verified_subject','same_verified_subject'].includes(p.identity_binding),denied);
 assert(['status_sha256','manifest_sha256','account_state_sha256','seed_sha256','runtime_sha256'].every(k=>hex(p[k])),denied);
 const semantic={...payload};delete semantic.expected_revision;const canonical_audit=canonical(semantic);
 assert(new TextEncoder().encode(canonical_audit).length<=8192,denied);
 return {...payload,canonical_audit,audit_hash:await sha('crowd-source-continuation-v1\n'+canonical_audit)};
}
