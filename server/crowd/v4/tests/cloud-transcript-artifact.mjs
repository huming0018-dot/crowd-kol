import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
import {randomUUID} from 'node:crypto';
import {handleMachine} from '../supabase/functions/crowd-machine/core.mjs';
import {captureHash,sha} from '../supabase/functions/crowd-machine/contract.mjs';
import {transcriptPayload} from '../supabase/functions/crowd-machine/transcript_contract.mjs';
const {PGlite}=createRequire(import.meta.url)(path.join(process.env.CROWD_TEST_TOOLS||'/private/tmp/crowd-fix-tools','node_modules/@electric-sql/pglite'));
const folder=fs.mkdtempSync(path.join(os.tmpdir(),'transcript-rpc-')),db=new PGlite(folder);
const owner='a'.repeat(64),worker='b'.repeat(64),ownerHash=await sha(owner);let cases=0;
const backend={async rpc(name,args){try{const query=name==='crowd_transcript_artifact_rpc'?'select public.crowd_transcript_artifact_rpc($1,$2,$3,$4) result':'select public.crowd_machine_rpc($1,$2,$3,$4,$5) result';const values=name==='crowd_transcript_artifact_rpc'?[args.p_owner_scope,args.p_actor_kind,args.p_action,JSON.stringify(args.p_payload)]:[args.p_owner_scope,args.p_actor_kind,args.p_worker_hash,args.p_action,JSON.stringify(args.p_payload)];return{data:(await db.query(query,values)).rows[0].result};}catch(error){console.error(JSON.stringify({offline_sql_error:error.message}));return{error:{message:error.message}}}}};
async function call(action,payload={},workerRole=false){const response=await handleMachine(new Request('https://offline.invalid',{method:'POST',headers:{'Content-Type':'application/json',[workerRole?'X-Crowd-Worker-Key':'X-Crowd-Owner-Key']:workerRole?worker:owner},body:JSON.stringify({action,payload})}),backend,ownerHash);return{status:response.status,...await response.json()}}
async function good(action,payload={},workerRole=false){const r=await call(action,payload,workerRole);assert.equal(r.ok,true,JSON.stringify(r));return r.result}
const rawrpc=(action,payload,actor='owner',scope='crowd-owner-main')=>db.query('select public.crowd_transcript_artifact_rpc($1,$2,$3,$4) result',[scope,actor,action,JSON.stringify(payload)]);
try{
 await db.exec('create role anon;create role authenticated;create role service_role bypassrls;');
 await db.exec(fs.readFileSync(new URL('../cloud_machine.sql',import.meta.url),'utf8'));
 const sql=fs.readFileSync(new URL('../supabase/migrations/20261012080647_crowd_transcript_artifact.sql',import.meta.url),'utf8');await db.exec(sql);await db.exec(sql);cases++;
 await good('worker_pair',{worker_id:randomUUID(),worker_key:worker,name:'offline-transcript',platforms:['tieba'],expires_at:new Date(Date.now()+86400000).toISOString()});
 const task=(await good('task_create',{platforms:['tieba'],mode:'detail',targets_by_platform:{tieba:['123']},desired_items:1,max_api_requests:12,purpose:'noncommercial_research',idempotency_key:randomUUID()})).task;
 const lease=(await good('claim',{claim_id:randomUUID()},true)).lease,local=randomUUID(),job=randomUUID();
 await good('heartbeat',{run_id:lease.run_id,lease_epoch:lease.lease_epoch,sequence:1,local_run_id:local},true);
 const record={kind:'content',platform:'tieba',content_id:'123',title:'offline',body:'saved',source_kind:'mediacrawler_api',reward_eligible:false,origin:{run_id:local,file_sha256:'f'.repeat(64),line:1}};
 const envelope={schema:'crowd-machine-capture-v1',capture_id:randomUUID(),task_id:task.task_id,child_id:lease.child_id,run_id:lease.run_id,lease_epoch:lease.lease_epoch,platform:'tieba',delivery_basis:'live_capture',source_kind:'machine_api',record,adapter_version:'test',normalizer_version:'test',packaged_at:new Date().toISOString()};
 const envelope_hash=await captureHash(envelope);await good('capture',{run_id:lease.run_id,lease_epoch:lease.lease_epoch,envelope,envelope_hash},true);
 const preserved=(await db.query('select to_jsonb(c) child,(select jsonb_agg(to_jsonb(z)) from crowd_machine.captures z) captures,(select jsonb_agg(to_jsonb(h)) from crowd_machine.claims h) claims from crowd_machine.children c where child_id=$1',[lease.child_id])).rows[0];
 const segments=[{start:0,end:1,text:'原文😀',chunk_index:0},{start:1.5,end:2,text:'第二句',chunk_index:0}];
 const report={schema:'crowd-transcript-report-v1',job_id:job,audio_source_job_id:job,local_run_id:local,platform:'tieba',content_id:'123',entity_ref:null,asset_sha256:'c'.repeat(64),input_hash:'d'.repeat(64),full_result_file_sha256:'e'.repeat(64),duration_seconds:2,segments,text_sha256:await sha(segments.map(r=>r.text).join('\n')),segment_count:2,character_count:6,semantic_review:'not_reviewed',cer:null,human_groundtruth:false,diagnostics_sha256:null,model_manifest_sha256:null,processing_profile:null,processor:'local_asr',text_revision:null};
 const input={idempotency_key:'transcript:'+job,task_id:task.task_id,child_id:lease.child_id,run_id:lease.run_id,lease_epoch:lease.lease_epoch,local_run_id:local,local_job_id:job,source_refs:[{capture_id:envelope.capture_id,envelope_hash}],report_sha256:await sha(JSON.stringify(report)),report_json:JSON.stringify(report)};
 const receipt=(await good('transcript_put',input)).receipt;assert.equal(receipt.artifact_kind,'transcript_report');assert.equal(receipt.segment_count,2);assert.equal(receipt.text_sha256,report.text_sha256);assert.equal(receipt.reward_eligible,false);cases++;
 for(const payload of [{artifact_id:receipt.artifact_id},{local_job_id:job}]){const read=await good('transcript_get',payload);assert.equal(read.artifact.report_json,input.report_json);assert.deepEqual(read.receipt,receipt);cases++;}
 assert.equal((await good('transcript_put',input)).replayed,true);cases++;
 assert.equal((await call('transcript_put',input,true)).status,403);assert.equal((await call('transcript_get',{local_job_id:job},true)).status,403);cases+=2;
 for(const delta of [{lease_epoch:true},{source_refs:[input.source_refs[0],input.source_refs[0]]},{report_sha256:'0'.repeat(64)}]){await assert.rejects(transcriptPayload({...input,...delta}));cases++;}
 for(const delta of [{task_id:randomUUID()},{child_id:randomUUID()},{run_id:randomUUID()},{lease_epoch:2},{local_run_id:randomUUID()},{source_refs:[{capture_id:envelope.capture_id,envelope_hash:'0'.repeat(64)}]}]){await assert.rejects(async()=>rawrpc('transcript_put',await transcriptPayload({...input,...delta})),/transcript_source_binding_denied|invalid_transcript/);cases++;}
 for(const delta of [{cer:0.1},{human_groundtruth:true},{segment_count:1},{character_count:99},{entity_ref:'tieba:answer:other'},{segments:[{start:-1,end:1,text:'wrong'}]},{segments:[{start:0,end:3,text:'wrong'}]},{segments:[{start:true,end:1,text:'wrong'}]},{segments:[{start:0,end:1,text:'password=PRIVATE'}]},{input_snapshot:{text:'duplicated'}}]){const raw=JSON.stringify({...report,...delta});await assert.rejects(transcriptPayload({...input,report_json:raw,report_sha256:await sha(raw)}));cases++;}
 const wrongReport=JSON.stringify({...report,entity_ref:'tieba:dynamic:123'});await assert.rejects(rawrpc('transcript_put',await transcriptPayload({...input,report_json:wrongReport,report_sha256:await sha(wrongReport)})),/transcript_source_binding_denied/);cases++;
 for(const entity_ref of [null,'zhihu:content:123','zhihu:content:123:other']){const raw=JSON.stringify({...report,platform:'zhihu',entity_ref});const denied={...input,report_json:raw,report_sha256:await sha(raw)};await assert.rejects(transcriptPayload(denied),/invalid_transcript/);await assert.rejects(rawrpc('transcript_put',denied),/invalid_transcript/);cases++;}
 for(const actor of ['worker','anonymous']){await assert.rejects(rawrpc('transcript_get',{local_job_id:job},actor),/principal_denied/);cases++;}await assert.rejects(rawrpc('transcript_get',{local_job_id:job},'owner','other-owner'),/principal_denied/);cases++;
 await assert.rejects(db.query('update crowd_machine.transcript_artifacts set receipt=\'{}\'::jsonb'),/transcript_immutable/);await assert.rejects(db.query('delete from crowd_machine.transcript_artifacts'),/transcript_immutable/);cases+=2;
 const permissions=(await db.query("select has_function_privilege('anon','public.crowd_transcript_artifact_rpc(text,text,text,jsonb)','execute') calls,has_table_privilege('authenticated','crowd_machine.transcript_artifacts','select') reads,has_table_privilege('service_role','crowd_machine.transcript_artifacts','update') updates")).rows[0];assert.deepEqual(permissions,{calls:false,reads:false,updates:false});cases++;
 const after=(await db.query('select to_jsonb(c) child,(select jsonb_agg(to_jsonb(z)) from crowd_machine.captures z) captures,(select jsonb_agg(to_jsonb(h)) from crowd_machine.claims h) claims from crowd_machine.children c where child_id=$1',[lease.child_id])).rows[0];assert.deepEqual(after,preserved);cases++;
 console.log(JSON.stringify({ok:true,cases,original_claim_capture_budget_unchanged:true,source_calls:0,model_calls:0,production_writes:0}));
}finally{await db.close();fs.rmSync(folder,{recursive:true,force:true});}
