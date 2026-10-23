import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
import {randomUUID} from 'node:crypto';
import {handleMachine} from '../supabase/functions/crowd-machine/core.mjs';
import {canonical,captureHash,sha} from '../supabase/functions/crowd-machine/contract.mjs';
import {artifactPayload} from '../supabase/functions/crowd-machine/artifact_contract.mjs';
process.on('uncaughtException',error=>{console.error(JSON.stringify({error:error.message,code:error.code,detail:error.detail,where:error.where?.slice(0,500)}));process.exitCode=1;});
const {PGlite}=createRequire(import.meta.url)(path.join(process.env.CROWD_TEST_TOOLS||'/private/tmp/crowd-fix-tools','node_modules/@electric-sql/pglite'));
const directory=fs.mkdtempSync(path.join(os.tmpdir(),'crowd-artifact-')),db=new PGlite(directory);
const ownerKey='a'.repeat(64),workerKey='b'.repeat(64),ownerHash=await sha(ownerKey),workerId=randomUUID();let cases=0;
const backend={async rpc(name,args){try{
 const query=name==='crowd_analysis_artifact_rpc'?'select public.crowd_analysis_artifact_rpc($1,$2,$3,$4) result':'select public.crowd_machine_rpc($1,$2,$3,$4,$5) result';
 const values=name==='crowd_analysis_artifact_rpc'?[args.p_owner_scope,args.p_actor_kind,args.p_action,JSON.stringify(args.p_payload)]:[args.p_owner_scope,args.p_actor_kind,args.p_worker_hash,args.p_action,JSON.stringify(args.p_payload)];
 return{data:(await db.query(query,values)).rows[0].result};}catch(error){return{error:{message:error.message}};}}};
async function call(action,payload={},worker=false){const response=await handleMachine(new Request('https://offline.invalid/functions/v1/crowd-machine',{method:'POST',headers:{'Content-Type':'application/json',[worker?'X-Crowd-Worker-Key':'X-Crowd-Owner-Key']:worker?workerKey:ownerKey},body:JSON.stringify({action,payload})}),backend,ownerHash);return{status:response.status,...await response.json()};}
async function good(action,payload={},worker=false){const value=await call(action,payload,worker);assert.equal(value.ok,true,JSON.stringify(value));return value.result;}
async function rpc(action,payload,actor='owner',scope='crowd-owner-main'){return(await db.query('select public.crowd_analysis_artifact_rpc($1,$2,$3,$4) result',[scope,actor,action,JSON.stringify(payload)])).rows[0].result;}
async function rejectContract(payload){await assert.rejects(artifactPayload(payload));cases++;}
try{
 await db.exec('create role anon;create role authenticated;create role service_role bypassrls;');
 await db.exec(fs.readFileSync(new URL('../cloud_machine.sql',import.meta.url),'utf8'));
 const migration=fs.readFileSync(new URL('../supabase/migrations/20261011145857_crowd_analysis_artifact.sql',import.meta.url),'utf8');
 await db.exec(migration);await db.exec(migration);cases++;
 await good('worker_pair',{worker_id:workerId,worker_key:workerKey,name:'isolated-artifact',platforms:['tieba'],expires_at:new Date(Date.now()+86400000).toISOString()});
 const task=(await good('task_create',{platforms:['tieba'],mode:'detail',targets_by_platform:{tieba:['123']},desired_items:1,max_api_requests:12,purpose:'noncommercial_research',idempotency_key:randomUUID()})).task;
 const lease=(await good('claim',{claim_id:randomUUID()},true)).lease,local=randomUUID();
 await good('heartbeat',{run_id:lease.run_id,lease_epoch:lease.lease_epoch,sequence:1,local_run_id:local},true);
 const source_refs=[];
 for(let index=0;index<9;index++){
  const record={kind:index?'comment':'content',platform:'tieba',content_id:'123',title:index?'':'保存标题',body:index?'':'保存正文',source_kind:'mediacrawler_api',reward_eligible:false,origin:{run_id:local,file_sha256:'f'.repeat(64),line:index+1},...(index?{comment_id:String(index),text:'公开评论'+index}:{})};
  const envelope={schema:'crowd-machine-capture-v1',capture_id:randomUUID(),task_id:task.task_id,child_id:lease.child_id,run_id:lease.run_id,lease_epoch:lease.lease_epoch,platform:'tieba',delivery_basis:'live_capture',source_kind:'machine_api',record,adapter_version:'cloud-machine-v1',normalizer_version:'mc-normalized-v2',packaged_at:new Date().toISOString()};
  const hash=await captureHash(envelope);await good('capture',{run_id:lease.run_id,lease_epoch:lease.lease_epoch,envelope,envelope_hash:hash},true);source_refs.push({capture_id:envelope.capture_id,envelope_hash:hash});
 }
 const preserved=(await db.query('select jsonb_build_object(\'claims\',(select jsonb_agg(to_jsonb(h)) from crowd_machine.claims h),\'captures\',(select jsonb_agg(to_jsonb(z) order by z.capture_id) from crowd_machine.captures z),\'child\',(select to_jsonb(c) from crowd_machine.children c where child_id=$1)) value',[lease.child_id])).rows[0].value;
 const derived=randomUUID(),coverage={state:'all_selected_segments_analyzed',batches_completed:3,batches_total:3,selected_segments:1110,selected_characters:12345,source_refs:Array.from({length:1110},(_,index)=>'derived:'+derived+':'+index),semantic_review:'not_reviewed',automatic_retry:false};
 const report={content_analysis:{summary:'完整报告摘要',segments:[],claims:[],reusable_methods:[],limitations:['未听音校对']},comment_statistics:{proportions:{positive:12.5}},comment_labels:[],review_status:'unreviewed_model_analysis',snapshot_hash:'c'.repeat(64),provider:'codex_cli',provider_version:'codex-cli test',full_analysis_coverage:coverage};
 const report_json=JSON.stringify(report),input={idempotency_key:'analysis:'+randomUUID(),task_id:task.task_id,child_id:lease.child_id,run_id:lease.run_id,lease_epoch:lease.lease_epoch,local_run_id:local,source_refs,local_job_id:randomUUID(),input_snapshot_hash:report.snapshot_hash,full_result_file_sha256:'d'.repeat(64),report_sha256:await sha(report_json),provider:report.provider,provider_version:report.provider_version,model_version:null,model_version_status:'not_recorded_by_local_provider',coverage,report_json};
 const payload=await artifactPayload(input),ack=await good('artifact_put',input);assert.equal(ack.receipt.status,'received');assert.equal(ack.receipt.reward_eligible,false);assert.equal(ack.receipt.artifact_kind,'analysis_report');assert.equal(ack.receipt.coverage.selected_segments,1110);cases++;
 const got=await good('artifact_get',{artifact_id:ack.receipt.artifact_id});assert.deepEqual(got.receipt,ack.receipt);assert.equal(got.artifact.report_json,report_json);assert.equal(JSON.parse(got.artifact.report_json).comment_statistics.proportions.positive,12.5);cases++;
 const replay=await good('artifact_put',input);assert.equal(replay.replayed,true);assert.deepEqual(replay.receipt,ack.receipt);cases++;
 for(const change of [{kind:'dynamic'},{content_type:'article'}]){
  const original=(await db.query('select * from crowd_machine.captures where capture_id=$1',[source_refs[0].capture_id])).rows[0];
  const envelope=structuredClone(original.envelope);envelope.capture_id=randomUUID();Object.assign(envelope.record,change);
  const hash=await captureHash(envelope),receipt={...original.receipt,capture_id:envelope.capture_id,envelope_hash:hash};
  await db.query('insert into crowd_machine.captures(capture_id,owner_scope,worker_id,task_id,child_id,run_id,lease_epoch,canonical_envelope,envelope,envelope_hash,receipt) values($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)',[envelope.capture_id,original.owner_scope,original.worker_id,original.task_id,original.child_id,original.run_id,original.lease_epoch,canonical(envelope),JSON.stringify(envelope),hash,JSON.stringify(receipt)]);
  await assert.rejects(rpc('artifact_put',await artifactPayload({...input,idempotency_key:randomUUID(),local_job_id:randomUUID(),source_refs:[...source_refs,{capture_id:envelope.capture_id,envelope_hash:hash}]})),/artifact_source_binding_denied/);cases++;
  await db.query('delete from crowd_machine.captures where capture_id=$1',[envelope.capture_id]);
 }
 assert.equal((await call('artifact_put',input,true)).status,403);assert.equal((await call('artifact_get',{artifact_id:ack.receipt.artifact_id},true)).status,403);cases+=2;
 await assert.rejects(rpc('artifact_put',await artifactPayload({...input,full_result_file_sha256:'0'.repeat(64)})),/artifact_conflict/);cases++;
 for(const change of [{task_id:randomUUID()},{child_id:randomUUID()},{run_id:randomUUID()},{lease_epoch:2},{local_run_id:randomUUID()},{source_refs:[{...source_refs[0],envelope_hash:'0'.repeat(64)}]},{source_refs:source_refs.slice(1)},{source_refs:source_refs.slice(0,1)}]){
  await assert.rejects(rpc('artifact_put',await artifactPayload({...input,...change,idempotency_key:randomUUID(),local_job_id:randomUUID()})),/artifact_source_binding_denied/);cases++;
 }
 for(const change of [{lease_epoch:true},{source_refs:[source_refs[0],source_refs[0]]},{provider:'unknown'},{report_sha256:'0'.repeat(64)},{coverage:{...coverage,batches_completed:2}},{coverage:{...coverage,source_refs:coverage.source_refs.slice(1)}},{coverage:{...coverage,source_refs:[...coverage.source_refs.slice(0,-1),coverage.source_refs[0]]}}])await rejectContract({...input,...change});
 for(const extra of [{password:'hidden'},{input_snapshot:{body:'repeat'}},{audio_base64:'AAA'}]){const raw=JSON.stringify({...report,...extra});await rejectContract({...input,report_json:raw,report_sha256:await sha(raw)});}
 const raw=JSON.stringify({...report,content_analysis:{...report.content_analysis,summary:'password=PRIVATE'}});await rejectContract({...input,report_json:raw,report_sha256:await sha(raw)});
 for(const actor of ['worker','anonymous']){await assert.rejects(rpc('artifact_get',{artifact_id:ack.receipt.artifact_id},actor),/principal_denied/);cases++;}
 await assert.rejects(rpc('artifact_get',{artifact_id:ack.receipt.artifact_id},'owner','another-owner'),/principal_denied/);cases++;
 await assert.rejects(db.query('update crowd_machine.analysis_artifacts set receipt=\'{}\'::jsonb'));cases++;
 await assert.rejects(db.query('delete from crowd_machine.analysis_artifacts'));cases++;
 const priv=(await db.query("select has_function_privilege('anon','public.crowd_analysis_artifact_rpc(text,text,text,jsonb)','execute') rpc,has_table_privilege('authenticated','crowd_machine.analysis_artifacts','select') reads,has_table_privilege('service_role','crowd_machine.analysis_artifacts','update') updates")).rows[0];assert.deepEqual(priv,{rpc:false,reads:false,updates:false});cases++;
 const after=(await db.query('select jsonb_build_object(\'claims\',(select jsonb_agg(to_jsonb(h)) from crowd_machine.claims h),\'captures\',(select jsonb_agg(to_jsonb(z) order by z.capture_id) from crowd_machine.captures z),\'child\',(select to_jsonb(c) from crowd_machine.children c where child_id=$1)) value',[lease.child_id])).rows[0].value;assert.deepEqual(after,preserved);cases++;
 console.log(JSON.stringify({ok:true,cases,source_requests:0,model_calls:0,production_writes:0,original_claim_captures_budget_unchanged:true}));
}finally{await db.close();fs.rmSync(directory,{recursive:true,force:true});}
