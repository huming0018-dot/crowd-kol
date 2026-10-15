import {decodeImage} from './image_decoder.mjs';
import {createHash} from 'node:crypto';
import {assert,canonical,hex,sha,uuid,strictJSON} from './contract.mjs';
export const IMAGE_BUCKET='crowd-machine-media',IMAGE_LIMIT=2*1024*1024;
export const IMAGE_FIELDS=['schema','manifest_version','idempotency_key','task_id','child_id','run_id','lease_epoch','local_run_id','local_job_id','capture_id','envelope_hash','platform','content_kind','content_id','comment_id','entity_ref','media_id','attachment_id','asset_sha256','asset_bytes','content_mime','width','height','frames','pixel_sha256','source_record_hash','source_observation_sha256','source_reference_sha256','source_url_sha256','transport_url_sha256','normalized_sha256','canonical_reference','source_record_canonical'];
const hashes=['envelope_hash','media_id','attachment_id','asset_sha256','pixel_sha256','source_record_hash','source_observation_sha256','source_reference_sha256','source_url_sha256','transport_url_sha256','normalized_sha256'];
// Original normalized records use Python json.dumps(sort_keys=True,
// ensure_ascii=False,separators=(',',':')). Keep that hash domain distinct
// from gateway canonical envelopes (which escape all controls as unicode).
export function sourceCanonical(value){
 canonical(value); // Retain the existing safe-integer, Unicode, depth and node limits.
 const compare=(a,b)=>{const x=Array.from(a,c=>c.codePointAt(0)),y=Array.from(b,c=>c.codePointAt(0));for(let i=0;i<Math.min(x.length,y.length);i++)if(x[i]!==y[i])return x[i]-y[i];return x.length-y.length;};
 const encode=v=>v===null?'null':typeof v==='string'?JSON.stringify(v):typeof v==='boolean'?(v?'true':'false'):typeof v==='number'?String(v===0?0:v):Array.isArray(v)?'['+v.map(encode).join(',')+']':'{'+Object.keys(v).sort(compare).map(k=>JSON.stringify(k)+':'+encode(v[k])).join(',')+'}';
 return encode(value);
}
export async function imageManifest(value){
 assert(value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).length===IMAGE_FIELDS.length&&IMAGE_FIELDS.every(k=>Object.hasOwn(value,k)),'invalid_image_manifest');
 assert(value.schema==='crowd-image-object-v1'&&value.manifest_version===1&&['task_id','child_id','run_id','local_run_id','local_job_id','capture_id'].every(k=>uuid(value[k]))&&hashes.every(k=>hex(value[k])),'invalid_image_manifest');
 assert(value.idempotency_key==='image:'+value.local_job_id&&value.platform==='xiaohongshu'&&['content','comment'].includes(value.content_kind)&&typeof value.content_id==='string'&&/^[A-Za-z0-9_.:-]{1,200}$/.test(value.content_id),'invalid_image_manifest');
 assert(value.content_kind==='comment'?typeof value.comment_id==='string'&&/^[A-Za-z0-9_.:-]{1,200}$/.test(value.comment_id):value.comment_id===null,'invalid_image_manifest');
 assert(value.entity_ref===value.platform+':'+value.content_kind+':'+value.content_id+(value.comment_id?':'+value.comment_id:''),'invalid_image_manifest');
 assert(['lease_epoch','asset_bytes','width','height','frames'].every(k=>Number.isSafeInteger(value[k]))&&value.lease_epoch>=1&&value.lease_epoch<=2147483647&&value.asset_bytes>=1&&value.asset_bytes<=IMAGE_LIMIT&&value.width>=1&&value.width<=16384&&value.height>=1&&value.height<=16384&&value.width*value.height<=16000000&&value.frames===1&&['image/jpeg','image/png','image/webp'].includes(value.content_mime),'invalid_image_manifest');
 assert(typeof value.canonical_reference==='string'&&value.canonical_reference.length<=16000,'invalid_image_manifest');
 let ref;try{ref=strictJSON(value.canonical_reference);}catch{throw new Error('invalid_image_manifest');}
 assert(ref&&typeof ref==='object'&&!Array.isArray(ref)&&canonical(ref)===value.canonical_reference&&await sha(value.canonical_reference)===value.source_reference_sha256&&ref.media_id===value.media_id&&ref.platform===value.platform&&ref.content_id===value.content_id&&(ref.comment_id??null)===value.comment_id&&['image','comment_image','cover'].includes(ref.kind)&&ref.status==='reference_only'&&ref.source_kind==='mediacrawler_api'&&ref.reward_eligible===false&&typeof ref.url==='string'&&!/[\x00-\x20]/.test(ref.url),'invalid_image_manifest');
 let url;try{url=new URL(ref.url);}catch{throw new Error('invalid_image_manifest');}
 assert(['http:','https:'].includes(url.protocol)&&!url.username&&!url.password&&!url.hash&&!url.port&&['xhscdn.com','xhsimg.com'].some(d=>url.hostname===d||url.hostname.endsWith('.'+d)),'invalid_image_manifest');
 const raw=ref.url.match(/^https?:\/\/[^/?#]+([^?#]*)(\?[^#]*)?$/);assert(raw,'invalid_image_manifest');
 const transport=url.protocol==='http:'?'https://'+url.hostname+raw[1]+(raw[2]||''):ref.url;
 assert(await sha(canonical(ref.url))===value.source_url_sha256&&await sha(canonical(transport))===value.transport_url_sha256,'invalid_image_manifest');
 let source;try{source=strictJSON(value.source_record_canonical);}catch{throw new Error('invalid_image_manifest');}assert(source&&typeof source==='object'&&!Array.isArray(source)&&new TextEncoder().encode(value.source_record_canonical).length<=131072&&sourceCanonical(source)===value.source_record_canonical&&await sha(value.source_record_canonical)===value.source_record_hash&&!Object.hasOwn(source,'record_hash'),'invalid_image_manifest');
 const canonical_manifest=canonical(value);return {...value,canonical_manifest,manifest_hash:await sha('crowd-media-image-v1\n'+canonical_manifest)};
}
export async function verifyImageBytes(data,manifest,decode=decodeImage){
 await imageManifest(manifest);
 assert(data instanceof Uint8Array&&data.byteLength===manifest.asset_bytes&&data.byteLength<=IMAGE_LIMIT&&createHash('sha256').update(data).digest('hex')===manifest.asset_sha256,'image_object_mismatch');
 assert(typeof decode==='function','image_decoder_unavailable');
 let decoded;try{decoded=await decode(data);}catch{throw new Error('image_object_mismatch');}
 const formats={'image/jpeg':'JPEG','image/png':'PNG','image/webp':'WEBP'};
 assert(decoded&&decoded.format===formats[manifest.content_mime]&&['width','height','frames'].every(k=>Number.isSafeInteger(decoded[k])&&decoded[k]===manifest[k])&&decoded.pixel_sha256===manifest.pixel_sha256,'image_object_mismatch');
 return {verified_bytes:data.byteLength,verified_sha256:manifest.asset_sha256,verified_pixel_sha256:decoded.pixel_sha256,verified_content_mime:manifest.content_mime,verified_width:decoded.width,verified_height:decoded.height,verified_frames:decoded.frames};
}
