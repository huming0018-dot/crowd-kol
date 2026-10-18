import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
import {randomUUID} from 'node:crypto';
import {handleMachine} from '../supabase/functions/crowd-machine/core.mjs';
import {canonical,captureHash,sha} from '../supabase/functions/crowd-machine/contract.mjs';
const {PGlite}=createRequire(import.meta.url)(path.join(process.env.CROWD_TEST_TOOLS||'/private/tmp/crowd-fix-tools','node_modules/@electric-sql/pglite'));
const directory=fs.mkdtempSync(path.join(os.tmpdir(),'crowd-supplemental-test-'));
const db=new PGlite(directory);let cases=0;
const ownerKey='a'.repeat(64),workerKey='b'.repeat(64),otherKey='c'.repeat(64),ownerHash=await sha(ownerKey);
const backend={async rpc(name,args){assert.equal(name,'crowd_machine_rpc');try{return {data:(await db.query('select public.crowd_machine_rpc($1,$2,$3,$4,$5) result',[args.p_owner_scope,args.p_actor_kind,args.p_worker_hash,args.p_action,JSON.stringify(args.p_payload)])).rows[0].result};}catch(error){return {error:{message:error.message}};}}};
async function call(action,payload={},key=ownerKey,role='Owner'){
 const request=new Request('https://test.supabase.co/functions/v1/crowd-machine',{method:'POST',headers:{'Content-Type':'application/json',['X-Crowd-'+role+'-Key']:key},body:JSON.stringify({action,payload})});
 const response=await handleMachine(request,backend,ownerHash);return {status:response.status,...await response.json()};
}
async function good(action,payload={},key=ownerKey,role='Owner'){const out=await call(action,payload,key,role);assert.equal(out.ok,true,JSON.stringify(out));return out.result;}
const worker=(a,p={})=>good(a,p,workerKey,'Worker');
function capture(lease,kind='content'){return {schema:'crowd-machine-capture-v1',capture_id:randomUUID(),task_id:lease.task_id,child_id:lease.child_id,run_id:lease.run_id,lease_epoch:lease.lease_epoch,platform:'bilibili',delivery_basis:lease.delivery_basis,source_kind:'machine_api',record:{kind,platform:'bilibili',content_id:'BV1234567890',body:'隔离合成正文',canonical_id_scheme:'bilibili.bvid.v1',origin:{run_id:lease.local_run_id,file_sha256:'e'.repeat(64),line:1},source_kind:'mediacrawler_api',reward_eligible:false,...(kind==='comment'?{comment_id:'1',text:'隔离评论'}:{})},adapter_version:'cloud-machine-v1',normalizer_version:'mc-normalized-v2',packaged_at:new Date().toISOString()};}
const cap=async envelope=>({run_id:envelope.run_id,lease_epoch:envelope.lease_epoch,envelope,envelope_hash:await captureHash(envelope)});
async function finish(lease,outcome,attempts,ids=[],context=null){const p={run_id:lease.run_id,lease_epoch:lease.lease_epoch,capture_ids:ids,outcome,api_attempts:attempts,...(context?{account_context:context}:{})};return {...p,finish_hash:await sha('crowd-machine-finish-v1\n'+canonical(p))};}
try{
 await db.exec('create role anon; create role authenticated; create role service_role bypassrls;');
 await db.exec(fs.readFileSync(new URL('../cloud_machine.sql',import.meta.url),'utf8'));
 await db.exec(fs.readFileSync(new URL('../cloud_machine.sql',import.meta.url),'utf8'));cases++;
 const workerId=randomUUID(),otherId=randomUUID(),localRun=randomUUID(),session=randomUUID();
 for(const [id,key]of [[workerId,workerKey],[otherId,otherKey]])await good('worker_pair',{worker_id:id,worker_key:key,name:'isolated-supplemental',platforms:['bili'],expires_at:new Date(Date.now()+86400000).toISOString()});
 const created=(await good('task_create',{platforms:['bili'],mode:'detail',targets_by_platform:{bili:['BV1234567890']},desired_items:1,max_api_requests:12,comments:true,replies:true,media:true,purpose:'noncommercial_research',idempotency_key:randomUUID()})).task;
 const firstClaim=randomUUID(),lease=(await worker('claim',{claim_id:firstClaim})).lease;
 await worker('heartbeat',{run_id:lease.run_id,lease_epoch:1,sequence:1,local_run_id:localRun});
 lease.local_run_id=localRun;
 const body=capture(lease),bodyPayload=await cap(body);await worker('capture',bodyPayload);
 await worker('finish',await finish(lease,'failed',5,[body.capture_id]));
 const before=(await db.query('select plan from crowd_machine.children where child_id=$1',[lease.child_id])).rows[0].plan;
 const oldClaim=(await db.query('select * from crowd_machine.claims where claim_id=$1',[firstClaim])).rows[0];
 const oldTask=(await db.query('select request_hash,proposal from crowd_machine.tasks where task_id=$1',[created.task_id])).rows[0];
 let status=(await good('task_status',{task_id:created.task_id})).task;assert.equal(status.children[0].contents,1);assert.equal(status.children[0].requests_spent,5);assert.equal(status.children[0].supplemental_available,true);cases++;
 const payload={task_id:created.task_id,child_id:lease.child_id,expected_revision:status.revision,idempotency_key:randomUUID(),dimensions:['comments','media'],long_audio:true};
 assert.equal((await call('retry_supplemental',payload,workerKey,'Worker')).error,'principal_denied');cases++;
 for(const change of [{expected_revision:2},{child_id:randomUUID()},{dimensions:[]},{dimensions:['media','media']},{dimensions:['comments'],long_audio:true},{long_audio:'true'},{targets:['BV0000000000']},{max_api_requests:12}]){
  const out=await call('retry_supplemental',{...payload,...change});assert.equal(out.ok,false);assert.equal(out.error,change.expected_revision?'revision_conflict':Object.hasOwn(change,'targets')||Object.hasOwn(change,'max_api_requests')?'invalid_request':'supplemental_retry_denied');cases++;
 }
 // Fixture mutations cover forbidden terminal/budget/source binding branches without touching a live source.
 for(const [field,value] of [['state','unknown'],['state','completed'],['requests_reserved',1],['requests_spent',12],['local_run_id',null]]){
  const original=(await db.query(`select ${field} value from crowd_machine.children where child_id=$1`,[lease.child_id])).rows[0].value;
  await db.query(`update crowd_machine.children set ${field}=$1 where child_id=$2`,[value,lease.child_id]);
  assert.equal((await call('retry_supplemental',payload)).error,'supplemental_retry_denied');
  assert.equal((await good('task_status',{task_id:created.task_id})).task.children[0].supplemental_available,false);
  await db.query(`update crowd_machine.children set ${field}=$1 where child_id=$2`,[original,lease.child_id]);cases++;
 }
 for(const [field,value]of [['mode','search'],['targets',['BV1234567890','BV0000000000']],['comments',false],['media',false]]){
  await db.query('update crowd_machine.children set plan=jsonb_set(plan,$1,$2) where child_id=$3',[['request',field],JSON.stringify(value),lease.child_id]);
  assert.equal((await call('retry_supplemental',payload)).error,'supplemental_retry_denied');
  await db.query('update crowd_machine.children set plan=$1 where child_id=$2',[JSON.stringify(before),lease.child_id]);cases++;
 }
 await db.query('update crowd_machine.workers set enabled=false where worker_id=$1',[workerId]);assert.equal((await call('retry_supplemental',payload)).error,'supplemental_retry_denied');await db.query('update crowd_machine.workers set enabled=true where worker_id=$1',[workerId]);cases++;
 await db.query("update crowd_machine.tasks set desired_state='paused' where task_id=$1",[created.task_id]);assert.equal((await call('retry_supplemental',payload)).error,'supplemental_retry_denied');await db.query("update crowd_machine.tasks set desired_state='running' where task_id=$1",[created.task_id]);cases++;
 const result=await good('retry_supplemental',payload);assert.equal(result.replayed,false);assert.equal(result.task.revision,2);assert.equal(result.task.children[0].state,'queued');assert.equal(result.task.children[0].requests_spent,5);assert.equal(result.task.children[0].supplemental_available,false);cases++;
 assert.equal((await good('retry_supplemental',{...payload,dimensions:['media','comments'],expected_revision:2})).replayed,true);assert.equal((await call('retry_supplemental',{...payload,long_audio:false})).error,'idempotency_conflict');cases++;
 assert.deepEqual((await db.query('select plan from crowd_machine.children where child_id=$1',[lease.child_id])).rows[0].plan,before);
 assert.deepEqual((await db.query('select request_hash,proposal from crowd_machine.tasks where task_id=$1',[created.task_id])).rows[0],oldTask);
 assert.deepEqual((await db.query('select * from crowd_machine.claims where claim_id=$1',[firstClaim])).rows[0],oldClaim);cases++;
 assert.equal((await good('claim',{claim_id:randomUUID()},otherKey,'Worker')).lease,null);cases++;
 const supplement=(await worker('claim',{claim_id:randomUUID()})).lease;assert.notEqual(supplement.run_id,lease.run_id);assert.equal(supplement.lease_epoch,2);assert.equal(supplement.request.max_items,1);assert.equal(supplement.request.max_api_requests,7);assert.equal(supplement.request.platform_options.long_audio,true);assert.deepEqual(supplement.request.targets,['BV1234567890']);assert.equal(supplement.supplemental_context.source_local_run_id,localRun);assert.equal(supplement.supplemental_context.authorization_local_run_id,localRun);assert.equal(supplement.supplemental_context.source_worker_id,workerId);assert.equal(supplement.supplemental_context.source_run_id,lease.run_id);assert.deepEqual(supplement.supplemental_context.account_context,{});cases++;
 // A pre-start login gate spends zero requests and never binds the old local run to the new attempt.
 const context={session_id:session,generation:1,account_ref:'d'.repeat(64)};
 await worker('finish',await finish(supplement,'login_required',0,[],context));
 const resume={run_id:supplement.run_id,lease_epoch:2,local_run_id:localRun,authorized_for_run:localRun,session_id:session,generation:1,account_ref:context.account_ref,identity_status:'authenticated_self_id',verified_at_ms:Date.now()};
 for(const change of [{local_run_id:randomUUID(),authorized_for_run:randomUUID()},{generation:2},{account_ref:'e'.repeat(64)},{verified_at_ms:Date.now()-181000}]){assert.equal((await call('resume_login',{...resume,...change},workerKey,'Worker')).error,'login_resume_denied');cases++;}
 assert.equal((await call('resume_login',resume,otherKey,'Worker')).error,'lease_binding_denied');cases++;
 assert.equal((await worker('resume_login',resume)).resumed,true);assert.equal((await worker('resume_login',resume)).replayed,true);cases++;
 const resumed=(await worker('claim',{claim_id:randomUUID()})).lease;assert.equal(resumed.lease_epoch,3);assert.equal(resumed.request.max_api_requests,7);assert.equal(resumed.request.max_items,1);assert.equal(resumed.local_run_id,null);assert.equal(resumed.supplemental_context.authorization_local_run_id,localRun);cases++;
 const newLocal=randomUUID();await worker('heartbeat',{run_id:resumed.run_id,lease_epoch:3,sequence:1,local_run_id:newLocal});
 await worker('finish',await finish(resumed,'login_required',1,[],context));
 assert.equal((await call('resume_login',{...resume,run_id:resumed.run_id,lease_epoch:3},workerKey,'Worker')).error,'login_resume_denied');cases++;
 const afterDispatchResume={...resume,run_id:resumed.run_id,lease_epoch:3,local_run_id:newLocal,authorized_for_run:newLocal,verified_at_ms:Date.now()};
 await worker('resume_login',afterDispatchResume);
 const dispatchedResume=(await worker('claim',{claim_id:randomUUID()})).lease;
 assert.equal(dispatchedResume.request.max_api_requests,6);assert.equal(dispatchedResume.lease_epoch,4);assert.equal(dispatchedResume.supplemental_context.authorization_local_run_id,newLocal);assert.equal(dispatchedResume.supplemental_context.source_local_run_id,localRun);cases++;
 await worker('finish',await finish(dispatchedResume,'login_required',0,[],context));
 const latestScopeResume={...afterDispatchResume,run_id:dispatchedResume.run_id,lease_epoch:4,verified_at_ms:Date.now()};
 assert.equal((await call('resume_login',{...latestScopeResume,local_run_id:localRun,authorized_for_run:localRun},workerKey,'Worker')).error,'login_resume_denied');cases++;
 await worker('resume_login',latestScopeResume);
 const latest=(await worker('claim',{claim_id:randomUUID()})).lease;
 assert.equal(latest.lease_epoch,5);assert.equal(latest.supplemental_context.authorization_local_run_id,newLocal);assert.equal(latest.request.max_api_requests,6);cases++;
 // Use the latest cloud binding for later captures; old authorizations and capture IDs stay historical.
 Object.assign(resumed,latest);
 const wrongTarget=capture(resumed);wrongTarget.record.content_id='BV0000000000';assert.equal((await call('capture',await cap(wrongTarget),workerKey,'Worker')).error,'invalid_capture');cases++;
 const duplicate=capture(resumed),comment=capture(resumed,'comment');await worker('capture',await cap(duplicate));await worker('capture',await cap(comment));
 assert.equal((await call('finish',await finish(resumed,'completed',4,[body.capture_id]),workerKey,'Worker')).error,'unacknowledged_capture');cases++;
 const final=await worker('finish',await finish(resumed,'completed',4,[duplicate.capture_id,comment.capture_id]));assert.equal(final.task.contents,1);assert.equal(final.task.comments,1);assert.equal(final.task.children[0].requests_spent,10);assert.equal(final.task.children[0].requests_reserved,0);assert.equal(final.task.children[0].attempts.length,5);assert.equal(final.task.reward_eligible,false);cases++;
 assert.equal((await worker('receipt',{run_id:lease.run_id,lease_epoch:1,capture_id:body.capture_id,envelope_hash:bodyPayload.envelope_hash})).receipt.capture_id,body.capture_id);
 assert.equal((await worker('capture',bodyPayload)).replayed,true);assert.equal((await worker('claim',{claim_id:firstClaim})).lease,null);cases++;
 assert.equal((await call('retry_supplemental',{...payload,idempotency_key:randomUUID(),expected_revision:2})).error,'supplemental_retry_denied');cases++;
 // Production identity shape: native MC reports AID while the original immutable locator remains BV.
 const aidTask=(await good('task_create',{platforms:['bili'],mode:'detail',targets_by_platform:{bili:['BV1popx6zEe1']},desired_items:1,max_api_requests:12,comments:true,media:true,purpose:'noncommercial_research',idempotency_key:randomUUID()})).task;
 const aidLocal=randomUUID(),aidLease=(await worker('claim',{claim_id:randomUUID()})).lease;
 await worker('heartbeat',{run_id:aidLease.run_id,lease_epoch:1,sequence:1,local_run_id:aidLocal});
 const aidBody=capture(aidLease);aidBody.record.content_id='117410296235621';aidBody.record.canonical_id_scheme='bilibili.aid.v1';aidBody.record.origin={run_id:aidLocal,file_sha256:'af28ad1d882f045b9e2fb3d32c14b7ed12cfe764a33a2c60adf5020d40c1edd6',line:1};
 await worker('capture',await cap(aidBody));await worker('finish',await finish(aidLease,'failed',5,[aidBody.capture_id]));
 const aidPayload={task_id:aidTask.task_id,child_id:aidLease.child_id,expected_revision:1,idempotency_key:randomUUID(),dimensions:['comments','media'],long_audio:true};
 assert.equal((await good('task_status',{task_id:aidTask.task_id})).task.children[0].supplemental_available,true);cases++;
 for(const change of [{origin:null},{origin:{...aidBody.record.origin,run_id:randomUUID()}},{origin:{run_id:aidLocal}},{canonical_id_scheme:null},{canonical_id_scheme:'bilibili.bvid.v1'},{kind:'comment'}]){
  const modified={...aidBody,record:{...aidBody.record,...change}};
  await db.query('update crowd_machine.captures set envelope=$1 where capture_id=$2',[JSON.stringify(modified),aidBody.capture_id]);
  assert.equal((await call('retry_supplemental',aidPayload)).error,'supplemental_retry_denied');
  await db.query('update crowd_machine.captures set envelope=$1 where capture_id=$2',[JSON.stringify(aidBody),aidBody.capture_id]);cases++;
 }
 for(const change of [{content_id:'117410296235622'},{origin:null}]){
  const ambiguous={...aidBody,capture_id:randomUUID(),record:{...aidBody.record,...change}};
  await worker('capture',await cap(ambiguous));
  assert.equal((await call('retry_supplemental',aidPayload)).error,'supplemental_retry_denied');
  await db.query('delete from crowd_machine.captures where capture_id=$1',[ambiguous.capture_id]);cases++;
 }
 for(const [field,value]of [['run_id',randomUUID()],['worker_id',otherId],['lease_epoch',99]]){
  const original=(await db.query(`select ${field} value from crowd_machine.captures where capture_id=$1`,[aidBody.capture_id])).rows[0].value;
  await db.query(`update crowd_machine.captures set ${field}=$1 where capture_id=$2`,[value,aidBody.capture_id]);
  assert.equal((await call('retry_supplemental',aidPayload)).error,'supplemental_retry_denied');
  await db.query(`update crowd_machine.captures set ${field}=$1 where capture_id=$2`,[original,aidBody.capture_id]);cases++;
 }
 await good('retry_supplemental',aidPayload);const aidSupplement=(await worker('claim',{claim_id:randomUUID()})).lease;
 assert.equal(aidSupplement.supplemental_context.source_content_id,'117410296235621');assert.deepEqual(aidSupplement.request.targets,['BV1popx6zEe1']);assert.equal(aidSupplement.request.max_api_requests,7);cases++;
 for(const id of ['BV1popx6zEe1','117410296235622']){const wrong=capture(aidSupplement);wrong.record.content_id=id;assert.equal((await call('capture',await cap(wrong),workerKey,'Worker')).error,'invalid_capture');cases++;}
 const goodAid=capture(aidSupplement);goodAid.record.content_id='117410296235621';goodAid.record.canonical_id_scheme='bilibili.aid.v1';await worker('capture',await cap(goodAid));const aidFinal=await worker('finish',await finish(aidSupplement,'completed',4,[goodAid.capture_id]));assert.equal(aidFinal.task.contents,1);assert.equal(aidFinal.task.children[0].requests_spent,9);cases++;
 const priv=(await db.query("select has_table_privilege('service_role','crowd_machine.recoveries','update') u,has_table_privilege('service_role','crowd_machine.recoveries','delete') d,has_table_privilege('anon','crowd_machine.recoveries','select') s")).rows[0];assert.equal(priv.u,false);assert.equal(priv.d,false);assert.equal(priv.s,false);cases++;
 const text=JSON.stringify(final.task);assert.equal(text.includes(context.account_ref),false);assert.equal(text.includes('source_finish_hash'),false);assert.equal((await db.query('select count(*)::int n from crowd_machine.recoveries')).rows[0].n,2);cases++;
 console.log(JSON.stringify({ok:true,cases,source_requests:0,model_requests:0,database:'PGlite isolated PostgreSQL',production_deployed:false}));
}finally{await db.close();fs.rmSync(directory,{recursive:true,force:true});}
