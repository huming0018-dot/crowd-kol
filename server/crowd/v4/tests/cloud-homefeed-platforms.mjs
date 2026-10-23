import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
import {randomUUID} from 'node:crypto';
import {handleMachine} from '../supabase/functions/crowd-machine/core.mjs';
import {PLATFORMS,canonical,captureHash,sha} from '../supabase/functions/crowd-machine/contract.mjs';

const {PGlite}=createRequire(import.meta.url)(path.join(process.env.CROWD_TEST_TOOLS||'/private/tmp/crowd-fix-tools','node_modules/@electric-sql/pglite'));
const directory=fs.mkdtempSync(path.join(os.tmpdir(),'crowd-homefeed-platforms-'));
const db=new PGlite(directory),ownerKey='a'.repeat(64),workerKey='b'.repeat(64),ownerHash=await sha(ownerKey);
let rpcCalls=0,cases=0;
const backend={async rpc(name,args){rpcCalls++;try{return {data:(await db.query('select public.crowd_machine_rpc($1,$2,$3,$4,$5) result',[args.p_owner_scope,args.p_actor_kind,args.p_worker_hash,args.p_action,JSON.stringify(args.p_payload)])).rows[0].result};}catch(error){return {error:{message:error.message}};}}};
async function call(action,payload={},worker=false){const response=await handleMachine(new Request('https://test.supabase.co/functions/v1/crowd-machine',{method:'POST',headers:{'Content-Type':'application/json',[worker?'X-Crowd-Worker-Key':'X-Crowd-Owner-Key']:worker?workerKey:ownerKey},body:JSON.stringify({action,payload})}),backend,ownerHash);return await response.json();}
async function good(action,payload={},worker=false){const value=await call(action,payload,worker);assert.equal(value.ok,true,JSON.stringify(value));return value.result;}
try{
  await db.exec('create role anon; create role authenticated; create role service_role bypassrls;');
  await db.exec(fs.readFileSync(new URL('../cloud_machine.sql',import.meta.url),'utf8'));
  await good('worker_pair',{worker_id:randomUUID(),worker_key:workerKey,name:'isolated',platforms:Object.keys(PLATFORMS),expires_at:new Date(Date.now()+86400000).toISOString()});
  for(const [platform,native] of Object.entries(PLATFORMS)){
    const task=(await good('task_create',{platforms:[platform],mode:'homefeed',desired_items:1,max_api_requests:12,comments:true,replies:true,media:true,purpose:'noncommercial_research',idempotency_key:'isolated-homefeed-'+platform})).task;
    const lease=(await good('claim',{claim_id:randomUUID()},true)).lease;
    assert.equal(lease.task_id,task.task_id);assert.equal(lease.platform,platform);assert.equal(lease.request.mode,'homefeed');assert.deepEqual(lease.request.targets,[]);
    const capture_ids=[];
    for(const kind of ['content','comment','media']){
      const record={kind,platform:native,content_id:'123',source_kind:'mediacrawler_api',reward_eligible:false,record_hash:'f'.repeat(64),discovery_kind:'homefeed',...(kind==='content'?{body:'isolated source fixture'}:kind==='comment'?{comment_id:'c1',text:'isolated comment fixture',parent_comment_id:null}:{sha256:'c'.repeat(64),size_bytes:100})};
      const envelope={schema:'crowd-machine-capture-v1',capture_id:randomUUID(),task_id:lease.task_id,child_id:lease.child_id,run_id:lease.run_id,lease_epoch:lease.lease_epoch,platform:native,delivery_basis:lease.delivery_basis,source_kind:'machine_api',record,adapter_version:'cloud-machine-v1',normalizer_version:'mc-normalized-v2',packaged_at:new Date().toISOString()};
      const payload={run_id:lease.run_id,lease_epoch:lease.lease_epoch,envelope,envelope_hash:await captureHash(envelope)};
      const first=await good('capture',payload,true),second=await good('capture',payload,true);
      assert.deepEqual(first.receipt,second.receipt);assert.equal(first.receipt.status,'received');capture_ids.push(envelope.capture_id);cases++;
    }
    const finish={run_id:lease.run_id,lease_epoch:lease.lease_epoch,capture_ids,outcome:'completed',api_attempts:4};
    finish.finish_hash=await sha('crowd-machine-finish-v1\n'+canonical(finish));
    await good('finish',finish,true);
    const results=await good('results',{task_id:task.task_id});assert.equal(results.items.length,3);
    assert(results.items.every(item=>item.record.discovery_kind==='homefeed'&&item.record.platform===native));cases++;
  }
  for(const platform of ['dy','wb','tieba','zhihu','ks']){
    const before=rpcCalls;
    const rejected=await call('task_preview',{platforms:[platform],mode:'trending',desired_items:1,max_api_requests:12,purpose:'noncommercial_research',idempotency_key:'isolated-denied-'+platform});
    assert.equal(rejected.error,'discovery_not_supported_for_platform');assert.equal(rpcCalls,before);cases++;
  }
  console.log(JSON.stringify({ok:true,cases,platforms:7,records:21,database:'isolated PGlite',source_requests:0,model_requests:0,production_deployed:false}));
}finally{await db.close();fs.rmSync(directory,{recursive:true,force:true});}
