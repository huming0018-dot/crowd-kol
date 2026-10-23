import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {webcrypto} from 'node:crypto';
import {taskPlan} from '../supabase/functions/crowd-machine/contract.mjs';
if(!globalThis.crypto)Object.defineProperty(globalThis,"crypto",{value:webcrypto});
const source=fs.readFileSync(new URL('../multiplatform/owner-ui.js',import.meta.url),'utf8');
const fields=Object.fromEntries(['owner_long_audio','owner_transcript_only','owner_media','owner_comments','owner_replies','owner_mode','owner_targets','owner_total','owner_requests','owner_comment_limit','purpose','authorization_ref','owner_continuous'].map(id=>[id,{checked:false,value:''}]));
const inputs=[{value:'xhs',checked:true},{value:'bili',checked:false},{value:'ks',checked:false}];let invalidations=0;
fields.owner_platforms={querySelectorAll:selector=>selector==='input'?inputs:inputs.filter(item=>item.checked)};
Object.assign(fields.owner_mode,{value:'detail'});fields.owner_targets.value='bili,BV1234567890';fields.owner_total.value='1';fields.owner_requests.value='8';fields.owner_comment_limit.value='3';fields.purpose.value='noncommercial_research';
const context=vm.createContext({$:id=>fields[id],crypto:webcrypto,invalidate:()=>invalidations++,call:async(action,p)=>{assert.equal(action,'parse_batch');return {targets_by_platform:{bili:['BV1234567890']},errors:[]};}});
const start=source.indexOf('  async function payload()');const end=source.indexOf("  $('owner_preview_button')",start);
vm.runInContext(source.slice(start,end),context);
vm.runInContext(source.slice(source.indexOf("  $('owner_long_audio').onchange"),source.indexOf("  $('owner_mode').onchange")),context);
let payload=await vm.runInContext('payload()',context);assert.equal(payload.platform_options_by_platform,undefined);
fields.owner_transcript_only.checked=true;fields.owner_transcript_only.onchange();assert.deepEqual(inputs.filter(item=>item.checked).map(item=>item.value),['xhs']);assert.equal(fields.owner_media.checked,true);assert.equal(fields.owner_long_audio.checked,false);assert.equal((await vm.runInContext('payload()',context)).platform_options_by_platform.xhs.transcript_only,true);inputs[0].checked=false;inputs[1].checked=true;
payload=await vm.runInContext('payload()',context);assert.deepEqual(JSON.parse(JSON.stringify(payload.platform_options_by_platform)),{bili:{long_audio:true,transcript_only:true}});
const planned=await taskPlan(JSON.parse(JSON.stringify(payload)));assert.equal(planned.children[0].request.platform_options.transcript_only,true);assert.equal(planned.max_api_requests,8);
inputs.find(item=>item.value==='ks').checked=true;assert.equal((await vm.runInContext('payload()',context)).platform_options_by_platform.ks.transcript_only,true);
for(const bad of [{transcript_only:1,long_audio:true},{transcript_only:true,long_audio:false},{transcript_only:true}])await assert.rejects(()=>taskPlan({...JSON.parse(JSON.stringify(payload)),platform_options_by_platform:{bili:bad}}));
await assert.rejects(()=>taskPlan({...JSON.parse(JSON.stringify(payload)),platforms:['ks'],targets_by_platform:{ks:['synthetic']},platform_options_by_platform:{ks:{transcript_only:true,long_audio:true}}}));
fields.owner_media.checked=false;fields.owner_media.onchange();assert.equal(fields.owner_transcript_only.checked,false);assert.equal(fields.owner_long_audio.checked,false);
assert.match(source,/先取平台字幕/);assert.ok(invalidations>=2);
console.log(JSON.stringify({ok:true,cases:8,actual_owner_payload:true,actual_cloud_plan:true,source_requests:0,model_calls:0}));
// The real Edge/RPC stores and dispatches the same option without widening source quota.
const {createRequire}=await import('node:module'),path=(await import('node:path')).default,os=(await import('node:os')).default;
const {PGlite}=createRequire(import.meta.url)(path.join(process.env.CROWD_TEST_TOOLS,'node_modules/@electric-sql/pglite'));
const {handleMachine}=await import('../supabase/functions/crowd-machine/core.mjs');
const {sha}=await import('../supabase/functions/crowd-machine/contract.mjs');
const directory=fs.mkdtempSync(path.join(os.tmpdir(),'crowd-transcript-light-'));
const db=new PGlite(directory),ownerKey='a'.repeat(64),workerKey='b'.repeat(64),ownerHash=await sha(ownerKey);
const backend={async rpc(name,args){try{return {data:(await db.query('select public.crowd_machine_rpc($1,$2,$3,$4,$5) result',[args.p_owner_scope,args.p_actor_kind,args.p_worker_hash,args.p_action,JSON.stringify(args.p_payload)])).rows[0].result};}catch(error){return {error:{message:error.message}};}}};
async function edge(action,payload,worker=false){const response=await handleMachine(new Request('https://test.supabase.co/functions/v1/crowd-machine',{method:'POST',headers:{'Content-Type':'application/json',[worker?'X-Crowd-Worker-Key':'X-Crowd-Owner-Key']:worker?workerKey:ownerKey},body:JSON.stringify({action,payload})}),backend,ownerHash);return response.json();}
try{
 await db.exec('create role anon; create role authenticated; create role service_role bypassrls;');await db.exec(fs.readFileSync(new URL('../cloud_machine.sql',import.meta.url),'utf8'));
 assert.equal((await edge('worker_pair',{worker_id:webcrypto.randomUUID(),worker_key:workerKey,name:'isolated',platforms:['bili'],expires_at:new Date(Date.now()+86400000).toISOString()})).ok,true);
 const created=await edge('task_create',{...JSON.parse(JSON.stringify(payload)),idempotency_key:'isolated-light-transcript'});assert.equal(created.ok,true);
 const claimed=await edge('claim',{claim_id:webcrypto.randomUUID()},true);assert.equal(claimed.ok,true);assert.equal(claimed.result.lease.request.platform_options.transcript_only,true);assert.equal(claimed.result.lease.request.max_api_requests,8);
 const repeated=await edge('task_create',{...JSON.parse(JSON.stringify(payload)),idempotency_key:'isolated-light-transcript'});assert.equal(repeated.result.task.task_id,created.result.task.task_id);
 for(const bad of [{transcript_only:true},{transcript_only:1,long_audio:true}])assert.equal((await edge('task_create',{...JSON.parse(JSON.stringify(payload)),idempotency_key:webcrypto.randomUUID(),platform_options_by_platform:{bili:bad}})).ok,false);
 console.log(JSON.stringify({ok:true,edge_rpc_cases:6,source_requests:0,model_calls:0,production_writes:0}));
}finally{await db.close();fs.rmSync(directory,{recursive:true,force:true});}
