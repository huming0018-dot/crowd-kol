// Existing machine Owner authentication wraps this read-only Storage primitive.
import {assert,hex,strictJSON,canonical} from './contract.mjs';
import {publicationJSON} from './publication_json.mjs';
export const PUBLICATION_BUCKET='crowd-publication-snapshots';
const SCOPE='crowd-owner-main',LIMIT=1000000;
const MIME={json:'application/json; charset=utf-8',html:'text/html; charset=utf-8',jsonl:'application/x-ndjson; charset=utf-8',csv:'text/csv; charset=utf-8'};
const TYPES=Object.values(MIME).map(x=>x.split(';')[0]);
const exact=(v,keys)=>v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).length===keys.length&&keys.every(k=>Object.hasOwn(v,k));
const hash=async bytes=>[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(x=>x.toString(16).padStart(2,'0')).join('');
async function readObject(storage,path,limit){
 let r;try{r=await storage.download(path);}catch{assert(false,'publication_storage_unavailable');}assert(!r.error&&r.data&&typeof r.data.arrayBuffer==='function','publication_not_found');
 assert(Number.isSafeInteger(r.data.size)&&r.data.size>0&&r.data.size<=limit,'publication_mismatch');
 const bytes=new Uint8Array(await r.data.arrayBuffer());assert(bytes.length===r.data.size&&bytes.length<=limit,'publication_mismatch');return bytes;
}
function validateManifest(manifest,rid){
 assert(exact(manifest,['schema','owner_scope','report_hash','project_id','as_of','tool_version','item_count','formats','media_bytes_included'])&&manifest.schema==='crowd-publication-snapshot-v1'&&manifest.owner_scope===SCOPE&&manifest.report_hash===rid&&typeof manifest.project_id==='string'&&/^[a-z0-9][a-z0-9-]{0,63}$/.test(manifest.project_id)&&typeof manifest.as_of==='string'&&manifest.as_of.length<=64&&typeof manifest.tool_version==='string'&&manifest.tool_version.length<=32&&Number.isSafeInteger(manifest.item_count)&&manifest.item_count>=1&&manifest.item_count<=2000&&manifest.media_bytes_included===false&&exact(manifest.formats,Object.keys(MIME)),'publication_mismatch');
 for(const [fmt,value]of Object.entries(manifest.formats))assert(exact(value,['sha256','bytes','mime'])&&hex(value.sha256)&&Number.isSafeInteger(value.bytes)&&value.bytes>0&&value.bytes<=LIMIT&&value.mime===MIME[fmt],'publication_mismatch');
 assert(manifest.formats.json.sha256===rid,'publication_mismatch');
}
export async function handlePublication(payload,backend,actor,action='publication_get'){
 assert(actor==='owner','principal_denied');
 if(action!=='publication_get')return writePublication(action,payload,backend,actor);
 assert(exact(payload,['report_hash','format'])&&hex(payload.report_hash)&&typeof payload.format==='string'&&Object.hasOwn(MIME,payload.format),'invalid_publication_request');
 const storage=await verifyBucket(backend),base=`publications/${SCOPE}/${payload.report_hash}/`;
 const manifestBytes=await readObject(storage,base+'manifest.json',16384);
 let manifest;try{manifest=strictJSON(new TextDecoder('utf-8',{fatal:true}).decode(manifestBytes));}catch{assert(false,'publication_mismatch');}
 validateManifest(manifest,payload.report_hash);
 const reportBytes=await readObject(storage,base+'report.json',LIMIT);
 assert(reportBytes.length===manifest.formats.json.bytes&&await hash(reportBytes)===payload.report_hash,'publication_mismatch');
 let report;try{report=publicationJSON(new TextDecoder('utf-8',{fatal:true}).decode(reportBytes));}catch{assert(false,'publication_mismatch');}
 assert(report.project_id===manifest.project_id&&report.as_of===manifest.as_of&&report.tool_version===manifest.tool_version&&Array.isArray(report.items)&&report.items.length===manifest.item_count,'publication_mismatch');
 const fmt=payload.format,bytes=fmt==='json'?reportBytes:await readObject(storage,base+'report.'+fmt,LIMIT),expected=manifest.formats[fmt];
 assert(bytes.length===expected.bytes&&await hash(bytes)===expected.sha256,'publication_mismatch');
 let body;try{body=new TextDecoder('utf-8',{fatal:true}).decode(bytes);}catch{assert(false,'publication_mismatch');}
 return {schema:'crowd-publication-read-v1',owner_scope:SCOPE,report_hash:payload.report_hash,project_id:manifest.project_id,as_of:manifest.as_of,tool_version:manifest.tool_version,item_count:manifest.item_count,format:fmt,mime:expected.mime,bytes:bytes.length,sha256:expected.sha256,body_utf8:body,media_bytes_included:false};
}

// storage-js 2.5.5 preserves HTTP status, not JSON statusCode. Legacy Storage
// can return HTTP 400 for a missing bucket/key; only the exact operation-specific
// StorageApiError message is absence. Other 400/401/403/unknown errors stay closed.
const absent=(r,message)=>{
 const e=r?.error;if(!e)return false;
 if(String(e.statusCode??e.status)==='404')return true;
 return e.name==='StorageApiError'&&e.status===400&&e.message===message;
};
async function verifyBucket(backend,init=false){
 let r;try{r=await backend.storage.getBucket(PUBLICATION_BUCKET);}catch{assert(false,'publication_storage_unavailable');}
 if(init&&absent(r,'Bucket not found')){
  try{await backend.storage.createBucket(PUBLICATION_BUCKET,{public:false,fileSizeLimit:LIMIT,allowedMimeTypes:TYPES});}catch{/* Reconcile the exact fixed bucket once; never update or blindly create again. */}
  try{r=await backend.storage.getBucket(PUBLICATION_BUCKET);}catch{assert(false,'publication_outcome_unknown');}
 }
 const b=r.data;assert(!r.error&&b?.id===PUBLICATION_BUCKET&&b.public===false&&Number(b.file_size_limit)===LIMIT&&Array.isArray(b.allowed_mime_types)&&b.allowed_mime_types.length===4&&TYPES.every(x=>b.allowed_mime_types.includes(x)),'publication_storage_unavailable');
 return backend.storage.from(PUBLICATION_BUCKET);
}
async function sameObject(response,bytes){
 assert(!response.error&&response.data&&typeof response.data.arrayBuffer==='function','publication_outcome_unknown');
 assert(response.data.size===bytes.length,'publication_conflict');
 const actual=new Uint8Array(await response.data.arrayBuffer());assert(actual.length===bytes.length&&await hash(actual)===await hash(bytes),'publication_conflict');
}
async function putImmutable(storage,path,bytes,mime){
 let existing;try{existing=await storage.download(path);}catch{assert(false,'publication_outcome_unknown');}
 if(!existing.error){await sameObject(existing,bytes);return 'existing_exact';}
 assert(absent(existing,'Object not found'),'publication_outcome_unknown');
 try{await storage.upload(path,bytes,{contentType:mime.split(';')[0],upsert:false});}catch{/* Unknown write: read the same object, do not repeat upload. */}
 let after;try{after=await storage.download(path);}catch{assert(false,'publication_outcome_unknown');}
 await sameObject(after,bytes);return 'written_or_reconciled_exact';
}
async function writePublication(action,payload,backend,actor){
 assert(actor==='owner','principal_denied');
 if(action==='publication_storage_init'){
  assert(exact(payload,[]),'invalid_publication_request');await verifyBucket(backend,true);return{bucket_id:PUBLICATION_BUCKET,public:false,initialized:true};
 }
 assert(action==='publication_put'&&exact(payload,['manifest','files'])&&exact(payload.files,Object.keys(MIME)),'invalid_publication_request');
 const m=payload.manifest;validateManifest(m,m?.report_hash);assert(hex(m.report_hash),'publication_mismatch');
 const bodies={};let total=0;
 for(const fmt of Object.keys(MIME)){
  assert(typeof payload.files[fmt]==='string','publication_mismatch');const bytes=new TextEncoder().encode(payload.files[fmt]);
  // Round-trip forbids a lone surrogate being silently replaced on upload.
  assert(new TextDecoder('utf-8',{fatal:true}).decode(bytes)===payload.files[fmt]&&bytes.length===m.formats[fmt].bytes&&await hash(bytes)===m.formats[fmt].sha256,'publication_mismatch');bodies[fmt]=bytes;total+=bytes.length;
 }
 assert(total<=250000,'publication_package_limit');
 let report;try{report=publicationJSON(payload.files.json);}catch{assert(false,'publication_mismatch');}
 assert(report.project_id===m.project_id&&report.as_of===m.as_of&&report.tool_version===m.tool_version&&Array.isArray(report.items)&&report.items.length===m.item_count,'publication_mismatch');
 const storage=await verifyBucket(backend),base=`publications/${SCOPE}/${m.report_hash}/`,states={};
 for(const fmt of Object.keys(MIME))states[fmt]=await putImmutable(storage,base+'report.'+fmt,bodies[fmt],MIME[fmt]);
 // Fixed-schema manifest is the last commit marker; private orphan files are not a publication.
 const manifestBytes=new TextEncoder().encode(canonical(m));assert(manifestBytes.length<=16384,'publication_mismatch');
 states.manifest=await putImmutable(storage,base+'manifest.json',manifestBytes,'application/json');
 return{schema:'crowd-publication-write-v1',report_hash:m.report_hash,project_id:m.project_id,item_count:m.item_count,states,manifest_sha256:await hash(manifestBytes),format_sha256:Object.fromEntries(Object.entries(m.formats).map(([fmt,value])=>[fmt,value.sha256])),media_bytes_included:false,immutable:true,new_collection_performed:false};
}
