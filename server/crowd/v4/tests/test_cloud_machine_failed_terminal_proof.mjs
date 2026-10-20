import assert from 'node:assert/strict';
import {handleMachine} from '../supabase/functions/crowd-machine/core.mjs';
import {canonical,sha} from '../supabase/functions/crowd-machine/contract.mjs';
const owner='a'.repeat(64),hash=await sha(owner),id='11111111-1111-4111-8111-111111111111';
const base={task_id:id,child_id:id,worker_id:id,claim_id:id,run_id:id,local_run_id:id,lease_epoch:1,expected_revision:2,idempotency_key:'terminal-import:'+id,expected_finish_hash:null,mode:'terminal_unknown',capture_count:0,capture_digest:await sha('crowd-machine-capture-audit-v1\n'),proof:{executor_inactive:true,local_state:'failed',exit_code:1,api_attempts:null,status_sha256:'b'.repeat(64),manifest_sha256:'c'.repeat(64)}};
let calls=0,cases=0,last;
const backend={async rpc(name,args){calls++;last=args;assert.equal(name,'crowd_machine_rpc');assert.equal(args.p_actor_kind,'owner');assert.equal(args.p_action,'task_reconcile');return {data:{reconciled:true}}}};
async function call(payload,worker=false){const response=await handleMachine(new Request('https://offline.invalid',{method:'POST',headers:{'Content-Type':'application/json',[worker?'X-Crowd-Worker-Key':'X-Crowd-Owner-Key']:owner},body:JSON.stringify({action:'task_reconcile',payload})}),backend,hash);return {status:response.status,...await response.json()}}
for(const proof of [base.proof,{...base.proof,exit_code:-9},{...base.proof,local_state:'interrupted_unknown',exit_code:null}]){
 const input={...base,proof},before=calls,result=await call(input);assert.equal(result.ok,true);assert.equal(calls,before+1);assert.equal(Object.getPrototypeOf(last.p_payload.proof),null);assert.deepEqual({...last.p_payload.proof},proof);const semantic={...input};delete semantic.expected_revision;const text=canonical(semantic);assert.equal(last.p_payload.canonical_audit,text);assert.equal(last.p_payload.audit_hash,await sha('crowd-machine-terminal-audit-v1\n'+text));cases++;
}
for(const change of [{exit_code:true},{exit_code:'1'},{exit_code:1.5},{exit_code:0},{exit_code:256},{exit_code:-129},{exit_code:null},{local_state:null},{local_state:'running'},{api_attempts:0},{executor_inactive:false}]){
 const before=calls,result=await call({...base,proof:{...base.proof,...change}});assert.equal(result.ok,false);assert.equal(result.error,change.exit_code===1.5?'integer_required':'terminal_reconciliation_denied');assert.equal(calls,before);cases++;
}
for(const key of ['exit_code','local_state']){const input=structuredClone(base);delete input.proof[key];const before=calls,result=await call(input);assert.equal(result.ok,false);assert.equal(calls,before);cases++}
{const before=calls,result=await call(base,true);assert.equal(result.status,403);assert.equal(calls,before);cases++}
console.log(JSON.stringify({status:'PASS_FAILED_TERMINAL_PROOF_SHAPE',cases,real_handler:true,RPC_mock_only:true,cloud_or_source:false}));
