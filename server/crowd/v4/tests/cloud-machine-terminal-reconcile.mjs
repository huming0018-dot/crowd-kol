import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
import {randomUUID} from 'node:crypto';
import {handleMachine} from '../supabase/functions/crowd-machine/core.mjs';
import {canonical,captureHash,sha} from '../supabase/functions/crowd-machine/contract.mjs';
const {PGlite}=createRequire(import.meta.url)(path.join(process.env.CROWD_TEST_TOOLS||'/private/tmp/crowd-fix-tools','node_modules/@electric-sql/pglite'));
const directory=fs.mkdtempSync(path.join(os.tmpdir(),'crowd-terminal-audit-')),db=new PGlite(directory);
const ownerKey='a'.repeat(64),workerKey='b'.repeat(64),ownerHash=await sha(ownerKey),workerId=randomUUID();let cases=0;
const backend={async rpc(name,args){try{return{data:(await db.query('select public.crowd_machine_rpc($1,$2,$3,$4,$5) result',[args.p_owner_scope,args.p_actor_kind,args.p_worker_hash,args.p_action,JSON.stringify(args.p_payload)])).rows[0].result};}catch(error){return{error:{message:error.message}};}}};
async function call(action,payload={},worker=false){const response=await handleMachine(new Request('https://offline.invalid/functions/v1/crowd-machine',{method:'POST',headers:{'Content-Type':'application/json',[worker?'X-Crowd-Worker-Key':'X-Crowd-Owner-Key']:worker?workerKey:ownerKey},body:JSON.stringify({action,payload})}),backend,ownerHash);return{status:response.status,...await response.json()};}
async function good(action,payload={},worker=false){const result=await call(action,payload,worker);assert.equal(result.ok,true,JSON.stringify(result));return result.result;}
async function capture(lease,kind='content',body=''){
 const envelope={schema:'crowd-machine-capture-v1',capture_id:randomUUID(),task_id:lease.task_id,child_id:lease.child_id,run_id:lease.run_id,lease_epoch:lease.lease_epoch,platform:lease.platform==='tieba'?'tieba':'zhihu',delivery_basis:'live_capture',source_kind:'machine_api',record:{kind,platform:lease.platform==='tieba'?'tieba':'zhihu',content_id:'123',title:kind==='content'?'标题可见':'',body,source_kind:'mediacrawler_api',reward_eligible:false,...(kind==='comment'?{comment_id:'c1',text:'公开评论'}:{})},adapter_version:'cloud-machine-v1',normalizer_version:'mc-normalized-v2',packaged_at:new Date().toISOString()};
 const envelope_hash=await captureHash(envelope),request={run_id:lease.run_id,lease_epoch:lease.lease_epoch,envelope,envelope_hash};
 const ack=await good('capture',request,true);return{request,ack,envelope};
}
async function fixture(platform='tieba',outcome='completed',attempts=3){
 const payload={platforms:[platform],mode:'detail',targets_by_platform:{[platform]:[platform==='tieba'?'123':'https://www.zhihu.com/question/1/answer/1']},desired_items:1,max_api_requests:12,purpose:'noncommercial_research',idempotency_key:randomUUID()};
 const task=(await good('task_create',payload)).task,claim_id=randomUUID(),lease=(await good('claim',{claim_id},true)).lease,local=randomUUID();assert.equal(lease.task_id,task.task_id);
 await good('heartbeat',{run_id:lease.run_id,lease_epoch:1,sequence:1,local_run_id:local},true);
 let captures=[];if(outcome==='completed')captures=[await capture(lease),await capture(lease,'comment')];
 await db.query("update crowd_machine.children set lease_until=clock_timestamp()-interval '1 second' where child_id=$1",[lease.child_id]);
 await good('heartbeat',{run_id:lease.run_id,lease_epoch:1,sequence:2},true);
 const finish={run_id:lease.run_id,lease_epoch:1,capture_ids:captures.map(x=>x.envelope.capture_id),outcome,api_attempts:attempts};finish.finish_hash=await sha('crowd-machine-finish-v1\n'+canonical(finish));await good('finish',finish,true);
 const capture_digest=await sha('crowd-machine-capture-audit-v1\n'+captures.map(x=>x.envelope.capture_id+':'+x.request.envelope_hash).sort().join('\n'));
 const audit={task_id:task.task_id,child_id:lease.child_id,worker_id:workerId,claim_id,run_id:lease.run_id,lease_epoch:1,local_run_id:local,expected_revision:task.revision,idempotency_key:randomUUID(),expected_finish_hash:finish.finish_hash,mode:outcome==='completed'?'completed_receipts':'terminal_unknown',capture_count:captures.length,capture_digest,proof:{executor_inactive:true,local_state:outcome==='completed'?'completed':'interrupted_unknown',exit_code:outcome==='completed'?0:null,api_attempts:outcome==='completed'?attempts:null,status_sha256:'d'.repeat(64),manifest_sha256:'e'.repeat(64)}};
 return{task,claim_id,lease,local,captures,finish,audit};
}
async function snapshot(f){return(await db.query('select jsonb_build_object(\'claims\',(select jsonb_agg(to_jsonb(h)) from crowd_machine.claims h where h.child_id=$1),\'captures\',(select jsonb_agg(to_jsonb(z) order by z.capture_id) from crowd_machine.captures z where z.child_id=$1),\'plan\',(select plan from crowd_machine.children where child_id=$1),\'account_context\',(select account_context from crowd_machine.children where child_id=$1),\'finish_hash\',(select finish_hash from crowd_machine.children where child_id=$1)) saved',[f.lease.child_id])).rows[0].saved;}
async function reject(payload,expected='terminal_reconciliation_denied'){const value=await call('task_reconcile',payload);assert.equal(value.error,expected,JSON.stringify(value));cases++;}
try{
 await db.exec('create role anon;create role authenticated;create role service_role bypassrls;');
 // Existing schema to additive migration, applied twice: no fixture production rows changed.
 const baseline=new URL('../../../../../outputs/unified-live-completion-2026-10-11/unknown-terminal-reconciliation/baseline/cloud_machine.sql',import.meta.url);
 await db.exec(fs.readFileSync(baseline,'utf8'));
 const migration=fs.readFileSync(new URL('../supabase/migrations/20261011144325_crowd_machine_terminal_reconciliation.sql',import.meta.url),'utf8');
 await db.exec(migration);await db.exec(migration);cases++;
 await good('worker_pair',{worker_id:workerId,worker_key:workerKey,name:'isolated-audit',platforms:['tieba','zhihu'],expires_at:new Date(Date.now()+86400000).toISOString()});
 const f=await fixture(),original=await snapshot(f);
 assert.equal((await call('task_reconcile',f.audit,true)).status,403);cases++;
 for(const change of [{child_id:randomUUID()},{worker_id:randomUUID()},{run_id:randomUUID()},{claim_id:randomUUID()},{lease_epoch:2},{local_run_id:randomUUID()},{expected_finish_hash:'0'.repeat(64)},{expected_revision:2}])await reject({...f.audit,...change},change.expected_revision?'revision_conflict':undefined);
 await reject({...f.audit,capture_count:1},'terminal_receipts_mismatch');await reject({...f.audit,capture_digest:'0'.repeat(64)},'terminal_receipts_mismatch');
 for(const change of [{executor_inactive:false},{api_attempts:4},{exit_code:1},{local_state:'running'},{status_sha256:'secret'}])await reject({...f.audit,proof:{...f.audit.proof,...change}});
 await reject({...f.audit,proof:{...f.audit.proof,cookie:'secret'}});
 for(const change of [{capture_count:true},{lease_epoch:true},{expected_revision:true},{mode:null}])await reject({...f.audit,...change});
 const captureId=f.captures[0].envelope.capture_id;
 for(const change of [{capture_id:randomUUID()},{run_id:randomUUID()},{lease_epoch:true},{reward_eligible:true},{source_kind:'participant_dom'}]){
   await db.query('update crowd_machine.captures set receipt=$2 where capture_id=$1',[captureId,JSON.stringify({...f.captures[0].ack.receipt,...change})]);
   await reject(f.audit,'terminal_receipts_mismatch');
 }
 await db.query('update crowd_machine.captures set receipt=$2 where capture_id=$1',[captureId,JSON.stringify(f.captures[0].ack.receipt)]);
 const drift=structuredClone(f.captures[0].envelope);drift.record.body='a body that was never received';
 await db.query('update crowd_machine.captures set envelope=$2 where capture_id=$1',[captureId,JSON.stringify(drift)]);
 await reject(f.audit,'terminal_receipts_mismatch');
 await db.query('update crowd_machine.captures set envelope=$2 where capture_id=$1',[captureId,JSON.stringify(f.captures[0].envelope)]);
 const complete=await good('task_reconcile',f.audit),child=complete.task.children[0];assert.equal(child.state,'completed');assert.equal(child.requests_spent,3);assert.equal(child.requests_reserved,0);assert.equal(child.terminal_audit.released_requests,9);assert.equal(child.terminal_audit.body_coverage.nonempty_body_contents,0);assert.equal(child.terminal_audit.body_coverage.title_only_contents,1);assert.deepEqual(await snapshot(f),original);cases++;
 const replay=await good('task_reconcile',{...f.audit,expected_revision:2});assert.equal(replay.replayed,true);assert.equal(replay.audit_hash,complete.audit_hash);assert.equal(replay.audit_id,complete.audit_id);assert.equal(replay.run_id,f.lease.run_id);cases++;
 await reject({...f.audit,proof:{...f.audit.proof,status_sha256:'f'.repeat(64)}},'reconciliation_conflict');
 const received=await good('capture',f.captures[0].request,true);assert.deepEqual(received.receipt,f.captures[0].ack.receipt);cases++;
 const different=structuredClone(f.captures[0].request);different.envelope.capture_id=randomUUID();different.envelope_hash=await captureHash(different.envelope);assert.equal((await call('capture',different,true)).error,'run_terminally_reconciled');cases++;
 assert.equal((await call('finish',f.finish,true)).error,'run_terminally_reconciled');cases++;
 const unknown=await fixture('zhihu','unknown',0),old=await snapshot(unknown);
 const closed=await good('task_reconcile',unknown.audit),u=closed.task.children[0];assert.equal(u.state,'failed');assert.equal(u.reason_code,'audited_terminal_unknown');assert.equal(u.terminal_audit.outcome,'unknown');assert.equal(u.requests_spent,12);assert.equal(u.requests_reserved,0);assert.equal(u.terminal_audit.charged_requests,12);assert.equal(u.terminal_audit.released_requests,0);assert.deepEqual(await snapshot(unknown),old);cases++;
 await good('task_control',{task_id:unknown.task.task_id,desired_state:'running',expected_revision:closed.task.revision});assert.equal((await good('claim',{claim_id:randomUUID()},true)).lease,null);cases++;
 const next=await fixture('zhihu','unknown',3);const counted=await good('task_reconcile',next.audit);assert.equal(counted.task.children[0].requests_spent,12);assert.equal(counted.task.children[0].terminal_audit.charged_requests,9);cases++;
 const unreserved=await fixture('zhihu','unknown',0);await db.query('update crowd_machine.children set requests_reserved=0 where child_id=$1',[unreserved.lease.child_id]);const conservative=await good('task_reconcile',unreserved.audit);assert.equal(conservative.task.children[0].requests_spent,12);assert.equal(conservative.task.children[0].terminal_audit.released_requests,0);cases++;
 const privilege=(await db.query("select has_function_privilege('anon','public.crowd_machine_rpc(text,text,text,text,jsonb)','execute') rpc,has_table_privilege('anon','crowd_machine.terminal_audits','select') reads,has_table_privilege('service_role','crowd_machine.terminal_audits','update') updates")).rows[0];assert.deepEqual(privilege,{rpc:false,reads:false,updates:false});cases++;
 assert.equal(complete.task.children[0].attempts[0].claim_id,f.claim_id);assert.equal(complete.task.children[0].finish_hash,f.finish.finish_hash);cases++;
 console.log(JSON.stringify({ok:true,cases,database:'isolated PGlite actual Edge/RPC',source_requests:0,model_calls:0,production_writes:0,old_claim_capture_identity_unchanged:true}));
}finally{await db.close();fs.rmSync(directory,{recursive:true,force:true});}
