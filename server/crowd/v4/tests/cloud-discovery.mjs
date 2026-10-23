import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
import {randomUUID} from 'node:crypto';
import {handleMachine} from '../supabase/functions/crowd-machine/core.mjs';
import {canonical,captureHash,sha} from '../supabase/functions/crowd-machine/contract.mjs';

const {PGlite}=createRequire(import.meta.url)(path.join(process.env.CROWD_TEST_TOOLS||'/private/tmp/crowd-fix-tools','node_modules/@electric-sql/pglite'));
const directory=fs.mkdtempSync(path.join(os.tmpdir(),'crowd-discovery-test-'));
const db=new PGlite(directory),ownerKey='a'.repeat(64),workerKey='b'.repeat(64),ownerHash=await sha(ownerKey);
let rpcCalls=0,cases=0;
const backend={async rpc(name,args){rpcCalls++;try{return {data:(await db.query('select public.crowd_machine_rpc($1,$2,$3,$4,$5) result',[args.p_owner_scope,args.p_actor_kind,args.p_worker_hash,args.p_action,JSON.stringify(args.p_payload)])).rows[0].result};}catch(error){return {error:{message:error.message}};}}};
async function call(action,payload={},worker=false){const response=await handleMachine(new Request('https://test.supabase.co/functions/v1/crowd-machine',{method:'POST',headers:{'Content-Type':'application/json',[worker?'X-Crowd-Worker-Key':'X-Crowd-Owner-Key']:worker?workerKey:ownerKey},body:JSON.stringify({action,payload})}),backend,ownerHash);return await response.json();}
async function good(action,payload={},worker=false){const value=await call(action,payload,worker);assert.equal(value.ok,true,JSON.stringify(value));return value.result;}
try{
  await db.exec('create role anon; create role authenticated; create role service_role bypassrls;');
  await db.exec(fs.readFileSync(new URL('../cloud_machine.sql',import.meta.url),'utf8'));
  await good('worker_pair',{worker_id:randomUUID(),worker_key:workerKey,name:'isolated',platforms:['bili'],expires_at:new Date(Date.now()+86400000).toISOString()});
  const task=(await good('task_create',{platforms:['bili'],mode:'detail',targets_by_platform:{bili:['BV1234567890']},desired_items:1,max_api_requests:5,comments:false,purpose:'noncommercial_research',idempotency_key:'discovery-isolated'})).task;
  const lease=(await good('claim',{claim_id:randomUUID()},true)).lease;
  const base={schema:'crowd-machine-capture-v1',capture_id:randomUUID(),task_id:lease.task_id,child_id:lease.child_id,run_id:lease.run_id,lease_epoch:lease.lease_epoch,platform:'bilibili',delivery_basis:lease.delivery_basis,source_kind:'machine_api',record:{kind:'content',platform:'bilibili',content_id:'123',title:'隔离样本',body:'保持原正文',source_kind:'mediacrawler_api',reward_eligible:false,record_hash:'f'.repeat(64)},adapter_version:'cloud-machine-v1',normalizer_version:'mc-normalized-v2',packaged_at:new Date().toISOString()};
  const captures=[];
  for(const discovery_kind of [undefined,'search','detail','creator','homefeed','trending']){
    const envelope={...base,capture_id:randomUUID(),record:{...base.record,...(discovery_kind?{discovery_kind}:{})}};
    const payload={run_id:lease.run_id,lease_epoch:lease.lease_epoch,envelope,envelope_hash:await captureHash(envelope)};
    const first=await good('capture',payload,true),again=await good('capture',payload,true);
    assert.deepEqual(again.receipt,first.receipt);captures.push({envelope,receipt:first.receipt});cases++;
  }
  for(const kind of [null,true,'','following','hot-search','constructor',[]]){
    const envelope={...base,record:{...base.record,discovery_kind:kind}},before=rpcCalls;
    const value=await call('capture',{run_id:lease.run_id,lease_epoch:lease.lease_epoch,envelope,envelope_hash:await captureHash(envelope)},true);
    assert.equal(value.error,'invalid_capture_record');assert.equal(rpcCalls,before);cases++;
  }
  for(const [platform,kind] of [['weibo','trending'],['xiaohongshu','trending']]){
    const envelope={...base,platform,record:{...base.record,platform,discovery_kind:kind}},before=rpcCalls;
    const value=await call('capture',{run_id:lease.run_id,lease_epoch:lease.lease_epoch,envelope,envelope_hash:await captureHash(envelope)},true);
    assert.equal(value.error,'invalid_capture_record');assert.equal(rpcCalls,before);cases++;
  }
  const results=await good('results',{task_id:task.task_id});assert.equal(results.items.length,6);
  for(const {envelope,receipt} of captures){const found=results.items.find(item=>item.receipt.capture_id===envelope.capture_id);assert.equal(canonical(found.record),canonical(envelope.record));assert.equal(found.record.record_hash,base.record.record_hash);assert.deepEqual(found.receipt,receipt);}
  assert.equal(Object.hasOwn(results.items.find(item=>item.receipt.capture_id===captures[0].envelope.capture_id).record,'discovery_kind'),false);cases++;
  console.log(JSON.stringify({ok:true,cases,database:'isolated PGlite',source_requests:0,model_requests:0,production_deployed:false}));
}finally{await db.close();fs.rmSync(directory,{recursive:true,force:true});}
