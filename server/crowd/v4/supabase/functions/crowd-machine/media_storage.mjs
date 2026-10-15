import {createHash} from 'node:crypto';
import {assert} from './contract.mjs';
import {MEDIA_BUCKET,MEDIA_LIMIT,mediaID,mediaManifest} from './media_storage_contract.mjs';
const ERRORS=new Set(['principal_denied','worker_revoked','media_owner_preparation_required','media_immutable','invalid_media_manifest','media_source_binding_denied','media_conflict','media_not_found','media_object_mismatch']);
async function rpc(backend,actor,workerHash,action,payload){
 const response=await backend.rpc('crowd_video_artifact_rpc',{p_owner_scope:'crowd-owner-main',p_actor_kind:actor,p_worker_hash:workerHash,p_action:action,p_payload:payload});
 if(response.error)throw new Error(ERRORS.has(response.error.message)?response.error.message:'backend_unavailable');
 return response.data;
}
async function bucket(backend,create=false){
 let response=await backend.storage.getBucket(MEDIA_BUCKET);
 if(response.error&&create){
  const made=await backend.storage.createBucket(MEDIA_BUCKET,{public:false,fileSizeLimit:MEDIA_LIMIT,allowedMimeTypes:['video/mp4']});
  if(made.error)throw new Error('media_storage_unavailable');
  response=await backend.storage.getBucket(MEDIA_BUCKET);
 }
 assert(!response.error&&response.data?.id===MEDIA_BUCKET&&response.data.public===false&&Number(response.data.file_size_limit)===MEDIA_LIMIT&&Array.isArray(response.data.allowed_mime_types)&&(response.data.allowed_mime_types.length===1&&response.data.allowed_mime_types[0]==='video/mp4'||response.data.allowed_mime_types.length===4&&['video/mp4','image/jpeg','image/png','image/webp'].every(m=>response.data.allowed_mime_types.includes(m))),'media_storage_unavailable');
}
function storageURL(backend,value,path,kind){
 const base=new URL(backend.storage.url),url=new URL(value);
 assert(base.protocol==='https:'&&url.origin===base.origin&&!url.username&&!url.password&&!url.hash&&url.pathname==='/storage/v1/object/'+kind+'/'+MEDIA_BUCKET+'/'+path,'media_storage_unavailable');
 return url.href;
}
export async function verifyStorageObject(backend,row,fetcher=fetch){
 const signed=await backend.storage.from(MEDIA_BUCKET).createSignedUrl(row.object_path,60);
 if(signed.error)throw new Error(signed.error.message==='Object not found'?'media_object_missing':'media_storage_unavailable');
 const url=storageURL(backend,signed.data.signedUrl,row.object_path,'sign');
 let response;try{response=await fetcher(url,{redirect:'error',signal:AbortSignal.timeout(90000)});}catch{throw new Error('media_storage_unavailable');}
 if(response.status===404){await response.body?.cancel();throw new Error('media_object_missing');}
 if(response.status!==200||response.headers.get('Content-Range')){await response.body?.cancel();throw new Error('media_storage_unavailable');}
 const declared=response.headers.get('Content-Length');
 if(declared!==null&&(!/^[0-9]{1,10}$/.test(declared)||Number(declared)!==row.manifest.asset_bytes)){await response.body?.cancel();throw new Error('media_object_mismatch');}
 const reader=response.body?.getReader();assert(reader,'media_object_mismatch');let count=0,head=new Uint8Array(),hash=createHash('sha256');
 try{
  for(;;){const {done,value}=await reader.read();if(done)break;count+=value.length;assert(count<=MEDIA_LIMIT&&count<=row.manifest.asset_bytes,'media_object_mismatch');hash.update(value);if(head.length<12){const copy=new Uint8Array(Math.min(12,head.length+value.length));copy.set(head);copy.set(value.subarray(0,copy.length-head.length),head.length);head=copy;}}
 }catch(error){throw new Error(error.message==='media_object_mismatch'?error.message:'media_storage_unavailable');}
 finally{await reader.cancel().catch(()=>{});reader.releaseLock();}
 const digest=hash.digest('hex');
 assert(count===row.manifest.asset_bytes&&digest===row.manifest.asset_sha256&&head.length===12&&new TextDecoder().decode(head.subarray(4,8))==='ftyp','media_object_mismatch');
 return {verified_bytes:count,verified_sha256:digest};
}
export async function handleMedia(action,input,backend,actor,workerHash,fetcher=fetch){
 if(action==='media_storage_init'){assert(actor==='owner'&&input&&typeof input==='object'&&!Array.isArray(input)&&Object.keys(input).length===0,'principal_denied');await bucket(backend,true);return {bucket_id:MEDIA_BUCKET,public:false,file_size_limit:MEDIA_LIMIT};}
 const payload=action==='media_prepare'?await mediaManifest(input):mediaID(input);
 const row=await rpc(backend,actor,workerHash,action==='media_prepare'?'media_prepare':'media_lookup',payload);
 await bucket(backend);
 if(action==='media_prepare'){
  if(row.state==='ready')return {artifact_id:row.artifact_id,state:'ready',manifest_hash:row.manifest_hash,receipt:row.receipt,replayed:row.replayed};
  const signed=await backend.storage.from(MEDIA_BUCKET).createSignedUploadUrl(row.object_path,{upsert:false});
  assert(!signed.error&&signed.data?.signedUrl,'media_storage_unavailable');
  return {artifact_id:row.artifact_id,state:'pending',manifest_hash:row.manifest_hash,upload_url:storageURL(backend,signed.data.signedUrl,row.object_path,'upload/sign')};
 }
 if(action==='media_commit'){
  const proof=await verifyStorageObject(backend,row,fetcher);
  return rpc(backend,actor,workerHash,'media_commit',{artifact_id:row.artifact_id,...proof});
 }
 assert(action==='media_get'&&row.state==='ready'&&row.receipt,'media_not_ready');
 const signed=await backend.storage.from(MEDIA_BUCKET).createSignedUrl(row.object_path,60);
 assert(!signed.error&&signed.data?.signedUrl,'media_storage_unavailable');
 return {artifact_id:row.artifact_id,state:'ready',receipt:row.receipt,download_url:storageURL(backend,signed.data.signedUrl,row.object_path,'sign')};
}
