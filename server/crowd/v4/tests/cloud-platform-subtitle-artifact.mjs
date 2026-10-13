import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
import {randomUUID} from 'node:crypto';
import {handleMachine} from '../supabase/functions/crowd-machine/core.mjs';
import {captureHash,sha} from '../supabase/functions/crowd-machine/contract.mjs';
import {transcriptPayload} from '../supabase/functions/crowd-machine/transcript_contract.mjs';
import {artifactCanonical} from '../supabase/functions/crowd-machine/artifact_contract.mjs';
const {PGlite}=createRequire(import.meta.url)(path.join(process.env.CROWD_TEST_TOOLS||'/private/tmp/crowd-fix-tools','node_modules/@electric-sql/pglite'));
const folder=fs.mkdtempSync(path.join(os.tmpdir(),'subtitle-rpc-')),db=new PGlite(folder);
const owner='a'.repeat(64),worker='b'.repeat(64),ownerHash=await sha(owner);let cases=0;
const backend={async rpc(name,args){try{const values=name==='crowd_transcript_artifact_rpc'?[args.p_owner_scope,args.p_actor_kind,args.p_action,JSON.stringify(args.p_payload)]:[args.p_owner_scope,args.p_actor_kind,args.p_worker_hash,args.p_action,JSON.stringify(args.p_payload)];return{data:(await db.query(name==='crowd_transcript_artifact_rpc'?'select public.crowd_transcript_artifact_rpc($1,$2,$3,$4) result':'select public.crowd_machine_rpc($1,$2,$3,$4,$5) result',values)).rows[0].result};}catch(error){return{error:{message:error.message}}}}};
async function call(action,payload={},workerRole=false){const response=await handleMachine(new Request('https://offline.invalid',{method:'POST',headers:{'Content-Type':'application/json',[workerRole?'X-Crowd-Worker-Key':'X-Crowd-Owner-Key']:workerRole?worker:owner},body:JSON.stringify({action,payload})}),backend,ownerHash);return{status:response.status,...await response.json()}}
async function good(action,payload={},workerRole=false){const r=await call(action,payload,workerRole);assert.equal(r.ok,true,JSON.stringify(r));return r.result}
async function direct(payload){
 const canonical_transcript=artifactCanonical(payload);
 const normalized={...payload,canonical_transcript,artifact_hash:await sha('crowd-transcript-artifact-v1\n'+canonical_transcript)};
 return db.query('select public.crowd_transcript_artifact_rpc($1,$2,$3,$4) result',['crowd-owner-main','owner','transcript_put',JSON.stringify(normalized)]);
}
try{
 await db.exec('create role anon;create role authenticated;create role service_role bypassrls;');
 await db.exec(fs.readFileSync(new URL('../cloud_machine.sql',import.meta.url),'utf8'));
 for(const name of ['20261012080647_crowd_transcript_artifact.sql','20261012153031_crowd_subtitle_report.sql','20261012163143_crowd_platform_subtitle_report.sql'])await db.exec(fs.readFileSync(new URL('../supabase/migrations/'+name,import.meta.url),'utf8'));
 await db.exec(fs.readFileSync(new URL('../supabase/migrations/20261012163143_crowd_platform_subtitle_report.sql',import.meta.url),'utf8'));
 await db.exec(fs.readFileSync(new URL('../supabase/migrations/20261013020000_crowd_video_ocr_report.sql',import.meta.url),'utf8'));
 await db.exec(fs.readFileSync(new URL('../supabase/migrations/20261013061140_crowd_declared_subtitle_report.sql',import.meta.url),'utf8'));cases++;
 await good('worker_pair',{worker_id:randomUUID(),worker_key:worker,name:'offline-subtitle',platforms:['dy'],expires_at:new Date(Date.now()+86400000).toISOString()});
 const task=(await good('task_create',{platforms:['dy'],mode:'detail',targets_by_platform:{dy:['7405123456789012345']},desired_items:1,max_api_requests:12,media:true,platform_options_by_platform:{dy:{transcript_only:true}},purpose:'noncommercial_research',idempotency_key:randomUUID()})).task;
 const lease=(await good('claim',{claim_id:randomUUID()},true)).lease,local=randomUUID(),job=randomUUID();
 await good('heartbeat',{run_id:lease.run_id,lease_epoch:lease.lease_epoch,sequence:1,local_run_id:local},true);
 const record={kind:'content',platform:'douyin',content_id:'117355149531810',title:'offline',body:'saved',source_kind:'mediacrawler_api',reward_eligible:false,origin:{run_id:local,file_sha256:'f'.repeat(64),line:1}};
 const envelope={schema:'crowd-machine-capture-v1',capture_id:randomUUID(),task_id:task.task_id,child_id:lease.child_id,run_id:lease.run_id,lease_epoch:lease.lease_epoch,platform:'douyin',delivery_basis:'live_capture',source_kind:'machine_api',record,adapter_version:'test',normalizer_version:'test',packaged_at:new Date().toISOString()};
 const envelope_hash=await captureHash(envelope);await good('capture',{run_id:lease.run_id,lease_epoch:lease.lease_epoch,envelope,envelope_hash},true);
 const preserved=(await db.query('select to_jsonb(c) child,(select jsonb_agg(to_jsonb(z)) from crowd_machine.captures z) captures from crowd_machine.children c where child_id=$1',[lease.child_id])).rows[0];
 const segments=[{start:0,end:1,text:'原文😀'},{start:1.5,end:2,text:'第二句'}];
 const provenance={provider:'douyin',subtitle_kind:'platform_auto',language:'ai-zh',track_id:'123',coverage:'source_track_full_duration_candidate',semantic_status:'not_reviewed',semantic_completeness:'unknown',source_body_sha256:'c'.repeat(64),raw_subtitle_sha256:'c'.repeat(64),source_metadata_sha256:'f'.repeat(64),extractor_version:'2026.08.19',extractor_method:'TikTokBaseIE._get_subtitles',content_id:record.content_id,first_seconds:0,last_seconds:2,duration_seconds:2};
 const report={schema:'crowd-platform-subtitle-report-v1',job_id:job,subtitle_source_run_id:local,subtitle_provenance:provenance,local_run_id:local,platform:'douyin',content_id:record.content_id,entity_ref:'douyin:content:'+record.content_id,asset_sha256:'c'.repeat(64),input_hash:'d'.repeat(64),full_result_file_sha256:'e'.repeat(64),duration_seconds:2,segments,text_sha256:await sha(segments.map(r=>r.text).join('\n')),segment_count:2,character_count:6,semantic_review:'not_reviewed',cer:null,human_groundtruth:false,diagnostics_sha256:null,model_manifest_sha256:null,processing_profile:'yt_dlp_native_metadata_subtitle_v1',processor:'yt_dlp_native_metadata_subtitle_v1',text_revision:null};
 const input={idempotency_key:'transcript:'+job,task_id:task.task_id,child_id:lease.child_id,run_id:lease.run_id,lease_epoch:lease.lease_epoch,local_run_id:local,local_job_id:job,source_refs:[{capture_id:envelope.capture_id,envelope_hash}],report_sha256:await sha(JSON.stringify(report)),report_json:JSON.stringify(report)};
 const receipt=(await good('transcript_put',input)).receipt;
 assert.equal(receipt.artifact_kind,'transcript_report');assert.equal(receipt.reward_eligible,false);cases++;
 const fetched=await good('transcript_get',{local_job_id:job});assert.equal(fetched.artifact.report_json,input.report_json);assert.deepEqual(fetched.receipt,receipt);cases++;
 assert.equal((await good('transcript_put',input)).replayed,true);assert.equal((await call('transcript_put',input,true)).status,403);cases+=2;
 assert.equal((await direct(input)).rows[0].result.replayed,true);cases++;
 for(const delta of [{subtitle_source_run_id:randomUUID()},{audio_source_job_id:job},{platform:'weibo'},{processor:'faster_whisper'},{model_manifest_sha256:'f'.repeat(64)},{human_groundtruth:true},{semantic_review:'reviewed'},{segments:[{start:0,end:3,text:'wrong'}]}]){
  const raw=JSON.stringify({...report,...delta}),payload={...input,report_json:raw,report_sha256:await sha(raw)};
  await assert.rejects(transcriptPayload(payload));await assert.rejects(direct(payload));cases++;
 }
 for(const delta of [{provider:'other'},{source_metadata_sha256:'bad'},{extractor_method:'unknown'},{extractor_version:'latest'},{content_id:'mismatch'},{content_id:Number(record.content_id)},{source_metadata_sha256:1},{raw_subtitle_sha256:1},{source_body_sha256:1},{raw_subtitle_sha256:'0'.repeat(64)},{coverage:'partial_or_unknown'},{semantic_completeness:'full'},{last_seconds:3},{first_seconds:0.1},{last_seconds:1.9},{aid:12},{track_id:''},{password:'private'}]){
  const raw=JSON.stringify({...report,subtitle_provenance:{...provenance,...delta}}),payload={...input,report_json:raw,report_sha256:await sha(raw)};
  await assert.rejects(transcriptPayload(payload));await assert.rejects(direct(payload));cases++;
 }
 const after=(await db.query('select to_jsonb(c) child,(select jsonb_agg(to_jsonb(z)) from crowd_machine.captures z) captures from crowd_machine.children c where child_id=$1',[lease.child_id])).rows[0];assert.deepEqual(after,preserved);cases++;
 console.log(JSON.stringify({ok:true,cases,source_calls:0,model_calls:0,production_writes:0,original_capture_budget_unchanged:true}));
}finally{await db.close();fs.rmSync(folder,{recursive:true,force:true});}
