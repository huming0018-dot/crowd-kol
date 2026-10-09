import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { randomUUID } from 'node:crypto';
import { fork } from 'node:child_process';
import { DatabaseSync } from 'node:sqlite';
import { openCaptureOutbox } from '../capture-outbox.mjs';
import { normalizeCapture } from '../capture-contract.mjs';
import { receiveCapture } from '../capture-receiver.mjs';

const scopeKeys = ['owner_scope','actor_ref','session_ref','task_ref','run_id','lease_epoch','credential_epoch','platform','source_kind','adapter_version'];
const bindingKeys = ['owner_scope','actor_ref','session_ref','task_ref','run_id','lease_epoch','credential_epoch','admission_id','target_ref','source_kind'];
function newScope() {
  return { owner_scope:'owner-1', actor_ref:'actor-1', session_ref:'session-1', task_ref:{namespace:'legacy_v4',legacy_task_id:'9007199254740993'},
    run_id:randomUUID(),lease_epoch:1,credential_epoch:1,platform:'xiaohongshu',source_kind:'platform_api',adapter_version:'self-parser-1' };
}
const contextFor = scope => ({ owner_scope:scope.owner_scope,actor_ref:scope.actor_ref,session_ref:scope.session_ref,authenticated:true,auth_epoch:1,collection_allowed:true,delivery_allowed:true });
function fixture(scope) {
  const capture = Object.fromEntries(bindingKeys.filter(key => Object.hasOwn(scope,key)).map(key => [key,structuredClone(scope[key])]));
  return {...capture,contract_version:1,capture_id:randomUUID(),admission_id:randomUUID(),
    target_ref:{platform:'xiaohongshu',kind:'content',id:'opaque-content-1'},captured_at:new Date().toISOString(),payload_schema:'content.v1',
    payload:{platform:'xiaohongshu',content_id:'opaque-content-1',creator_id:'author-1',canonical_url:'https://www.xiaohongshu.com/explore/opaque-content-1',content_type:'note',
      title:{value:'隔离测试',status:'observed'},title_origin:'original',body:{value:'SQLite 耐久交付测试。',status:'observed'},published_at:{value:null,status:'not_requested'},
      metrics:Object.fromEntries(['likes','collects','comments','shares','views'].map(key=>[key,{value:null,status:'not_requested',precision:null,raw_display:null}]))},
    completeness:{status:'complete',scope:'single_content',reason:null}};
}
const page = (sequence,captures,extra={}) => ({sequence,cursor_ref:'cursor:'+randomUUID(),coverage:'complete',stop_reason:null,
  items:captures.map(capture=>({kind:'capture',capture})),...extra});

// Isolated fixture changes only the waiting boundary, never attempts or envelopes.
function endFixtureWait(filename,scope){const fixtureDb=new DatabaseSync(filename);fixtureDb.prepare('update outbox_items set next_allowed_at=0 where owner_scope=? and run_id=?').run(scope.owner_scope,scope.run_id);fixtureDb.close();}

if (process.argv[2] === '--crash-child') {
  const config = JSON.parse(fs.readFileSync(process.argv[3],'utf8'));
  if (config.mode === 'dispatch') {
    const outbox=openCaptureOutbox(config.filename,config.scope);
    outbox.deliverOne(contextFor(config.scope),async()=>{process.send({ready:true});await new Promise(()=>{});});
  } else if (config.mode === 'committed') {
    const outbox = openCaptureOutbox(config.filename,config.scope);
    await outbox.stagePage(contextFor(config.scope),config.page);
    process.send({ready:true}); // Parent SIGKILLs before close(), simulating process loss.
  } else {
    const db = new DatabaseSync(config.filename);
    db.exec('BEGIN IMMEDIATE');
    db.prepare('update outbox_runs set captured_sequence=99 where owner_scope=? and run_id=?').run(config.scope.owner_scope,config.scope.run_id);
    process.send({ready:true}); // No COMMIT; restart must roll back this transaction.
  }
  setInterval(()=>{},60000);
} else {
  const {PGlite}=createRequire(import.meta.url)(path.join(process.env.CROWD_TEST_TOOLS,'node_modules/@electric-sql/pglite'));
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'crowd-outbox-')),filename=path.join(dir,'outbox.sqlite');
  const db=new PGlite(),scope=newScope(),context=contextFor(scope),principal={owner_scope:scope.owner_scope,actor_ref:scope.actor_ref};
  let queue=openCaptureOutbox(filename,scope),cases=0;
  const admit=async(capture,revoked=false)=>db.query(`insert into capture_receiver.admissions
    (owner_scope,admission_id,actor_ref,binding,parser_version,normalization_version,requested_fields,issued_at,accept_until,revoked)
    values($1,$2,$3,$4,'self-parser-1','capture-v1',array['title','body'],clock_timestamp()-interval '1 minute',clock_timestamp()+interval '1 hour',$5)`,
    [capture.owner_scope,capture.admission_id,capture.actor_ref,Object.fromEntries(bindingKeys.map(key=>[key,capture[key]])),revoked]);
  const ack=async capture=>{const result=await receiveCapture(db,principal,capture);assert.equal(result.error,null,JSON.stringify(result));return result;};
  async function killChild(config,onReady=null) {
    const configPath=path.join(dir,'child-'+randomUUID()+'.json');fs.writeFileSync(configPath,JSON.stringify(config),{mode:0o600});
    const child=fork(fileURLToPath(import.meta.url),['--crash-child',configPath],{stdio:['ignore','ignore','inherit','ipc']});
    await new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>{child.kill('SIGKILL');reject(new Error('child_timeout'));},10000);
      child.once('error',failure=>{clearTimeout(timer);reject(failure);});
      child.once('exit',(code,signal)=>{clearTimeout(timer);signal==='SIGKILL'?resolve():reject(new Error('unexpected_child_exit'));});
      child.once('message',async message=>{if(message.ready){try{if(onReady)await onReady();}catch(failure){reject(failure);}finally{child.kill('SIGKILL');}}});
    });
  }
  try {
    await db.exec('create role anon;create role authenticated;');
    await db.exec(fs.readFileSync(new URL('./fixtures/capture-receiver.sql',import.meta.url),'utf8'));
    await db.query('insert into capture_receiver.actors values($1,$2,true)',[scope.owner_scope,scope.actor_ref]);
    const a=fixture(scope),b=fixture(scope),c=fixture(scope),p1=page(1,[a,b]),p2=page(2,[c]);
    for(const capture of [a,b,c])await admit(capture);
    await queue.stagePage(context,p1);await queue.stagePage(context,p2);
    assert.equal(queue.status(context).captured_sequence,2);assert.equal(queue.status(context).delivered_sequence,0);
    const beforeReplay=queue.status(context);assert.deepEqual(await queue.stagePage(context,p1),beforeReplay);cases++;
    const changedPage=structuredClone(p1);changedPage.items[0].capture.payload.body.value='不同正文';
    await assert.rejects(queue.stagePage(context,changedPage),/page_reused/);cases++;
    await assert.rejects(queue.stagePage(context,page(4,[])),/page_sequence_gap/);cases++;
    const wrongCursor=page(3,[]);wrongCursor.cursor_ref='https://example.com/?token=secret';
    await assert.rejects(queue.stagePage(context,wrongCursor),/invalid_cursor_ref/);cases++;
    const wrongBinding=fixture(scope);wrongBinding.credential_epoch=2;
    await assert.rejects(queue.stagePage(context,page(3,[wrongBinding])),/outbox_capture_binding_mismatch/);cases++;
    const rowBefore=queue.status(context);const mutatedId=structuredClone(a);mutatedId.payload.body.value='同 ID 另载荷';
    await assert.rejects(queue.stagePage(context,page(3,[fixture(scope),mutatedId])),/request_reused/);
    assert.deepEqual(queue.status(context),rowBefore,'earlier item and page insert roll back with conflict');cases++;

    const ackA=await ack(a),ackB=await ack(b),ackC=await ack(c);
    queue.applyResult(context,c.capture_id,ackC);assert.equal(queue.status(context).delivered_sequence,0);
    queue.applyResult(context,a.capture_id,ackA);assert.equal(queue.status(context).delivered_sequence,0);
    assert.equal(queue.pending(context).length,1);cases++;
    for(const [key,value]of[['capture_id',randomUUID()],['envelope_hash','a'.repeat(64)],['run_id',randomUUID()],['lease_epoch',2],['credential_epoch',2],['admission_id',randomUUID()],['status','accepted'],['verdict','approved'],['received_at','2026-02-30T00:00:00.000Z']]){
      const bad=structuredClone(ackB);bad.receipt[key]=value;assert.throws(()=>queue.applyResult(context,b.capture_id,bad),/capture_ack_mismatch|invalid_capture_ack/);cases++;
    }
    assert.throws(()=>queue.applyResult(context,b.capture_id,{receipt:'success',error:null}),/invalid_capture_ack/);cases++;
    assert.equal(queue.status(context).delivered_sequence,0);queue.applyResult(context,b.capture_id,ackB);
    assert.equal(queue.status(context).delivered_sequence,2);assert.equal(queue.status(context).delivered_cursor,p2.cursor_ref);cases++;
    assert.deepEqual(queue.applyResult(context,a.capture_id,ackA),queue.status(context));
    assert.throws(()=>queue.applyResult(context,a.capture_id,null),/receipt_conflict/);cases++;

    // Source callback is called once. Unknown ACK retry only invokes the receiver.
    let sourceReads=0,receiverCalls=0,originalAck;
    const syntheticSource=()=>{sourceReads++;return fixture(scope);};
    const d=syntheticSource();await admit(d);await queue.stagePage(context,page(3,[d]));
    const lost=await queue.deliverOne(context,async capture=>{receiverCalls++;originalAck=await ack(capture);throw new Error('synthetic_lost_ack');});
    assert.equal(lost.kind,'unknown');assert.equal(queue.status(context).counts.unknown,1);
    const originalEnvelope=queue.pending(context)[0];queue.close();queue=openCaptureOutbox(filename,scope);
    assert.deepEqual(queue.pending(context)[0],originalEnvelope);
    assert.equal((await queue.deliverOne(context,()=>{throw new Error('must_wait');})).kind,'deferred');
    endFixtureWait(filename,scope);
    const replayed=await queue.deliverOne(context,async capture=>{receiverCalls++;const result=await ack(capture);assert.deepEqual(result,originalAck);return result;});
    assert.equal(replayed.kind,'received');assert.equal(sourceReads,1);assert.equal(receiverCalls,2);
    assert.equal(queue.status(context).delivered_sequence,3);
    assert.equal((await db.query('select count(*)::int n from capture_receiver.captures where capture_id=$1',[d.capture_id])).rows[0].n,1);cases++;

    const e=fixture(scope);await admit(e);const p4=page(4,[e]);await queue.stagePage(context,p4);
    const paused={...context,collection_allowed:false};
    await assert.rejects(queue.stagePage(paused,page(5,[])),/collection_paused/);
    assert.equal((await queue.deliverOne(paused,ack)).kind,'received');cases++;
    const f=fixture(scope);await admit(f);await queue.stagePage(context,page(5,[f]));
    let calls=0;const stopped={...context,authenticated:false};
    await assert.rejects(queue.deliverOne(stopped,async()=>{calls++;}),/outbox_not_authorized/);assert.equal(calls,0);cases++;
    assert.throws(()=>queue.pending({...context,owner_scope:'another-owner'}),/outbox_not_authorized/);cases++;
    assert.throws(()=>queue.pending({...context,session_ref:'another-session'}),/outbox_not_authorized/);cases++;
    await assert.rejects(queue.deliverOne({...context,delivery_allowed:false},ack),/delivery_stopped/);cases++;
    const midflight={...context};
    await assert.rejects(queue.deliverOne(midflight,async capture=>{const result=await ack(capture);midflight.authenticated=false;return result;}),/outbox_not_authorized/);
    assert.equal(queue.status(context).counts.unknown,1);assert.equal(queue.status(context).delivered_sequence,4);
    endFixtureWait(filename,scope);assert.equal((await queue.deliverOne(context,ack)).kind,'received');cases++;

    const rejected=fixture(scope);await admit(rejected,true);await queue.stagePage(context,page(6,[rejected]));
    assert.equal((await queue.deliverOne(context,capture=>receiveCapture(db,principal,capture))).kind,'rejected');
    assert.equal(queue.status(context).captured_coverage,'partial');assert.equal(queue.status(context).delivered_sequence,5);
    assert.throws(()=>queue.applyResult(context,rejected.capture_id,null),/rejection_conflict/);cases++;
    const later=fixture(scope);await admit(later);await queue.stagePage(context,page(7,[later]));await queue.deliverOne(context,ack);
    assert.equal(queue.status(context).delivered_sequence,5);assert.equal(queue.status(context).captured_coverage,'partial');cases++;
    const g=fixture(scope);await admit(g);const failure={kind:'failure',item_ref:'item:'+randomUUID(),error_code:'parse_failed'};
    const badPage=page(8,[g],{coverage:'partial',stop_reason:'partial_failure'});badPage.items.push(failure);
    await queue.stagePage(context,badPage);await queue.deliverOne(context,ack);
    const state=queue.status(context);assert.equal(state.counts.failed,1);assert.equal(state.counts.rejected,1);assert.equal(state.delivered_sequence,5);
    assert.equal(queue.itemStates(context).find(item=>item.item_ref===failure.item_ref).state,'failed');cases++;
    await assert.rejects(queue.stagePage(context,{...page(9,[]),items:[failure]}),/invalid_outbox_coverage/);cases++;
    const partial=fixture(scope);partial.payload.body={value:null,status:'not_visible'};partial.completeness={status:'partial',scope:'single_content',reason:'field_unavailable'};
    await assert.rejects(queue.stagePage(context,page(9,[partial])),/invalid_outbox_coverage/);cases++;

    // Partial capture may be fully ACKed, but subsequent complete pages cannot erase coverage gaps.
    const partialScope={...scope,run_id:randomUUID(),lease_epoch:2};const partialContext=contextFor(partialScope);
    const partialQueue=openCaptureOutbox(filename,partialScope);
    const part=fixture(partialScope);part.completeness={status:'partial',scope:'single_content',reason:'content_truncated'};
    await admit(part);await partialQueue.stagePage(partialContext,page(1,[part],{coverage:'partial',stop_reason:'partial_capture'}));
    await partialQueue.deliverOne(partialContext,ack);await partialQueue.stagePage(partialContext,page(2,[]));
    assert.equal(partialQueue.status(partialContext).delivered_sequence,2);assert.equal(partialQueue.status(partialContext).delivered_coverage,'partial');
    assert.deepEqual(queue.status(context),state);partialQueue.close();cases++;
    assert.throws(()=>openCaptureOutbox(filename,{...scope,adapter_version:'changed'}),/outbox_scope_conflict/);cases++;

    // Lost ACK followed by expired system authorization is recoverable without new capture.
    const authScope={...scope,run_id:randomUUID()},authContext=contextFor(authScope),authCapture=fixture(authScope);
    let authQueue=openCaptureOutbox(filename,authScope),authSourceReads=1,authCalls=0,authAck;
    await admit(authCapture);await authQueue.stagePage(authContext,page(1,[authCapture]));
    await authQueue.deliverOne(authContext,async capture=>{authCalls++;authAck=await ack(capture);throw new Error('lost_ack');});
    await db.query('update capture_receiver.actors set enabled=false where owner_scope=$1 and actor_ref=$2',[scope.owner_scope,scope.actor_ref]);
    endFixtureWait(filename,authScope);assert.equal((await authQueue.deliverOne(authContext,async capture=>{authCalls++;return receiveCapture(db,principal,capture);})).kind,'blocked');
    assert.equal(authQueue.status(authContext).counts.blocked,1);
    assert.equal((await authQueue.deliverOne(authContext,()=>{throw new Error('must_not_retry_blocked');})).kind,'idle');
    assert.throws(()=>authQueue.applyResult(authContext,authCapture.capture_id,null),/auth_resume_required/);
    authQueue.close();authQueue=openCaptureOutbox(filename,authScope);
    assert.equal(authQueue.status(authContext).counts.blocked,1);
    assert.throws(()=>authQueue.resumeDelivery({...authContext,authenticated:false},authCapture.capture_id),/outbox_not_authorized/);
    assert.throws(()=>authQueue.resumeDelivery(authContext,authCapture.capture_id),/reauthentication_required/);
    await db.query('update capture_receiver.actors set enabled=true where owner_scope=$1 and actor_ref=$2',[scope.owner_scope,scope.actor_ref]);
    const reauthenticated={...authContext,auth_epoch:2};authQueue.resumeDelivery(reauthenticated,authCapture.capture_id);
    assert.deepEqual(authQueue.pending(reauthenticated)[0],await normalizeCapture(authCapture));
    endFixtureWait(filename,authScope);const afterAuth=await authQueue.deliverOne(reauthenticated,async capture=>{authCalls++;const result=await ack(capture);assert.deepEqual(result,authAck);return result;});
    assert.equal(afterAuth.kind,'received');assert.equal(authCalls,3);assert.equal(authSourceReads,1);
    assert.equal(authQueue.status(reauthenticated).delivered_sequence,1);authQueue.close();cases++;

    // A response to auth epoch 1 cannot block a login already refreshed to epoch 2.
    const flightScope={...scope,run_id:randomUUID()},flightContext=contextFor(flightScope),flightCapture=fixture(flightScope);
    const flightQueue=openCaptureOutbox(filename,flightScope);await admit(flightCapture);
    await flightQueue.stagePage(flightContext,page(1,[flightCapture]));
    const beforeFlight=flightQueue.pending(flightContext)[0];
    await db.query('update capture_receiver.actors set enabled=false where owner_scope=$1 and actor_ref=$2',[scope.owner_scope,scope.actor_ref]);
    const stale=await flightQueue.deliverOne(flightContext,async capture=>{
      const oldResponse=await receiveCapture(db,principal,capture);assert.equal(oldResponse.error.code,'actor_not_authorized');
      await db.query('update capture_receiver.actors set enabled=true where owner_scope=$1 and actor_ref=$2',[scope.owner_scope,scope.actor_ref]);
      flightContext.auth_epoch=2;return oldResponse;
    });
    assert.equal(stale.kind,'unknown');assert.equal(stale.reason,'stale_auth_response');
    assert.equal(flightQueue.status(flightContext).counts.blocked,0);
    assert.deepEqual(flightQueue.pending(flightContext)[0],beforeFlight);
    endFixtureWait(filename,flightScope);assert.equal((await flightQueue.deliverOne(flightContext,ack)).kind,'received');cases++;
    for(const [key,value,expected]of[['authenticated',false,/outbox_not_authorized/],['owner_scope','another-owner',/outbox_not_authorized/],
      ['actor_ref','another-actor',/outbox_not_authorized/],['session_ref','another-session',/outbox_not_authorized/],['delivery_allowed',false,/delivery_stopped/]]){
      const guardedScope={...scope,run_id:randomUUID()},guardedContext=contextFor(guardedScope),guarded=fixture(guardedScope);await admit(guarded);
      const guardedQueue=openCaptureOutbox(filename,guardedScope);await guardedQueue.stagePage(guardedContext,page(1,[guarded]));
      const changedContext={...guardedContext};
      await assert.rejects(guardedQueue.deliverOne(changedContext,async()=>{
        changedContext.auth_epoch=3;changedContext[key]=value;return {receipt:null,error:{code:'actor_not_authorized'}};
      }),expected);
      assert.equal(guardedQueue.status(guardedContext).counts.unknown,1);
      assert.equal(guardedQueue.status(guardedContext).counts.blocked,0);
      endFixtureWait(filename,guardedScope);assert.equal((await guardedQueue.deliverOne(guardedContext,ack)).kind,'received');guardedQueue.close();cases++;
    }
    flightQueue.close();

    // Three attempts, persistent waits, preserved evidence and strict ACK after exhaustion.
    const retryScope=newScope(),retryContext=contextFor(retryScope),retryCapture=fixture(retryScope),retryFile=path.join(dir,'retry.sqlite');
    let retryQueue=openCaptureOutbox(retryFile,retryScope),retryCalls=0,retryAck;
    await admit(retryCapture);await retryQueue.stagePage(retryContext,page(1,[retryCapture]));
    for(let attempt=1;attempt<=3;attempt++){
      const result=await retryQueue.deliverOne(retryContext,async envelope=>{
        retryCalls++;retryAck=await ack(envelope);
        // Simulate pre-dispatch deadline already elapsed during a slow callback.
        endFixtureWait(retryFile,retryScope);return {receipt:null,error:{code:'receiver_unavailable'}};
      });
      assert.equal(result.kind,attempt===3?'exhausted':'unknown');
      const item=retryQueue.itemStates(retryContext)[0];assert.equal(item.attempt_count,attempt);
      assert.ok(item.next_allowed_at>=Date.now()+(attempt===1?4500:19500));
      assert.equal(retryQueue.status(retryContext).delivery.in_flight,false);
      retryQueue.close();retryQueue=openCaptureOutbox(retryFile,retryScope);
      assert.equal((await retryQueue.deliverOne(retryContext,()=>{throw new Error('must_not_send');})).kind,attempt===3?'idle':'deferred');
      endFixtureWait(retryFile,retryScope);cases++;
    }
    assert.equal(retryCalls,3);assert.equal(retryQueue.status(retryContext).counts.exhausted,1);assert.equal(retryQueue.status(retryContext).delivered_sequence,0);
    retryQueue.applyResult(retryContext,retryCapture.capture_id,null);assert.equal(retryQueue.itemStates(retryContext)[0].attempt_count,3);
    assert.equal((await retryQueue.deliverOne(retryContext,()=>{throw new Error('cap_bypass');})).kind,'idle');
    retryQueue.applyResult(retryContext,retryCapture.capture_id,retryAck);assert.equal(retryQueue.status(retryContext).delivered_sequence,1);retryQueue.close();cases++;

    // Same run and separate connections cannot dispatch while the live callback is held.
    const mutexScope=newScope(),mutexContext=contextFor(mutexScope),mutexCapture=fixture(mutexScope),mutexFile=path.join(dir,'mutex.sqlite');
    const mutexQueue=openCaptureOutbox(mutexFile,mutexScope),otherQueue=openCaptureOutbox(mutexFile,mutexScope);
    await admit(mutexCapture);await mutexQueue.stagePage(mutexContext,page(1,[mutexCapture]));let release,callsInFlight=0;
    const held=mutexQueue.deliverOne(mutexContext,async capture=>{callsInFlight++;return await new Promise(resolve=>{release=resolve;});});
    assert.equal(otherQueue.status(mutexContext).delivery.in_flight,true);
    assert.throws(()=>mutexQueue.close(),/delivery_in_flight/);
    assert.equal((await mutexQueue.deliverOne(mutexContext,ack)).kind,'busy');assert.equal((await otherQueue.deliverOne(mutexContext,ack)).kind,'busy');
    assert.throws(()=>otherQueue.applyResult(mutexContext,mutexCapture.capture_id,null),/delivery_in_flight/);
    otherQueue.close();const reopened=openCaptureOutbox(mutexFile,mutexScope);assert.equal((await reopened.deliverOne(mutexContext,ack)).kind,'busy');
    const liveAck=await ack(mutexCapture);reopened.applyResult(mutexContext,mutexCapture.capture_id,liveAck);
    release({receipt:null,error:{code:'actor_not_authorized'}});const staleResult=await held;
    assert.equal(staleResult.kind,'received');assert.equal(staleResult.reason,'stale_delivery_response');assert.equal(staleResult.progress.delivery.in_flight,false);
    assert.equal(callsInFlight,1);assert.equal(reopened.itemStates(mutexContext)[0].attempt_count,1);mutexQueue.close();reopened.close();cases++;

    // A killed process leaves the attempt consumed. Only confirmed dead PID unlocks it.
    const dispatchScope=newScope(),dispatchContext=contextFor(dispatchScope),dispatchCapture=fixture(dispatchScope),dispatchFile=path.join(dir,'dispatch.sqlite');
    let dispatchQueue=openCaptureOutbox(dispatchFile,dispatchScope);await admit(dispatchCapture);await dispatchQueue.stagePage(dispatchContext,page(1,[dispatchCapture]));dispatchQueue.close();
    await killChild({mode:'dispatch',filename:dispatchFile,scope:dispatchScope},async()=>{
      const observer=openCaptureOutbox(dispatchFile,dispatchScope);
      assert.equal((await observer.deliverOne(dispatchContext,()=>{throw new Error('cross_process_double_send');})).kind,'busy');observer.close();
    });
    dispatchQueue=openCaptureOutbox(dispatchFile,dispatchScope);assert.equal(dispatchQueue.status(dispatchContext).delivery.in_flight,true);
    assert.equal(dispatchQueue.itemStates(dispatchContext)[0].attempt_count,1);
    assert.equal((await dispatchQueue.deliverOne(dispatchContext,()=>{throw new Error('must_wait_after_crash');})).kind,'deferred');
    assert.equal(dispatchQueue.status(dispatchContext).delivery.in_flight,false);endFixtureWait(dispatchFile,dispatchScope);
    assert.equal((await dispatchQueue.deliverOne(dispatchContext,ack)).kind,'received');assert.equal(dispatchQueue.itemStates(dispatchContext)[0].attempt_count,2);dispatchQueue.close();cases++;

    // Claim storage failure must happen before any external call and roll back the attempt.
    const atomicScope=newScope(),atomicContext=contextFor(atomicScope),atomicCapture=fixture(atomicScope),atomicFile=path.join(dir,'atomic.sqlite');
    const atomicQueue=openCaptureOutbox(atomicFile,atomicScope);await admit(atomicCapture);await atomicQueue.stagePage(atomicContext,page(1,[atomicCapture]));
    const inject=new DatabaseSync(atomicFile);inject.exec("create trigger reject_attempt before update of attempt_count on outbox_items begin select raise(abort,'synthetic_failure');end");
    let atomicCalls=0;await assert.rejects(atomicQueue.deliverOne(atomicContext,()=>{atomicCalls++;}),/outbox_storage_failure/);
    assert.equal(atomicCalls,0);assert.equal(atomicQueue.itemStates(atomicContext)[0].attempt_count,0);assert.equal(atomicQueue.status(atomicContext).delivery.in_flight,false);
    inject.exec('drop trigger reject_attempt');inject.close();assert.equal((await atomicQueue.deliverOne(atomicContext,ack)).kind,'received');atomicQueue.close();cases++;

    // Legacy schema migration: pending is provably unsent; unknown history cannot be reset.
    const legacyScope=newScope(),legacyContext=contextFor(legacyScope),legacyFile=path.join(dir,'legacy.sqlite');
    let legacyQueue=openCaptureOutbox(legacyFile,legacyScope);const oldCaptures=Array.from({length:5},()=>fixture(legacyScope));
    for(const capture of oldCaptures)await admit(capture);
    const oldPage=page(1,oldCaptures,{coverage:'partial',stop_reason:'partial_failure'});oldPage.items.push({kind:'failure',item_ref:'item:'+randomUUID(),error_code:'parse_failed'});
    await legacyQueue.stagePage(legacyContext,oldPage);
    legacyQueue.applyResult(legacyContext,oldCaptures[1].capture_id,null);
    legacyQueue.applyResult(legacyContext,oldCaptures[2].capture_id,{receipt:null,error:{code:'actor_not_authorized'}});
    legacyQueue.applyResult(legacyContext,oldCaptures[3].capture_id,{receipt:null,error:{code:'admission_revoked'}});
    const oldReceived=await ack(oldCaptures[4]);legacyQueue.applyResult(legacyContext,oldCaptures[4].capture_id,oldReceived);legacyQueue.close();
    const oldDb=new DatabaseSync(legacyFile);
    oldDb.exec('alter table outbox_items drop column attempt_count;alter table outbox_items drop column next_allowed_at;alter table outbox_items drop column legacy_attempts_unknown;alter table outbox_runs drop column flight_token;alter table outbox_runs drop column flight_capture_id;alter table outbox_runs drop column flight_pid;');oldDb.close();
    legacyQueue=openCaptureOutbox(legacyFile,legacyScope);const migrated=legacyQueue.itemStates(legacyContext);
    assert.deepEqual(migrated.map(row=>row.state),['pending','legacy_unknown','blocked','rejected','received','failed']);assert.equal(migrated[0].attempt_count,0);assert.equal(migrated[1].attempt_count,3);
    const legacyAuth={...legacyContext,auth_epoch:2};legacyQueue.resumeDelivery(legacyAuth,oldCaptures[2].capture_id);
    assert.equal(legacyQueue.itemStates(legacyAuth)[2].state,'legacy_unknown');
    assert.equal((await legacyQueue.deliverOne(legacyAuth,ack)).kind,'received');assert.equal((await legacyQueue.deliverOne(legacyAuth,()=>{throw new Error('legacy_bypass');})).kind,'idle');
    legacyQueue.applyResult(legacyAuth,oldCaptures[1].capture_id,await ack(oldCaptures[1]));assert.equal(legacyQueue.itemStates(legacyAuth)[1].state,'received');
    const fresh=fixture(legacyScope);await admit(fresh);await legacyQueue.stagePage(legacyAuth,page(2,[fresh]));assert.equal((await legacyQueue.deliverOne(legacyAuth,ack)).kind,'received');
    assert.equal(legacyQueue.status(legacyAuth).delivered_sequence,0);legacyQueue.close();cases++;

    const crashScope=newScope(),crashFile=path.join(dir,'crash.sqlite'),crashCapture=fixture(crashScope),crashPage=page(1,[crashCapture]);
    await killChild({mode:'committed',filename:crashFile,scope:crashScope,page:crashPage});
    let afterCrash=openCaptureOutbox(crashFile,crashScope);assert.equal(afterCrash.status(contextFor(crashScope)).captured_sequence,1);
    assert.deepEqual(afterCrash.pending(contextFor(crashScope))[0],await normalizeCapture(crashCapture));afterCrash.close();cases++;
    await killChild({mode:'uncommitted',filename:crashFile,scope:crashScope});
    afterCrash=openCaptureOutbox(crashFile,crashScope);assert.equal(afterCrash.status(contextFor(crashScope)).captured_sequence,1);afterCrash.close();cases++;
    assert.equal(fs.statSync(filename).mode & 0o077,0);cases++;
    queue.close();queue=openCaptureOutbox(filename,scope);assert.deepEqual(queue.status(context),state);cases++;
    console.log(`PASS capture outbox: ${cases} scenario groups; SQLite transactions, stable envelopes, ACK order, receiver lost-ACK replay, SIGKILL restart`);
    console.log('BOUNDARY: local ACK watermark only; no server page checkpoint, cross-device recovery, production auth, source collection or power-loss proof');
  } finally {queue.close();await db.close();fs.rmSync(dir,{recursive:true,force:true});}
}
