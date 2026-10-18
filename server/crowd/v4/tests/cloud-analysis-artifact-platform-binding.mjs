import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
import {randomUUID} from 'node:crypto';
import {handleMachine} from '../supabase/functions/crowd-machine/core.mjs';
import {artifactPayload} from '../supabase/functions/crowd-machine/artifact_contract.mjs';
import {PLATFORMS,canonical,captureHash,sha} from '../supabase/functions/crowd-machine/contract.mjs';
const {PGlite}=createRequire(import.meta.url)('/private/tmp/crowd-fix-tools/node_modules/@electric-sql/pglite');
const folder=fs.mkdtempSync(path.join(os.tmpdir(),'artifact-platform-')),db=new PGlite(folder),owner='a'.repeat(64),ownerHash=await sha(owner);let cases=0;
process.on('uncaughtException',error=>{console.error(JSON.stringify({error:error.message,code:error.code,position:error.position,where:error.where?.slice(0,1000)}));process.exitCode=1;});
const backend={async rpc(name,args){try{return {data:(await db.query(`select public.${name}($1,$2,$3,$4${name==='crowd_machine_rpc'?',$5':''}) value`,name==='crowd_machine_rpc'?[args.p_owner_scope,args.p_actor_kind,args.p_worker_hash,args.p_action,JSON.stringify(args.p_payload)]:[args.p_owner_scope,args.p_actor_kind,args.p_action,JSON.stringify(args.p_payload)])).rows[0].value,error:null};}catch(e){return {error:{message:e.message}};}}};
async function call(action,payload,key=owner,worker=false){const response=await handleMachine(new Request('http://offline.invalid',{method:'POST',headers:{'Content-Type':'application/json',[worker?'X-Crowd-Worker-Key':'X-Crowd-Owner-Key']:key},body:JSON.stringify({action,payload})}),backend,ownerHash);const json=await response.json();assert.equal(response.status,200,JSON.stringify(json));return json.result;}
const sql=fs.readFileSync(new URL('../supabase/migrations/20261011154518_crowd_analysis_artifact_platform_binding.sql',import.meta.url),'utf8');
try{
 await db.exec('create role anon;create role authenticated;create role service_role bypassrls;');
 await db.exec(fs.readFileSync(new URL('../cloud_machine.sql',import.meta.url),'utf8'));
 await db.exec(fs.readFileSync(new URL('../supabase/migrations/20261011145857_crowd_analysis_artifact.sql',import.meta.url),'utf8'));
 await db.exec(sql);await db.exec(sql);cases++;
 for(const [platform,normalized]of Object.entries(PLATFORMS)){
  const key=(await sha(platform)),worker_id=randomUUID();await call('worker_pair',{worker_id,worker_key:key,name:'fixture',platforms:[platform],expires_at:new Date(Date.now()+86400000).toISOString()});
  const target={xhs:'66fad51c000000001b0224b8',dy:'123',ks:'abc123',bili:'BV1popx6zEe1',wb:'123',tieba:'123',zhihu:'https://zhuanlan.zhihu.com/p/123'}[platform];
  const task=(await call('task_create',{platforms:[platform],mode:'detail',targets_by_platform:{[platform]:[target]},desired_items:1,max_api_requests:12,purpose:'noncommercial_research',idempotency_key:randomUUID()})).task;
  const lease=(await call('claim',{claim_id:randomUUID()},key,true)).lease;assert.ok(lease,'fixture lease missing for '+platform);const local=randomUUID();await call('heartbeat',{run_id:lease.run_id,lease_epoch:lease.lease_epoch,sequence:1,local_run_id:local},key,true);
  const refs=[];
  for(let i=0;i<2;i++){
   const record={kind:i?'comment':'content',platform:normalized,content_id:'123',title:i?'':'公开标题',body:i?'':'公开正文',source_kind:'mediacrawler_api',reward_eligible:false,origin:{run_id:local,file_sha256:'f'.repeat(64),line:i+1},...(i?{comment_id:'1',text:'公开评论'}:{})};
   const envelope={schema:'crowd-machine-capture-v1',capture_id:randomUUID(),task_id:task.task_id,child_id:lease.child_id,run_id:lease.run_id,lease_epoch:lease.lease_epoch,platform:normalized,delivery_basis:'live_capture',source_kind:'machine_api',record,adapter_version:'cloud-machine-v1',normalizer_version:'mc-normalized-v2',packaged_at:new Date().toISOString()};
   const hash=await captureHash(envelope);await call('capture',{run_id:lease.run_id,lease_epoch:lease.lease_epoch,envelope,envelope_hash:hash},key,true);refs.push({capture_id:envelope.capture_id,envelope_hash:hash});
  }
  const before=(await db.query("select jsonb_build_object('claim',(select to_jsonb(q) from crowd_machine.claims q where run_id=$1),'captures',(select jsonb_agg(to_jsonb(z) order by capture_id) from crowd_machine.captures z where run_id=$1),'child',(select to_jsonb(c) from crowd_machine.children c where child_id=$2)) value",[lease.run_id,lease.child_id])).rows[0].value;
  const derived=randomUUID(),coverage={state:'all_selected_segments_analyzed',batches_completed:1,batches_total:1,selected_segments:1,selected_characters:3,source_refs:['derived:'+derived+':0'],semantic_review:'not_reviewed',automatic_retry:false};
  const report={content_analysis:{summary:'有界合成分析'},review_status:'unreviewed_model_analysis',snapshot_hash:'c'.repeat(64),provider:'codex_cli',provider_version:'fixture',full_analysis_coverage:coverage},report_json=JSON.stringify(report);
  const input={idempotency_key:randomUUID(),task_id:task.task_id,child_id:lease.child_id,run_id:lease.run_id,lease_epoch:lease.lease_epoch,local_run_id:local,source_refs:refs,local_job_id:randomUUID(),input_snapshot_hash:'c'.repeat(64),full_result_file_sha256:'d'.repeat(64),report_sha256:await sha(report_json),provider:'codex_cli',provider_version:'fixture',model_version:null,model_version_status:'not_recorded_by_local_provider',coverage,report_json};
  const ack=await call('artifact_put',input);assert.equal(ack.receipt.source_refs.length,2);assert.equal(ack.receipt.reward_eligible,false);cases++;
  assert.equal((await call('artifact_put',input)).replayed,true);cases++;
  const row=(await db.query('select * from crowd_machine.captures where capture_id=$1',[refs[0].capture_id])).rows[0],bad=structuredClone(row.envelope);bad.record.platform=normalized==='bilibili'?'weibo':'bilibili';const badhash=await captureHash(bad),receipt={...row.receipt,envelope_hash:badhash};
  await db.query('update crowd_machine.captures set envelope=$1,canonical_envelope=$2,envelope_hash=$3,receipt=$4 where capture_id=$5',[JSON.stringify(bad),canonical(bad),badhash,JSON.stringify(receipt),row.capture_id]);
  const payload=await artifactPayload({...input,idempotency_key:randomUUID(),local_job_id:randomUUID(),source_refs:[{...refs[0],envelope_hash:badhash},refs[1]]});
  await assert.rejects(db.query('select public.crowd_analysis_artifact_rpc($1,$2,$3,$4)',['crowd-owner-main','owner','artifact_put',JSON.stringify(payload)]),/artifact_source_binding_denied/);cases++;
  await db.query('update crowd_machine.captures set envelope=$1,canonical_envelope=$2,envelope_hash=$3,receipt=$4 where capture_id=$5',[JSON.stringify(row.envelope),row.canonical_envelope,row.envelope_hash,JSON.stringify(row.receipt),row.capture_id]);
  const after=(await db.query("select jsonb_build_object('claim',(select to_jsonb(q) from crowd_machine.claims q where run_id=$1),'captures',(select jsonb_agg(to_jsonb(z) order by capture_id) from crowd_machine.captures z where run_id=$1),'child',(select to_jsonb(c) from crowd_machine.children c where child_id=$2)) value",[lease.run_id,lease.child_id])).rows[0].value;assert.deepEqual(after,before);cases++;
 }
 console.log(JSON.stringify({ok:true,cases,platforms:Object.keys(PLATFORMS),original_claim_captures_budget_unchanged:true,source_requests:0,model_calls:0,production_writes:0}));
}finally{await db.close();fs.rmSync(folder,{recursive:true,force:true});}
