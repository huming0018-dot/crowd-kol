import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
globalThis.crypto??=webcrypto;
import {cpSync,mkdtempSync,copyFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
const formal=fileURLToPath(new URL('../supabase/functions/crowd-machine/',import.meta.url));
const scratch=mkdtempSync(join(tmpdir(),'participant-owner-feed-'));
cpSync(formal,scratch,{recursive:true});

const {handleMachine}=await import(pathToFileURL(join(scratch,'core.mjs')));
const {sha}=await import(pathToFileURL(join(scratch,'contract.mjs')));
const key='a'.repeat(64),hash=await sha(key);let calls=[];
const empty={schema:'crowd-participant-pro-receipt-feed-v1',groups:[],next_cursor:null,has_more:false};
let response={data:empty,error:null};
const backend={rpc:async(...args)=>{calls.push(args);return response;}};
async function req(headers={},payload={},action='participant_pro_receipts'){const r=await handleMachine(new Request('https://local.invalid',{method:'POST',headers:{'Content-Type':'application/json',...headers},body:JSON.stringify({action,payload})}),backend,hash);return {status:r.status,...await r.json()};}
let cases=0;const test=async(fn)=>{calls=[];response={data:empty,error:null};await fn();cases++;};
await test(async()=>{assert.equal((await req({'X-Crowd-Owner-Key':key})).ok,true);assert.deepEqual(JSON.parse(JSON.stringify(calls)),[['crowd_participant_pro_receipts_rpc',{p_owner_scope:'crowd-owner-main',p_actor_kind:'owner',p_payload:{}}]]);});
for(const h of [{},{'X-Crowd-Worker-Key':key},{'X-Crowd-Owner-Key':'b'.repeat(64)},{'X-Crowd-Owner-Key':key,Origin:'https://evil.invalid'},{'X-Crowd-Owner-Key':key,'X-Crowd-Worker-Key':key}])await test(async()=>{assert.equal((await req(h)).error,'principal_denied');assert.equal(calls.length,0);});
for(const p of [{limit:0},{limit:9},{limit:1.5},{foreign:1},{after:{}},{after:{created_at:'bad',request:key,task_id:29,subject:key,installation_id:key,dispatch_id:key}}])await test(async()=>{assert.equal((await req({'X-Crowd-Owner-Key':key},p)).error,p.limit===1.5?'integer_required':'invalid_request');assert.equal(calls.length,0);});
await test(async()=>{response={error:{message:'private SQL credential text'}};assert.equal((await req({'X-Crowd-Owner-Key':key})).error,'backend_unavailable');});
for(const error of ['participant_receipt_feed_limit','participant_receipt_feed_invalid'])await test(async()=>{response={error:{message:error}};assert.equal((await req({'X-Crowd-Owner-Key':key})).error,error);});
await test(async()=>{response={data:{...empty,groups:Array(9).fill({})}};assert.equal((await req({'X-Crowd-Owner-Key':key})).error,'participant_receipt_feed_invalid');});
await test(async()=>{response={data:{...empty,groups:[{payload:'x'.repeat(8*1024*1024)}]}};assert.equal((await req({'X-Crowd-Owner-Key':key})).error,'participant_receipt_feed_limit');});
console.log(JSON.stringify({status:'PASS',cases,real_core:true,network_calls:0}));

rmSync(scratch,{recursive:true});
