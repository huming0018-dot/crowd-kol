import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
import {randomUUID} from 'node:crypto';
import {handleMachine} from '../supabase/functions/crowd-machine/core.mjs';
import {canonical,sha} from '../supabase/functions/crowd-machine/contract.mjs';
const {PGlite}=createRequire(import.meta.url)(path.join(process.env.CROWD_TEST_TOOLS||'/private/tmp/crowd-fix-tools','node_modules/@electric-sql/pglite'));
const directory=fs.mkdtempSync(path.join(os.tmpdir(),'crowd-platform-isolation-'));const db=new PGlite(directory);let cases=0;
const ownerKey='a'.repeat(64),workerKey='b'.repeat(64),otherKey='c'.repeat(64),ownerHash=await sha(ownerKey),workerId=randomUUID(),otherId=randomUUID();
const backend={async rpc(name,args){assert.equal(name,'crowd_machine_rpc');try{return{data:(await db.query('select public.crowd_machine_rpc($1,$2,$3,$4,$5) result',[args.p_owner_scope,args.p_actor_kind,args.p_worker_hash,args.p_action,JSON.stringify(args.p_payload)])).rows[0].result};}catch(e){return{error:{message:e.message}};}}};
async function good(action,payload={},key=workerKey,role='Worker'){const response=await handleMachine(new Request('https://isolated.supabase.co/functions/v1/crowd-machine',{method:'POST',headers:{'Content-Type':'application/json',['X-Crowd-'+role+'-Key']:key},body:JSON.stringify({action,payload})}),backend,ownerHash);const value=await response.json();assert.equal(value.ok,true,JSON.stringify(value));return value.result;}
const owner=(action,payload)=>good(action,payload,ownerKey,'Owner');
const targets={zhihu:'https://zhuanlan.zhihu.com/p/2010393405658793620',ks:'https://www.kuaishou.com/short-video/3xvzf4jsvsv46ty',wb:'Abc'};
async function create(platform){return(await owner('task_create',{platforms:[platform],mode:'detail',targets_by_platform:{[platform]:[targets[platform]]},desired_items:1,max_api_requests:12,comments:true,purpose:'noncommercial_research',idempotency_key:randomUUID()})).task;}
const claim=(key=workerKey,p={})=>good('claim',{claim_id:randomUUID(),...p},key);
async function unknown(lease,id){await good('heartbeat',{run_id:lease.run_id,lease_epoch:lease.lease_epoch,sequence:1,local_run_id:randomUUID()});const p={run_id:lease.run_id,lease_epoch:lease.lease_epoch,capture_ids:[],outcome:'unknown',api_attempts:0};await good('finish',{...p,finish_hash:await sha('crowd-machine-finish-v1\n'+canonical(p))});return(await db.query('select * from crowd_machine.claims where claim_id=$1',[id])).rows[0];}
try{
 await db.exec('create role anon;create role authenticated;create role service_role bypassrls;');
 const source=fs.readFileSync(new URL('../cloud_machine.sql',import.meta.url),'utf8');
 const migrationDir=new URL('../supabase/migrations/',import.meta.url),names=fs.readdirSync(migrationDir).filter(x=>x.endsWith('_crowd_machine_unknown_platform_isolation.sql'));assert.equal(names.length,1);
 const migration=fs.readFileSync(new URL(names[0],migrationDir),'utf8');
 const rpc=source.slice(source.indexOf('create or replace function public.crowd_machine_rpc('),source.indexOf('revoke all on all functions in schema crowd_machine'));
 assert.ok(migration.includes(rpc));assert.doesNotMatch(migration,/alter table|truncate|drop table/i);
 await db.exec(fs.readFileSync(new URL('../supabase/migrations/20261011053338_crowd_machine_original_content_binding.sql',import.meta.url),'utf8'));
 await db.exec(migration);await db.exec(migration);cases++;
 for(const[id,key]of[[workerId,workerKey],[otherId,otherKey]])await owner('worker_pair',{worker_id:id,worker_key:key,name:'isolated-platform-worker',platforms:['zhihu','ks','wb'],expires_at:new Date(Date.now()+86400000).toISOString()});
 const first=await create('zhihu'),claimId=randomUUID(),zh=(await claim(workerKey,{claim_id:claimId})).lease;assert.equal(zh.task_id,first.task_id);
 const oldClaim=await unknown(zh,claimId);assert.equal(oldClaim.outcome,'unknown');cases++;
 const oldChild=(await db.query('select * from crowd_machine.children where child_id=$1',[zh.child_id])).rows[0];
 const same=await create('zhihu');assert.equal((await claim()).lease,null);cases++;
 const ks=await create('ks');await db.query('update crowd_machine.children set requests_spent=1,worker_id=$1 where task_id=$2',[workerId,ks.task_id]);
 assert.equal((await claim(workerKey,{unavailable_platforms:['ks']})).lease,null);cases++;
 // Concurrent RPC submissions are queued by PGlite; the actual function still locks the worker row.
 const contenders=await Promise.all(Array.from({length:6},()=>claim()));const leases=contenders.map(x=>x.lease).filter(Boolean);assert.equal(leases.length,1);const resumed=leases[0];assert.equal(resumed.task_id,ks.task_id);assert.equal(resumed.request.max_api_requests,11);assert.equal(resumed.requests_reserved,11);cases++;
 assert.equal((await db.query("select count(*)::int n from crowd_machine.children where worker_id=$1 and state='running'",[workerId])).rows[0].n,1);cases++;
 const wb=await create('wb');assert.equal((await claim()).lease,null);cases++;
 assert.deepEqual((await db.query('select * from crowd_machine.children where child_id=$1',[zh.child_id])).rows[0],oldChild);assert.deepEqual((await db.query('select * from crowd_machine.claims where claim_id=$1',[claimId])).rows[0],oldClaim);cases++;
 const replay=(await claim(workerKey,{claim_id:claimId}));assert.equal(replay.replayed,true);assert.equal(replay.lease.state,'unknown');assert.equal(replay.lease.may_dispatch,false);cases++;
 assert.equal((await db.query('select count(*)::int n from crowd_machine.resolutions')).rows[0].n,0);cases++;
 // Different workers can use their own platforms, but cannot take an already worker-bound queued child.
 await db.query('update crowd_machine.children set worker_id=$1 where task_id=$2',[workerId,same.task_id]);
 const other=(await claim(otherKey)).lease;assert.equal(other.task_id,wb.task_id);assert.equal(other.worker_id,otherId);assert.notEqual(other.child_id,same.children[0].child_id);cases++;
 const free=await create('zhihu');const done={run_id:other.run_id,lease_epoch:other.lease_epoch,capture_ids:[],outcome:'failed',api_attempts:0};await good('finish',{...done,finish_hash:await sha('crowd-machine-finish-v1\n'+canonical(done))},otherKey);
 const otherZh=(await claim(otherKey)).lease;assert.equal(otherZh.task_id,free.task_id);assert.equal(otherZh.worker_id,otherId);assert.notEqual(otherZh.run_id,zh.run_id);cases++;
 // Expiration is recorded unknown first; it does not release the old reservation or allow same-platform work.
 await db.query("update crowd_machine.children set lease_until=clock_timestamp()-interval '1 second' where child_id=$1",[resumed.child_id]);
 const ksBefore=(await db.query('select * from crowd_machine.claims where run_id=$1',[resumed.run_id])).rows[0];const ks2=await create('ks'),wb2=await create('wb');
 const afterExpire=(await claim()).lease;assert.equal(afterExpire.task_id,wb2.task_id);cases++;
 const expired=(await db.query('select * from crowd_machine.children where child_id=$1',[resumed.child_id])).rows[0];assert.equal(expired.state,'unknown');assert.equal(expired.reason_code,'lease_expired_source_outcome_unknown');assert.equal(expired.requests_reserved,11);assert.equal(expired.requests_spent,1);assert.equal(expired.run_id,resumed.run_id);assert.deepEqual((await db.query('select * from crowd_machine.claims where run_id=$1',[resumed.run_id])).rows[0],ksBefore);cases++;
 assert.equal((await owner('task_status',{task_id:ks2.task_id})).task.children[0].state,'queued');assert.equal((await owner('task_status',{task_id:same.task_id})).task.children[0].state,'queued');cases++;
 const currentZh=(await db.query('select * from crowd_machine.children where child_id=$1',[zh.child_id])).rows[0];assert.deepEqual(currentZh,oldChild);assert.equal((await db.query('select count(*)::int n from crowd_machine.captures')).rows[0].n,0);cases++;
 console.log(JSON.stringify({ok:true,cases,database:'isolated PGlite actual Edge/RPC',concurrency:'six concurrent RPC submissions; PGlite serializes SQL, PostgreSQL worker row lock retained',source_requests:0,model_requests:0,production_deployed:false}));
}finally{await db.close();fs.rmSync(directory,{recursive:true,force:true});}
