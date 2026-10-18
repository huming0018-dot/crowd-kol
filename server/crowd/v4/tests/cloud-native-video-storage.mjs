import assert from 'node:assert/strict';
import fs from 'node:fs';import path from 'node:path';import os from 'node:os';
import {createRequire} from 'node:module';import {randomUUID,createHash} from 'node:crypto';
import {handleMachine} from '../supabase/functions/crowd-machine/core.mjs';
import {canonical,captureHash,sha} from '../supabase/functions/crowd-machine/contract.mjs';
import {mediaManifest,MEDIA_BUCKET,MEDIA_LIMIT} from '../supabase/functions/crowd-machine/media_storage_contract.mjs';
import {verifyStorageObject} from '../supabase/functions/crowd-machine/media_storage.mjs';
const {PGlite}=createRequire(import.meta.url)(path.join(process.env.CROWD_TEST_TOOLS||'/private/tmp/crowd-fix-tools','node_modules/@electric-sql/pglite'));
const db=new PGlite(),ownerKey='a'.repeat(64),workerKey='b'.repeat(64),ownerHash=await sha(ownerKey);let cases=0;
const mp4=Buffer.concat([Buffer.from([0,0,0,16]),Buffer.from('ftypisom'),Buffer.alloc(200,7)]);const assetHash=createHash('sha256').update(mp4).digest('hex');
let bucketInfo={id:MEDIA_BUCKET,public:false,file_size_limit:MEDIA_LIMIT,allowed_mime_types:['video/mp4']},objects=new Map(),signs=0,fetches=0;
const backend={async rpc(name,args){try{const media=name==='crowd_video_artifact_rpc';return {data:(await db.query(media?'select public.crowd_video_artifact_rpc($1,$2,$3,$4,$5) result':'select public.crowd_machine_rpc($1,$2,$3,$4,$5) result',[args.p_owner_scope,args.p_actor_kind,args.p_worker_hash,args.p_action,JSON.stringify(args.p_payload)])).rows[0].result};}catch(e){return{error:{message:e.message}};}},storage:{url:'https://test.supabase.co/storage/v1',async getBucket(){return{data:bucketInfo,error:bucketInfo?null:{message:'missing'}};},async createBucket(name,options){bucketInfo={id:name,public:options.public,file_size_limit:options.fileSizeLimit,allowed_mime_types:options.allowedMimeTypes};return{data:bucketInfo};},from(name){assert.equal(name,MEDIA_BUCKET);return{async createSignedUploadUrl(p,options){assert.deepEqual(options,{upsert:false});signs++;return{data:{signedUrl:'https://test.supabase.co/storage/v1/object/upload/sign/'+MEDIA_BUCKET+'/'+p+'?token=signed-sensitive'}};},async createSignedUrl(p){return objects.has(p)?{data:{signedUrl:'https://test.supabase.co/storage/v1/object/sign/'+MEDIA_BUCKET+'/'+p+'?token=download-sensitive'}}:{error:{message:'Object not found'}};}}}}};
const previousFetch=globalThis.fetch;globalThis.fetch=async(url,opts)=>{fetches++;assert.equal(opts.redirect,'error');const p=new URL(url).pathname.split('/'+MEDIA_BUCKET+'/')[1];return new Response(objects.get(p),{headers:{'Content-Length':String(objects.get(p)?.length||0),'Content-Type':'video/mp4'}});};
async function call(action,payload={},worker=false){const r=await handleMachine(new Request('https://offline.invalid',{method:'POST',headers:{'Content-Type':'application/json',[worker?'X-Crowd-Worker-Key':'X-Crowd-Owner-Key']:worker?workerKey:ownerKey},body:JSON.stringify({action,payload})}),backend,ownerHash);return{status:r.status,...await r.json()};}
async function good(action,payload={},worker=false){const r=await call(action,payload,worker);assert.equal(r.ok,true,JSON.stringify(r));cases++;return r.result;}
async function bad(action,payload={},worker=false,expected){const r=await call(action,payload,worker);assert.equal(r.ok,false);if(expected)assert.equal(r.error,expected);cases++;return r;}
try{
 await db.exec('create role anon;create role authenticated;create role service_role bypassrls;');await db.exec(fs.readFileSync(new URL('../cloud_machine.sql',import.meta.url),'utf8'));
 const migration=fs.readFileSync(new URL('../supabase/migrations/20261012000706_crowd_private_video_artifact.sql',import.meta.url),'utf8');await db.exec(migration);await db.exec(migration);const nativeMigration=fs.readFileSync(new URL('../supabase/migrations/20261012010045_crowd_native_video_artifact.sql',import.meta.url),'utf8');await db.exec(nativeMigration);await db.exec(nativeMigration);cases++;
 const worker=randomUUID();await good('worker_pair',{worker_id:worker,worker_key:workerKey,name:'video-test',platforms:['xhs','dy','ks','bili','wb','tieba','zhihu'],expires_at:new Date(Date.now()+86400000).toISOString()});
 const task=(await good('task_create',{platforms:['dy'],mode:'detail',targets_by_platform:{dy:['123']},desired_items:1,max_api_requests:4,purpose:'noncommercial_research',idempotency_key:randomUUID()})).task;
 const lease=(await good('claim',{claim_id:randomUUID()},true)).lease,local=randomUUID();await good('heartbeat',{run_id:lease.run_id,lease_epoch:lease.lease_epoch,sequence:1,local_run_id:local},true);
 const cap=randomUUID(),fileSha='f'.repeat(64),envelope={schema:'crowd-machine-capture-v1',capture_id:cap,task_id:task.task_id,child_id:lease.child_id,run_id:lease.run_id,lease_epoch:lease.lease_epoch,platform:'douyin',delivery_basis:'live_capture',source_kind:'machine_api',adapter_version:'bridge-v1',normalizer_version:'normalize-v1',packaged_at:'2026-10-12T00:00:00Z',record:{kind:'content',platform:'douyin',content_id:'123',body:'actual offline fixture',source_kind:'mediacrawler_api',origin:{run_id:local,file_sha256:fileSha},reward_eligible:false}};
 const envelopeHash=await captureHash(envelope);await good('capture',{run_id:lease.run_id,lease_epoch:lease.lease_epoch,envelope,envelope_hash:envelopeHash},true);
 const job=randomUUID(),payload={idempotency_key:'video:'+job,task_id:task.task_id,child_id:lease.child_id,run_id:lease.run_id,lease_epoch:lease.lease_epoch,local_run_id:local,local_job_id:job,platform:'douyin',content_id:'123',capture_id:cap,envelope_hash:envelopeHash,asset_sha256:assetHash,asset_bytes:mp4.length,duration_ms:2000,source_duration_ms:2000,source_asset_sha256:'d'.repeat(64),source_file_sha256:fileSha,source_reference_sha256:'e'.repeat(64),result_file_sha256:'a'.repeat(64)};
 await bad('media_storage_init',{},true,'principal_denied');bucketInfo=null;await good('media_storage_init');
 await bad('media_prepare',payload,true,'media_owner_preparation_required');
 let r=await good('media_prepare',payload);const aid=r.artifact_id;assert.equal(r.state,'pending');assert(r.upload_url.includes('signed-sensitive'));
 await bad('media_commit',{artifact_id:aid},false,'media_object_missing');await bad('media_get',{artifact_id:aid},false,'media_not_ready');
 const row=(await db.query('select * from crowd_machine.video_artifacts where artifact_id=$1',[aid])).rows[0];objects.set(row.object_path,mp4);
 const done=await good('media_commit',{artifact_id:aid});assert.equal(done.receipt.verification,'server_storage_bytes_sha256');assert.deepEqual(done.receipt.manifest,payload);assert.equal(done.receipt.reward_eligible,false);
 r=await good('media_prepare',payload);assert.equal(r.state,'ready');assert(!Object.hasOwn(r,'upload_url'));await good('media_commit',{artifact_id:aid});await good('media_get',{artifact_id:aid});
 await good('media_get',{artifact_id:aid},true);await good('media_prepare',payload,true);
 await bad('media_prepare',{...payload,asset_sha256:'1'.repeat(64)},false,'media_conflict');
 for(const field of ['capture_id','task_id','run_id','local_run_id','child_id'])await bad('media_prepare',{...payload,[field]:randomUUID()},false,'media_source_binding_denied');
 await bad('media_prepare',{...payload,source_file_sha256:'2'.repeat(64)},false,'media_source_binding_denied');
 await bad('media_prepare',{...payload,envelope_hash:'2'.repeat(64)},false,'media_source_binding_denied');
 for(const [key,value]of [['asset_bytes',true],['asset_bytes',MEDIA_LIMIT+1],['lease_epoch',true],['content_id',123],['duration_ms',0],['duration_ms',2400],['extra','secret']])await bad('media_prepare',{...payload,[key]:value});
 bucketInfo.public=true;await bad('media_get',{artifact_id:aid},false,'media_storage_unavailable');bucketInfo.public=false;
 objects.set(row.object_path,Buffer.alloc(mp4.length,1));await bad('media_commit',{artifact_id:aid},false,'media_object_mismatch');objects.set(row.object_path,mp4);
 const response=await handleMachine(new Request('https://offline.invalid',{method:'POST',headers:{'Content-Type':'application/json','X-Crowd-Owner-Key':ownerKey,Origin:'https://evil.invalid'},body:JSON.stringify({action:'media_get',payload:{artifact_id:aid}})}),backend,ownerHash);assert.equal(response.status,403);cases++;
 await db.exec('set role anon');await assert.rejects(db.query('select public.crowd_video_artifact_rpc($1,$2,$3,$4,$5)',['crowd-owner-main','owner',null,'media_get',JSON.stringify({artifact_id:aid})]));await db.exec('reset role');cases++;
 await assert.rejects(db.query("update crowd_machine.video_artifacts set manifest='{}' where artifact_id=$1",[aid]));cases++;
 await assert.rejects(db.query('delete from crowd_machine.video_artifacts where artifact_id=$1',[aid]));cases++;

 const finish=async(l,ids)=>{const p={run_id:l.run_id,lease_epoch:l.lease_epoch,capture_ids:ids,outcome:'completed',api_attempts:1};await good('finish',{...p,finish_hash:await sha('crowd-machine-finish-v1\n'+canonical(p))},true);};
 await finish(lease,[cap]);
 const platforms={xhs:'xiaohongshu',dy:'douyin',ks:'kuaishou',bili:'bilibili',wb:'weibo',tieba:'tieba',zhihu:'zhihu'};
 for(const [short,platform] of Object.entries(platforms)){
  const locator=short==='xhs'?'0123456789abcdef01234567':short==='bili'?'BV1popx6zEe1':short==='zhihu'?'https://www.zhihu.com/question/123/answer/456':'123';
  const taskN=(await good('task_create',{platforms:[short],mode:'detail',targets_by_platform:{[short]:[locator]},desired_items:1,max_api_requests:4,purpose:'noncommercial_research',idempotency_key:randomUUID()})).task;
  const l=(await good('claim',{claim_id:randomUUID()},true)).lease,localN=randomUUID();await good('heartbeat',{run_id:l.run_id,lease_epoch:l.lease_epoch,sequence:1,local_run_id:localN},true);
  const cid='456',kind=short==='bili'?'dynamic':'content',ctype=short==='zhihu'?'answer':null,rhash='4'.repeat(64),capN=randomUUID();
  const e={...envelope,capture_id:capN,task_id:taskN.task_id,child_id:l.child_id,run_id:l.run_id,lease_epoch:l.lease_epoch,platform,record:{...envelope.record,kind,platform,content_id:cid,record_hash:rhash,origin:{run_id:localN,file_sha256:fileSha},...(ctype?{content_type:ctype}:{})}};
  const eh=await captureHash(e);await good('capture',{run_id:l.run_id,lease_epoch:l.lease_epoch,envelope:e,envelope_hash:eh},true);
  const ref=randomUUID(),n={...payload,manifest_version:2,representation:'native_collected',completeness:'saved_asset_not_full_length_verified',content_kind:kind,content_type:ctype,entity_ref:platform+':'+kind+':'+cid+(ctype?':'+ctype:''),container:'mp4',video_track_present:true,source_record_hash:rhash,idempotency_key:'native:'+ref,local_job_id:ref,task_id:taskN.task_id,child_id:l.child_id,run_id:l.run_id,lease_epoch:l.lease_epoch,local_run_id:localN,platform,content_id:cid,capture_id:capN,envelope_hash:eh,source_asset_sha256:assetHash};
  const protectedN=canonical((await db.query('select to_jsonb(c) child,to_jsonb(cl) claim,to_jsonb(z) capture from crowd_machine.children c join crowd_machine.claims cl using(child_id) join crowd_machine.captures z using(child_id) where z.capture_id=$1',[capN])).rows);
  const prepared=await good('media_prepare',n);const rowN=(await db.query('select * from crowd_machine.video_artifacts where artifact_id=$1',[prepared.artifact_id])).rows[0];objects.set(rowN.object_path,mp4);
  const received=await good('media_commit',{artifact_id:prepared.artifact_id});assert.deepEqual(received.receipt.manifest,n);await good('media_get',{artifact_id:prepared.artifact_id},true);await good('media_prepare',n);
  for(const [key,value] of [['video_track_present',false],['manifest_version',true],['representation','processed_derivative'],['completeness','full_length_verified'],['content_type',platform==='zhihu'?'article':'answer'],['entity_ref',platform+':content:999'],['source_record_hash','8'.repeat(64)],['platform','evil'],['source_asset_sha256','9'.repeat(64)],['asset_bytes',MEDIA_LIMIT+1]])await bad('media_prepare',{...n,[key]:value});
  assert.equal(canonical((await db.query('select to_jsonb(c) child,to_jsonb(cl) claim,to_jsonb(z) capture from crowd_machine.children c join crowd_machine.claims cl using(child_id) join crowd_machine.captures z using(child_id) where z.capture_id=$1',[capN])).rows),protectedN);cases++;
  await finish(l,[capN]);
 }
 const oldReceipt=canonical(done.receipt);await db.exec(nativeMigration);assert.equal(canonical((await good('media_get',{artifact_id:aid})).receipt),oldReceipt);cases++;
 const otherKey='c'.repeat(64),otherWorker=randomUUID();await good('worker_pair',{worker_id:otherWorker,worker_key:otherKey,name:'other-video-worker',platforms:['dy'],expires_at:new Date(Date.now()+86400000).toISOString()});
 const denied=await handleMachine(new Request('https://offline.invalid',{method:'POST',headers:{'Content-Type':'application/json','X-Crowd-Worker-Key':otherKey},body:JSON.stringify({action:'media_get',payload:{artifact_id:aid}})}),backend,ownerHash);assert.equal((await denied.json()).error,'media_not_found');cases++;
 const privileges=(await db.query("select has_function_privilege('anon','public.crowd_video_artifact_rpc(text,text,text,text,jsonb)','execute') rpc,has_table_privilege('authenticated','crowd_machine.video_artifacts','select') reads,has_table_privilege('service_role','crowd_machine.video_artifacts','update') updates")).rows[0];assert.deepEqual(privileges,{rpc:false,reads:false,updates:false});cases++;
 const before=canonical((await db.query('select receipt from crowd_machine.captures where capture_id=$1',[cap])).rows[0].receipt);await db.exec(nativeMigration);assert.equal(canonical((await db.query('select receipt from crowd_machine.captures where capture_id=$1',[cap])).rows[0].receipt),before);cases++;
 console.log(JSON.stringify({status:'PASS_OFFLINE_NATIVE_VIDEO_STORAGE',cases,signs,fetches,source_calls:0,production_writes:0,real_uploads:0}));
}finally{globalThis.fetch=previousFetch;await db.close();}
