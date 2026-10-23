import {assert} from './contract.mjs';
import {IMAGE_BUCKET as MEDIA_BUCKET,IMAGE_LIMIT,imageLimit, imageManifest,verifyImageBytes} from './image_storage_contract.mjs';
import {uuid} from './contract.mjs';
function imageID(value){assert(value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).length===1&&uuid(value.artifact_id),'invalid_image_manifest');return value;}
const MEDIA_LIMIT=52428800, MIMES=['video/mp4','image/jpeg','image/png','image/webp'];
const ERRORS=new Set(['principal_denied','worker_revoked','image_owner_preparation_required','image_immutable','invalid_image_manifest','image_source_binding_denied','image_conflict','image_not_found','image_object_mismatch']);
async function rpc(backend,actor,workerHash,action,payload){
 const response=await backend.rpc('crowd_image_artifact_rpc',{p_owner_scope:'crowd-owner-main',p_actor_kind:actor,p_worker_hash:workerHash,p_action:action,p_payload:payload});
 if(response.error)throw new Error(ERRORS.has(response.error.message)?response.error.message:'backend_unavailable');
 return response.data;
}
async function bucket(backend,create=false){
 let response=await backend.storage.getBucket(MEDIA_BUCKET);
 if(create&&!response.error&&response.data?.public===false&&Number(response.data.file_size_limit)===MEDIA_LIMIT&&response.data.allowed_mime_types?.length===1&&response.data.allowed_mime_types[0]==='video/mp4'){const updated=await backend.storage.updateBucket(MEDIA_BUCKET,{public:false,fileSizeLimit:MEDIA_LIMIT,allowedMimeTypes:MIMES});if(updated.error)throw new Error('image_storage_unavailable');response=await backend.storage.getBucket(MEDIA_BUCKET);}
 if(response.error&&create){
  const made=await backend.storage.createBucket(MEDIA_BUCKET,{public:false,fileSizeLimit:MEDIA_LIMIT,allowedMimeTypes:MIMES});
  if(made.error)throw new Error('image_storage_unavailable');
  response=await backend.storage.getBucket(MEDIA_BUCKET);
 }
 assert(!response.error&&response.data?.id===MEDIA_BUCKET&&response.data.public===false&&Number(response.data.file_size_limit)===MEDIA_LIMIT&&Array.isArray(response.data.allowed_mime_types)&&[4,5].includes(response.data.allowed_mime_types.length)&&MIMES.every(m=>response.data.allowed_mime_types.includes(m))&&(response.data.allowed_mime_types.length===4||response.data.allowed_mime_types.includes('audio/mp4')),'image_storage_unavailable');
}
function storageURL(backend,value,path,kind){
 const base=new URL(backend.storage.url),url=new URL(value);
 assert(base.protocol==='https:'&&url.origin===base.origin&&!url.username&&!url.password&&!url.hash&&url.pathname==='/storage/v1/object/'+kind+'/'+MEDIA_BUCKET+'/'+path,'image_storage_unavailable');
 return url.href;
}
export async function verifyImageStorageObject(backend,row,fetcher=fetch){
 const signed=await backend.storage.from(MEDIA_BUCKET).createSignedUrl(row.object_path,60);
 if(signed.error)throw new Error(signed.error.message==='Object not found'?'image_object_missing':'image_storage_unavailable');
 const url=storageURL(backend,signed.data.signedUrl,row.object_path,'sign');
 let response;try{response=await fetcher(url,{redirect:'error',signal:AbortSignal.timeout(90000)});}catch{throw new Error('image_storage_unavailable');}
 if(response.status===404){await response.body?.cancel();throw new Error('image_object_missing');}
 if(response.status!==200||response.headers.get('Content-Range')){await response.body?.cancel();throw new Error('image_storage_unavailable');}
 const declared=response.headers.get('Content-Length');
 if(declared!==null&&(!/^[0-9]{1,10}$/.test(declared)||Number(declared)!==row.manifest.asset_bytes)){await response.body?.cancel();throw new Error('image_object_mismatch');}
 const reader=response.body?.getReader();assert(reader,'image_object_mismatch');let count=0,chunks=[];
 try{
  for(;;){const {done,value}=await reader.read();if(done)break;count+=value.length;assert(count<=imageLimit(row.manifest)&&count<=row.manifest.asset_bytes,'image_object_mismatch');chunks.push(value.slice());}
 }catch(error){throw new Error(error.message==='image_object_mismatch'?error.message:'image_storage_unavailable');}
 finally{await reader.cancel().catch(()=>{});reader.releaseLock();}
 const data=new Uint8Array(count);let offset=0;for(const c of chunks){data.set(c,offset);offset+=c.length;}
 return verifyImageBytes(data,row.manifest);
}
export async function handleImage(action,input,backend,actor,workerHash,fetcher=fetch){
 if(action==='image_storage_init'){assert(actor==='owner'&&input&&typeof input==='object'&&!Array.isArray(input)&&Object.keys(input).length===0,'principal_denied');await bucket(backend,true);return {bucket_id:MEDIA_BUCKET,public:false,file_size_limit:MEDIA_LIMIT};}
 const payload=action==='image_prepare'?await imageManifest(input):imageID(input);
 const row=await rpc(backend,actor,workerHash,action==='image_prepare'?'image_prepare':'image_lookup',payload);
 await bucket(backend);
 if(action==='image_prepare'){
  if(row.state==='ready')return {artifact_id:row.artifact_id,state:'ready',manifest_hash:row.manifest_hash,receipt:row.receipt,replayed:row.replayed};
  const signed=await backend.storage.from(MEDIA_BUCKET).createSignedUploadUrl(row.object_path,{upsert:false});
  assert(!signed.error&&signed.data?.signedUrl,'image_storage_unavailable');
  return {artifact_id:row.artifact_id,state:'pending',manifest_hash:row.manifest_hash,object_path:row.object_path,upload_url:storageURL(backend,signed.data.signedUrl,row.object_path,'upload/sign')};
 }
 if(action==='image_commit'){
  const proof=await verifyImageStorageObject(backend,row,fetcher);
  return rpc(backend,actor,workerHash,'image_commit',{artifact_id:row.artifact_id,...proof});
 }
 assert(action==='image_get'&&row.state==='ready'&&row.receipt,'image_not_ready');
 const signed=await backend.storage.from(MEDIA_BUCKET).createSignedUrl(row.object_path,60);
 assert(!signed.error&&signed.data?.signedUrl,'image_storage_unavailable');
 return {artifact_id:row.artifact_id,state:'ready',receipt:row.receipt,download_url:storageURL(backend,signed.data.signedUrl,row.object_path,'sign')};
}
