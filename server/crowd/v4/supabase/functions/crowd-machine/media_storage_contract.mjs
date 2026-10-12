import {assert,canonical,hex,sha,uuid} from './contract.mjs';
export const MEDIA_BUCKET='crowd-machine-media';
export const MEDIA_LIMIT=50*1024*1024;
export const MEDIA_FIELDS=['idempotency_key','task_id','child_id','run_id','lease_epoch','local_run_id','local_job_id','platform','content_id','capture_id','envelope_hash','asset_sha256','asset_bytes','duration_ms','source_duration_ms','source_asset_sha256','source_file_sha256','source_reference_sha256','result_file_sha256'];
export async function mediaManifest(input){
 assert(input&&typeof input==='object'&&!Array.isArray(input)&&Object.keys(input).length===MEDIA_FIELDS.length&&MEDIA_FIELDS.every(k=>Object.hasOwn(input,k)),'invalid_media_manifest');
 assert(['task_id','child_id','run_id','local_run_id','local_job_id','capture_id'].every(k=>uuid(input[k])),'invalid_media_manifest');
 assert(['envelope_hash','asset_sha256','source_asset_sha256','source_file_sha256','source_reference_sha256','result_file_sha256'].every(k=>hex(input[k])),'invalid_media_manifest');
 assert(input.idempotency_key==='video:'+input.local_job_id&&input.platform==='douyin'&&typeof input.content_id==='string'&&/^[0-9]{1,30}$/.test(input.content_id),'invalid_media_manifest');
 assert(Number.isSafeInteger(input.lease_epoch)&&input.lease_epoch>=1&&input.lease_epoch<=2147483647,'invalid_media_manifest');
 assert(Number.isSafeInteger(input.asset_bytes)&&input.asset_bytes>=12&&input.asset_bytes<=MEDIA_LIMIT,'media_size_limit');
 assert(['duration_ms','source_duration_ms'].every(k=>Number.isSafeInteger(input[k])&&input[k]>0&&input[k]<=7200000)&&Math.abs(input.duration_ms-input.source_duration_ms)<=250,'invalid_media_manifest');
 const canonical_manifest=canonical(input);
 return {...input,canonical_manifest,manifest_hash:await sha('crowd-media-video-v1\n'+canonical_manifest)};
}
export function mediaID(input){assert(input&&typeof input==='object'&&!Array.isArray(input)&&Object.keys(input).length===1&&uuid(input.artifact_id),'invalid_media_manifest');return input;}
