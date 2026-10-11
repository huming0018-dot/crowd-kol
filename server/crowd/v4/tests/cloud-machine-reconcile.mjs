import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
import {randomUUID} from 'node:crypto';
import {handleMachine} from '../supabase/functions/crowd-machine/core.mjs';
import {canonical,captureHash,sha} from '../supabase/functions/crowd-machine/contract.mjs';

const {PGlite}=createRequire(import.meta.url)(path.join(process.env.CROWD_TEST_TOOLS||'/private/tmp/crowd-fix-tools','node_modules/@electric-sql/pglite'));
const directory=fs.mkdtempSync(path.join(os.tmpdir(),'crowd-reconcile-test-'));
const db=new PGlite(directory);let cases=0;
const ownerKey='a'.repeat(64),workerKey='b'.repeat(64),otherKey='c'.repeat(64),ownerHash=await sha(ownerKey);
const backend={async rpc(name,args){assert.equal(name,'crowd_machine_rpc');try{return {data:(await db.query('select public.crowd_machine_rpc($1,$2,$3,$4,$5) result',[args.p_owner_scope,args.p_actor_kind,args.p_worker_hash,args.p_action,JSON.stringify(args.p_payload)])).rows[0].result};}catch(error){return {error:{message:error.message}};}}};
async function call(action,payload={},key=workerKey,role='Worker'){
 const request=new Request('https://test.supabase.co/functions/v1/crowd-machine',{method:'POST',headers:{'Content-Type':'application/json',['X-Crowd-'+role+'-Key']:key},body:JSON.stringify({action,payload})});
 const response=await handleMachine(request,backend,ownerHash);return {status:response.status,...await response.json()};
}
async function good(action,payload={},key=workerKey,role='Worker'){const out=await call(action,payload,key,role);assert.equal(out.ok,true,JSON.stringify(out));return out.result;}
const owner=(action,payload={})=>good(action,payload,ownerKey,'Owner');
const task=()=>({platforms:['xhs'],mode:'detail',targets_by_platform:{xhs:['0123456789abcdef01234567']},desired_items:1,max_api_requests:5,comments:false,purpose:'noncommercial_research',idempotency_key:randomUUID()});
async function finish(lease,outcome='unknown',attempts=0){const p={run_id:lease.run_id,lease_epoch:lease.lease_epoch,capture_ids:[],outcome,api_attempts:attempts};return {...p,finish_hash:await sha('crowd-machine-finish-v1\n'+canonical(p))};}
function capture(lease){return {schema:'crowd-machine-capture-v1',capture_id:randomUUID(),task_id:lease.task_id,child_id:lease.child_id,run_id:lease.run_id,lease_epoch:lease.lease_epoch,platform:'xiaohongshu',delivery_basis:lease.delivery_basis,source_kind:'machine_api',record:{kind:'content',platform:'xiaohongshu',content_id:'0123456789abcdef01234567',body:'隔离合成样本',source_kind:'mediacrawler_api',reward_eligible:false},adapter_version:'cloud-machine-v1',normalizer_version:'mc-normalized-v2',packaged_at:new Date().toISOString()};}
try{
 await db.exec('create role anon; create role authenticated; create role service_role bypassrls;');
 await db.exec(fs.readFileSync(new URL('../cloud_machine.sql',import.meta.url),'utf8'));
 const workerId=randomUUID(),otherId=randomUUID();
 for(const [id,key]of [[workerId,workerKey],[otherId,otherKey]])await owner('worker_pair',{worker_id:id,worker_key:key,name:'isolated-reconcile',platforms:['xhs'],expires_at:new Date(Date.now()+86400000).toISOString()});
 const first=(await owner('task_create',task())).task,claimId=randomUUID(),lease=(await good('claim',{claim_id:claimId})).lease;
 const binding={run_id:lease.run_id,lease_epoch:lease.lease_epoch};
 await good('heartbeat',{...binding,sequence:1});
 const proof={phase:'authorized',local_run_id:null,sequence:1,evidence_sha256:'e'.repeat(64)};
 const payload={...binding,claim_id:claimId,proof};
 assert.equal((await call('reconcile_no_dispatch',payload,ownerKey,'Owner')).error,'principal_denied');cases++;
 assert.equal((await call('reconcile_no_dispatch',payload,otherKey)).error,'lease_binding_denied');cases++;
 assert.equal((await call('reconcile_no_dispatch',payload)).error,'no_dispatch_reconciliation_denied');cases++;
 // A restart can heartbeat sequence 2 before recording the unknown finish; the durable pre-start proof remains sequence 1.
 await good('heartbeat',{...binding,sequence:2});
 const f=await finish(lease);await good('finish',f);
 const history=(await db.query('select * from crowd_machine.claims where worker_id=$1 and claim_id=$2',[workerId,claimId])).rows[0];
 assert.equal(history.outcome,'unknown');assert.equal(history.api_attempts,0);assert.equal(history.local_run_id,null);cases++;
 for(const change of [{phase:'dispatching'},{phase:'running'},{local_run_id:randomUUID()},{sequence:0},{sequence:3},{sequence:1.1},{evidence_sha256:'bad'}]){
  assert.equal((await call('reconcile_no_dispatch',{...payload,proof:{...proof,...change}})).error,change.sequence===1.1?'integer_required':'no_dispatch_reconciliation_denied');cases++;
 }
 for(const change of [{claim_id:randomUUID()},{run_id:randomUUID()},{lease_epoch:2}]){assert.equal((await call('reconcile_no_dispatch',{...payload,...change})).error,'lease_binding_denied');cases++;}
 for(const field of ['phase','local_run_id','sequence','evidence_sha256']){
  const invalid={...proof};delete invalid[field];
  await assert.rejects(db.query('select public.crowd_machine_rpc($1,$2,$3,$4,$5)', ['crowd-owner-main','worker',await sha(workerKey),'reconcile_no_dispatch',JSON.stringify({...payload,proof:invalid})]),/no_dispatch_reconciliation_denied/);cases++;
 }
 for(const [table,field,value] of [['children','local_run_id',randomUUID()],['claims','local_run_id',randomUUID()],['claims','api_attempts',1],['claims','outcome','failed']]){
  const where=table==='children'?'child_id':'claim_id',id=table==='children'?lease.child_id:claimId;
  await db.query(`update crowd_machine.${table} set ${field}=$1 where ${where}=$2`,[value,id]);
  assert.equal((await call('reconcile_no_dispatch',payload)).error,'no_dispatch_reconciliation_denied');
  await db.query(`update crowd_machine.${table} set ${field}=$1 where ${where}=$2`,[field==='api_attempts'?0:field==='outcome'?'unknown':null,id]);cases++;
 }
 const item=capture(lease),itemPayload={...binding,envelope:item,envelope_hash:await captureHash(item)};
 await good('capture',itemPayload);
 assert.equal((await call('reconcile_no_dispatch',payload)).error,'no_dispatch_reconciliation_denied');cases++;
 await db.query('delete from crowd_machine.captures where capture_id=$1',[item.capture_id]); // Isolated fixture only: production has no delete action.
 const second=(await owner('task_create',task())).task;
 assert.equal((await good('claim',{claim_id:randomUUID()})).lease,null);cases++;
 const result=await good('reconcile_no_dispatch',payload);
 assert.equal(result.reconciled,true);assert.equal(result.replayed,false);assert.equal(result.released_requests,5);
 assert.equal(result.worker_id,workerId);assert.equal(result.claim_id,claimId);assert.equal(result.run_id,lease.run_id);assert.equal(result.lease_epoch,lease.lease_epoch);
 const child=result.task.children[0];assert.equal(child.state,'waiting');assert.equal(child.reason_code,'no_dispatch_reconciled');assert.equal(child.requests_reserved,0);assert.equal(child.requests_spent,0);
 assert.equal(child.attempts[0].outcome,'unknown');assert.equal(child.attempts[0].resolution.kind,'no_dispatch');
 assert.deepEqual((await db.query('select * from crowd_machine.claims where worker_id=$1 and claim_id=$2',[workerId,claimId])).rows[0],history);cases++;
 const replay=await good('reconcile_no_dispatch',payload);assert.equal(replay.replayed,true);assert.equal(replay.released_requests,5);
 for(const key of ['worker_id','claim_id','run_id','lease_epoch'])assert.equal(replay[key],result[key]);
 assert.equal((await db.query('select count(*)::int n from crowd_machine.resolutions')).rows[0].n,1);cases++;
 assert.equal((await call('reconcile_no_dispatch',{...payload,proof:{...proof,evidence_sha256:'f'.repeat(64)}})).error,'reconciliation_conflict');cases++;
 assert.equal((await call('finish',f)).error,'run_reconciled_no_dispatch');
 assert.equal((await call('capture',itemPayload)).error,'run_reconciled_no_dispatch');
 assert.equal((await good('heartbeat',{...binding,sequence:3})).lease.may_dispatch,false);
 assert.equal((await good('claim',{claim_id:claimId})).lease.may_dispatch,false);cases++;
 const newLease=(await good('claim',{claim_id:randomUUID()})).lease;assert.equal(newLease.task_id,second.task_id);assert.equal(newLease.requests_reserved,5);assert.notEqual(newLease.run_id,lease.run_id);cases++;
 const priv=(await db.query("select has_table_privilege('service_role','crowd_machine.resolutions','update') u,has_table_privilege('anon','crowd_machine.resolutions','select') s")).rows[0];assert.equal(priv.u,false);assert.equal(priv.s,false);cases++;
 const publicText=JSON.stringify((await owner('task_status',{task_id:first.task_id})).task);assert.equal(publicText.includes(proof.evidence_sha256),false);cases++;
 console.log(JSON.stringify({ok:true,cases,source_requests:0,model_requests:0,database:'PGlite isolated PostgreSQL',production_deployed:false}));
}finally{await db.close();fs.rmSync(directory,{recursive:true,force:true});}
