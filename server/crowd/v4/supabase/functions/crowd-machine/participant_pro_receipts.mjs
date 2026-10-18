import {assert,uuid} from './contract.mjs';
const CURSOR=['created_at','request','task_id','subject','installation_id','dispatch_id'];
export async function participantProReceipts(payload,backend,actor){
 assert(actor==='owner','principal_denied');
 assert(payload&&typeof payload==='object'&&!Array.isArray(payload)&&Object.keys(payload).every(k=>['after','limit'].includes(k)),'invalid_request');
 if(Object.hasOwn(payload,'limit'))assert(Number.isSafeInteger(payload.limit)&&payload.limit>=1&&payload.limit<=8,'invalid_request');
 if(payload.after!==undefined&&payload.after!==null){const c=payload.after;
  assert(c&&typeof c==='object'&&!Array.isArray(c)&&Object.keys(c).length===CURSOR.length&&CURSOR.every(k=>Object.hasOwn(c,k)),'invalid_request');
  assert(typeof c.created_at==='string'&&c.created_at.length<=64&&/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)$/.test(c.created_at)&&Number.isFinite(Date.parse(c.created_at))&&Number.isSafeInteger(c.task_id)&&c.task_id>0&&['request','subject','installation_id','dispatch_id'].every(k=>uuid(c[k])),'invalid_request');
 }
 const r=await backend.rpc('crowd_participant_pro_receipts_rpc',{p_owner_scope:'crowd-owner-main',p_actor_kind:actor,p_payload:payload});
 if(r.error)throw new Error(['principal_denied','invalid_request','participant_receipt_feed_limit','participant_receipt_feed_invalid','comment_capture_pending'].includes(r.error.message)?r.error.message:'backend_unavailable');
 assert(r.data&&['crowd-participant-pro-receipt-feed-v1','crowd-participant-pro-receipt-feed-v2'].includes(r.data.schema)&&Array.isArray(r.data.groups)&&r.data.groups.length<=(payload.limit??8)&&typeof r.data.has_more==='boolean','participant_receipt_feed_invalid');
 assert(new TextEncoder().encode(JSON.stringify(r.data)).length<=8*1024*1024,'participant_receipt_feed_limit');
 return r.data;
}
