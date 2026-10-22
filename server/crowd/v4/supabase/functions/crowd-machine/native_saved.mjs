import {assert,canonical,hex,sha} from './contract.mjs';
export const NOTE_COLUMNS='id nickname creator_hash add_ts last_modify_ts note_id type title desc video_url time last_update_time liked_count collected_count comment_count share_count image_list tag_list note_url source_keyword'.split(' ');
export const COMMENT_COLUMNS='id nickname creator_hash add_ts last_modify_ts comment_id create_time note_id content sub_comment_count pictures parent_comment_id like_count note_url target_comment_id'.split(' ');
const integerColumns=new Set('id add_ts last_modify_ts time last_update_time create_time'.split(' '));
const requiredText=new Set('note_id comment_id content sub_comment_count like_count'.split(' '));
const error='invalid_native_saved';
function exact(v,keys){assert(v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).length===keys.length&&keys.every(k=>Object.hasOwn(v,k)),error);}
function key(v){assert(typeof v==='string'&&v.length>=1&&v.length<=160&&!/[\x00-\x1f]/.test(v),error);}
function sensitive(v){assert(!/(?:cookie|authorization|password|access_token|refresh_token|private_key)\s*[=:]|[?&](?:xsec_token|xsec_source|access_token|token)=/i.test(canonical(v)),'sensitive_native_saved');}
export async function nativeSavedPayload(payload){
  exact(payload,['schema','idempotency_key','source','records']);key(payload.idempotency_key);
  assert(payload.schema==='crowd-owner-native-saved-v1',error);
  exact(payload.source,['platform','kind','sdk_commit','snapshot_sha256']);
  assert(payload.source.platform==='xiaohongshu'&&payload.source.kind==='mediacrawler_pro_native_sqlite'&&/^[a-f0-9]{40}$/.test(payload.source.sdk_commit)&&hex(payload.source.snapshot_sha256),error);
  assert(Array.isArray(payload.records)&&payload.records.length>=1&&payload.records.length<=1000,error);
  let note=null;const comments=new Map(),seen=new Set();
  for(const item of payload.records){
    exact(item,['native_table','native_id','record','native_row_sha256','url_redaction','record_sha256']);
    assert(['xhs_note','xhs_note_comment'].includes(item.native_table)&&typeof item.native_id==='string'&&/^[A-Za-z0-9_-]{1,100}$/.test(item.native_id)&&hex(item.native_row_sha256)&&hex(item.record_sha256),error);
    const id=item.native_table+':'+item.native_id;assert(!seen.has(id),error);seen.add(id);
    const cols=item.native_table==='xhs_note'?NOTE_COLUMNS:COMMENT_COLUMNS;exact(item.record,cols);
    for(const c of cols){const v=item.record[c];assert(integerColumns.has(c)?Number.isSafeInteger(v):(typeof v==='string'||v===null&&!requiredText.has(c)),error);if(typeof v==='string')assert(v.length<=100000,error);}
    assert(item.native_id===item.record[item.native_table==='xhs_note'?'note_id':'comment_id'],error);
    // Only public source URLs enter central storage; local raw URL is represented by a digest.
    assert(typeof item.record.note_url==='string'&&/^https?:\/\/(?:www\.)?xiaohongshu\.com\/explore\/[A-Za-z0-9_-]+\/?$/.test(item.record.note_url),error);
    exact(item.url_redaction,['field','original_url_sha256','removed_query_keys','removed_fragment']);const r=item.url_redaction;
    assert(r.field==='note_url'&&hex(r.original_url_sha256)&&typeof r.removed_fragment==='boolean'&&Array.isArray(r.removed_query_keys)&&r.removed_query_keys.length<=32&&r.removed_query_keys.every(k=>typeof k==='string'&&/^[A-Za-z0-9_.-]{1,80}$/.test(k))&&canonical(r.removed_query_keys)===canonical([...new Set(r.removed_query_keys)].sort()),error);
    assert(await sha('crowd-owner-native-record-v1\n'+canonical({native_table:item.native_table,native_id:item.native_id,record:item.record}))===item.record_sha256,'native_saved_hash_mismatch');
    sensitive(item.record);
    if(item.native_table==='xhs_note'){assert(note===null,error);note=item;}else comments.set(item.native_id,item);
  }
  assert(note!==null,error);
  for(const item of comments.values()){
    assert(item.record.note_id===note.native_id,error);let parent=item.record.parent_comment_id;const visited=new Set([item.native_id]);
    while(parent!==null&&parent!==''&&parent!=='0'){assert(typeof parent==='string'&&comments.has(parent)&&!visited.has(parent),error);visited.add(parent);parent=comments.get(parent).record.parent_comment_id;}
  }
  const canonical_payload=canonical(payload);assert(new TextEncoder().encode(canonical_payload).length<=250000,error);
  return {envelope:payload,canonical_payload,batch_hash:await sha('crowd-owner-native-batch-v1\n'+canonical_payload)};
}
export async function handleNativeSaved(action,payload,backend,actor){
  assert(actor==='owner','principal_denied');
  if(action==='native_saved_put')payload=await nativeSavedPayload(payload);
  else{exact(payload,['idempotency_key']);key(payload.idempotency_key);}
  const response=await backend.rpc('crowd_owner_native_saved_rpc',{p_owner_scope:'crowd-owner-main',p_actor_kind:actor,p_action:action,p_payload:payload});
  if(response.error){const code=response.error.message;throw new Error(['principal_denied','invalid_native_saved','sensitive_native_saved','native_saved_hash_mismatch','native_saved_conflict','native_saved_not_found'].includes(code)?code:'backend_unavailable');}
  return response.data;
}
