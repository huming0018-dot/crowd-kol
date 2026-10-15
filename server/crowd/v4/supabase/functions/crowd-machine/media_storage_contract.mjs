import {sourceCanonical} from './image_storage_contract.mjs';
import {assert,canonical,hex,sha,uuid,strictJSON} from './contract.mjs';
export const MEDIA_BUCKET='crowd-machine-media';
export const MEDIA_LIMIT=50*1024*1024;
export const MEDIA_FIELDS=['idempotency_key','task_id','child_id','run_id','lease_epoch','local_run_id','local_job_id','platform','content_id','capture_id','envelope_hash','asset_sha256','asset_bytes','duration_ms','source_duration_ms','source_asset_sha256','source_file_sha256','source_reference_sha256','result_file_sha256'];
export const NATIVE_FIELDS=['manifest_version','representation','completeness','content_kind','content_type','entity_ref','container','video_track_present','source_record_hash'];
export async function mediaManifest(input){
 if(input?.manifest_version===3)return audioManifest(input);
 const native=input?.manifest_version===2,fields=native?[...MEDIA_FIELDS,...NATIVE_FIELDS]:MEDIA_FIELDS;
 assert(input&&typeof input==='object'&&!Array.isArray(input)&&Object.keys(input).length===fields.length&&fields.every(k=>Object.hasOwn(input,k)),'invalid_media_manifest');
 assert(['task_id','child_id','run_id','local_run_id','local_job_id','capture_id'].every(k=>uuid(input[k])),'invalid_media_manifest');
 assert(['envelope_hash','asset_sha256','source_asset_sha256','source_file_sha256','source_reference_sha256','result_file_sha256'].every(k=>hex(input[k])),'invalid_media_manifest');
 if(native){
  assert(input.idempotency_key==='native:'+input.local_job_id&&['xiaohongshu','douyin','kuaishou','bilibili','weibo','tieba','zhihu'].includes(input.platform)&&typeof input.content_id==='string'&&/^[A-Za-z0-9_.:-]{1,200}$/.test(input.content_id),'invalid_media_manifest');
  assert(input.representation==='native_collected'&&input.completeness==='saved_asset_not_full_length_verified'&&input.container==='mp4'&&input.video_track_present===true&&['content','dynamic'].includes(input.content_kind)&&hex(input.source_record_hash),'invalid_media_manifest');
  assert(input.platform==='zhihu'?input.content_kind==='content'&&['answer','article','zvideo'].includes(input.content_type):input.content_type===null,'invalid_media_manifest');
  assert(input.content_kind!=='dynamic'||input.platform==='bilibili','invalid_media_manifest');
  assert(input.entity_ref===input.platform+':'+input.content_kind+':'+input.content_id+(input.platform==='zhihu'?':'+input.content_type:''),'invalid_media_manifest');
  assert(input.source_asset_sha256===input.asset_sha256&&input.source_duration_ms===input.duration_ms,'invalid_media_manifest');
 }else assert(input.idempotency_key==='video:'+input.local_job_id&&input.platform==='douyin'&&typeof input.content_id==='string'&&/^[0-9]{1,30}$/.test(input.content_id),'invalid_media_manifest');
 assert(Number.isSafeInteger(input.lease_epoch)&&input.lease_epoch>=1&&input.lease_epoch<=2147483647,'invalid_media_manifest');
 assert(Number.isSafeInteger(input.asset_bytes)&&input.asset_bytes>=12&&input.asset_bytes<=MEDIA_LIMIT,'media_size_limit');
 assert(['duration_ms','source_duration_ms'].every(k=>Number.isSafeInteger(input[k])&&input[k]>0&&input[k]<=7200000)&&Math.abs(input.duration_ms-input.source_duration_ms)<=250,'invalid_media_manifest');
 const canonical_manifest=canonical(input);
 return {...input,canonical_manifest,manifest_hash:await sha('crowd-media-video-v'+(native?'2':'1')+'\n'+canonical_manifest)};
}
export function mediaID(input){assert(input&&typeof input==='object'&&!Array.isArray(input)&&Object.keys(input).length===1&&uuid(input.artifact_id),'invalid_media_manifest');return input;}

export const AUDIO_FIELDS=[...MEDIA_FIELDS.filter(k=>k!=='source_file_sha256'),'source_observation_sha256',...NATIVE_FIELDS,'audio_track_present','content_mime','source_record_canonical'];
async function audioManifest(input){
 assert(input&&typeof input==='object'&&!Array.isArray(input)&&Object.keys(input).length===AUDIO_FIELDS.length&&AUDIO_FIELDS.every(k=>Object.hasOwn(input,k)),'invalid_media_manifest');
 assert(['task_id','child_id','run_id','local_run_id','local_job_id','capture_id'].every(k=>uuid(input[k])),'invalid_media_manifest');
 assert(['envelope_hash','asset_sha256','source_asset_sha256','source_observation_sha256','source_reference_sha256','result_file_sha256','source_record_hash'].every(k=>hex(input[k])),'invalid_media_manifest');
 assert(input.manifest_version===3&&input.idempotency_key==='audio:'+input.local_job_id&&input.platform==='bilibili'&&input.content_kind==='content'&&input.content_type===null&&typeof input.content_id==='string'&&/^[1-9][0-9]{0,15}$/.test(input.content_id),'invalid_media_manifest');
 assert(input.representation==='pro_collected_audio'&&input.completeness==='saved_asset_not_full_length_verified'&&input.container==='m4a'&&input.content_mime==='audio/mp4'&&input.audio_track_present===true&&input.video_track_present===false,'invalid_media_manifest');
 assert(input.entity_ref==='bilibili:content:'+input.content_id&&input.source_asset_sha256===input.asset_sha256&&input.source_duration_ms===input.duration_ms,'invalid_media_manifest');
 assert(Number.isSafeInteger(input.lease_epoch)&&input.lease_epoch>=1&&input.lease_epoch<=2147483647,'invalid_media_manifest');
 assert(Number.isSafeInteger(input.asset_bytes)&&input.asset_bytes>=12&&input.asset_bytes<=MEDIA_LIMIT,'media_size_limit');
 assert(['duration_ms','source_duration_ms'].every(k=>Number.isSafeInteger(input[k])&&input[k]>0&&input[k]<=7200000),'invalid_media_manifest');
 let source;try{source=strictJSON(input.source_record_canonical);}catch{throw new Error('invalid_media_manifest');}
 assert(source&&typeof source==='object'&&!Array.isArray(source)&&new TextEncoder().encode(input.source_record_canonical).length<=131072&&sourceCanonical(source)===input.source_record_canonical&&await sha(input.source_record_canonical)===input.source_record_hash&&!Object.hasOwn(source,'record_hash'),'invalid_media_manifest');
 assert(source.platform==='bilibili'&&source.kind==='content'&&source.content_id===input.content_id&&source.source_kind==='mediacrawler_api'&&source.reward_eligible===false&&source.origin?.run_id===input.local_run_id&&source.origin?.observation_sha256===input.source_observation_sha256,'invalid_media_manifest');
 const canonical_manifest=canonical(input);
 return {...input,canonical_manifest,manifest_hash:await sha('crowd-media-audio-v3\n'+canonical_manifest)};
}
