import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { DatabaseSync } from 'node:sqlite';
import { randomUUID } from 'node:crypto';
import { submitCheckpointPage,readCheckpoint,readRecoveryAdvice,checkpointHash } from '../capture-checkpoint.mjs';
import { normalizeCapture } from '../capture-contract.mjs';
import { receiveCapture } from '../capture-receiver.mjs';
import { openCaptureOutbox } from '../capture-outbox.mjs';
const {PGlite}=createRequire(import.meta.url)(path.join(process.env.CROWD_TEST_TOOLS,'node_modules/@electric-sql/pglite'));
const dir=fs.mkdtempSync(path.join(os.tmpdir(),'crowd-checkpoint-'));
let db=new PGlite(path.join(dir,'pg')),cases=0;
const p={owner_scope:'owner-1',actor_ref:'actor-1'};
const target={platform:'xiaohongshu',kind:'content',id:'opaque-note-1'};
async function setup() {
  await db.exec('drop schema if exists capture_checkpoint cascade;drop schema if exists capture_budget cascade;drop schema if exists capture_receiver cascade;');
  await db.exec(fs.readFileSync(new URL('./fixtures/capture-receiver.sql',import.meta.url),'utf8'));
  await db.exec(fs.readFileSync(new URL('./fixtures/capture-budget.sql',import.meta.url),'utf8'));
  await db.exec(fs.readFileSync(new URL('./fixtures/capture-checkpoint.sql',import.meta.url),'utf8'));
  await db.query('insert into capture_receiver.actors values($1,$2,true)',[p.owner_scope,p.actor_ref]);
  const taskId=randomUUID(),runId=randomUUID(),ids=Object.fromEntries(['task','account','device_exit','platform'].map(kind=>[kind,randomUUID()]));
  for(const kind of Object.keys(ids))await db.query(`insert into capture_budget.buckets(bucket_id,kind,owner_scope,subject_ref,platform,
    max_detail_attempts,max_requests,window_start,window_end) values($1,$2,$3,$4,'xiaohongshu',2,2,clock_timestamp()-interval '1 minute',clock_timestamp()+interval '1 day')`,
    [ids[kind],kind,kind==='platform'?'global':p.owner_scope,{task:taskId,account:'account-1',device_exit:'device-1',platform:'xiaohongshu'}[kind]]);
  await db.query(`insert into capture_budget.tasks(owner_scope,task_id,task_ref,platform,allowed_targets,task_bucket_id,platform_bucket_id,current_run_id,lease_epoch,expires_at)
    values($1,$2,$3,'xiaohongshu',$4,$5,$6,$7,1,clock_timestamp()+interval '1 hour')`,
    [p.owner_scope,taskId,{namespace:'legacy_v4',legacy_task_id:'9007199254740993'},[target,{...target,id:'opaque-note-2'}],ids.task,ids.platform,runId]);
  await db.query(`insert into capture_budget.sessions(owner_scope,session_ref,actor_ref,platform,account_ref,device_exit_ref,account_bucket_id,device_bucket_id,credential_epoch,active)
    values($1,'session-1',$2,'xiaohongshu','account-1','device-1',$3,$4,1,true)`,[p.owner_scope,p.actor_ref,ids.account,ids.device_exit]);
  await db.query(`insert into capture_budget.runs(owner_scope,run_id,task_id,actor_ref,session_ref,lease_epoch,credential_epoch,lease_until,source_kind,parser_version,normalization_version,requested_fields)
    values($1,$2,$3,$4,'session-1',1,1,clock_timestamp()+interval '1 hour','platform_api','self-parser-1','capture-v1',array['title','body'])`,[p.owner_scope,runId,taskId,p.actor_ref]);
  return {taskId,runId,ids};
}
function captureFor(binding) {
  return {...binding,contract_version:1,capture_id:randomUUID(),captured_at:new Date().toISOString(),payload_schema:'content.v1',
    payload:{platform:binding.target_ref.platform,content_id:binding.target_ref.id,creator_id:'author-1',canonical_url:'https://www.xiaohongshu.com/explore/'+binding.target_ref.id,
      content_type:'note',title:{value:'预算闭环合成样本',status:'observed'},title_origin:'original',body:{value:'只用于离线验证。',status:'observed'},published_at:{value:null,status:'not_requested'},
      metrics:Object.fromEntries(['likes','collects','comments','shares','views'].map(key=>[key,{value:null,status:'not_requested',precision:null,raw_display:null}]))},
    completeness:{status:'complete',scope:'single_content',reason:null}};
}
const good=async promise=>{const result=await promise;assert.equal(result.error,null,JSON.stringify(result));return result.data;};
const bad=async(promise,code)=>{const result=await promise;assert.equal(result.data,null,JSON.stringify(result));assert.equal(result.error.code,code);cases++;};
async function fixtureCapture(config,overrides={}){
  const binding={...p,session_ref:'session-1',task_ref:{namespace:'legacy_v4',legacy_task_id:'9007199254740993'},run_id:config.runId,lease_epoch:1,credential_epoch:1,
    admission_id:randomUUID(),target_ref:target,source_kind:'platform_api',...overrides};
  await db.query(`insert into capture_receiver.admissions(owner_scope,admission_id,actor_ref,binding,parser_version,normalization_version,requested_fields,issued_at,accept_until)
    values($1,$2,$3,$4,'self-parser-1','capture-v1',array['title','body'],clock_timestamp()-interval '1 second',clock_timestamp()+interval '1 hour')`,[p.owner_scope,binding.admission_id,p.actor_ref,binding]);
  return normalizeCapture(captureFor(binding));
}
async function manifest(config,captures,sequence=1,previous=null,extra={}){
  const registered=await good(readCheckpoint(db,p,config.runId));
  return {manifest_version:1,binding:registered.binding,page:{page_id:randomUUID(),sequence,previous_page_hash:previous,cursor_ref:'cursor:'+randomUUID(),reported_coverage:'complete',stop_reason:null,
    items:captures.map(capture=>({kind:'capture',capture_id:capture.capture_id,envelope_hash:capture.envelope_hash})),...extra}};
}
async function received(capture){const result=await receiveCapture(db,p,capture);assert.equal(result.error,null,JSON.stringify(result));return result;}
async function newRun(config,overrides={}){
  const id=randomUUID();
  await db.query(`insert into capture_budget.runs select owner_scope,$1,task_id,actor_ref,session_ref,2,$3,lease_until,source_kind,$4,normalization_version,$5,paused from capture_budget.runs where run_id=$2`,
    [id,config.runId,overrides.credential_epoch??1,overrides.parser_version??'self-parser-1',overrides.requested_fields??['title','body']]);
  await db.query('update capture_budget.tasks set current_run_id=$1,lease_epoch=2 where task_id=$2',[id,config.taskId]);return {...config,runId:id};
}
async function grant(source,target,expiry="clock_timestamp()+interval '1 hour'",issued="clock_timestamp()-interval '1 second'"){
  const a=await good(readCheckpoint(db,p,source.runId)),b=await good(readCheckpoint(db,p,target.runId)),id=randomUUID();
  await db.query(`insert into capture_checkpoint.recovery_grants(grant_id,owner_scope,actor_ref,source_run_id,target_run_id,source_binding_hash,target_binding_hash,issued_at,expires_at)
    values($1,$2,$3,$4,$5,$6,$7,${issued},${expiry})`,[id,p.owner_scope,p.actor_ref,source.runId,target.runId,a.binding_hash,b.binding_hash]);return id;
}
try{
  await db.exec('create role anon;create role authenticated;');
  let config=await setup(),a=await fixtureCapture(config),b=await fixtureCapture(config);
  let one=await manifest(config,[a]),two=await manifest(config,[b],2,checkpointHash(one));
  const outOfOrder=await good(submitCheckpointPage(db,p,two));assert.equal(outOfOrder.checkpoint.acknowledged_sequence,0);assert.equal(outOfOrder.checkpoint.blocked_reason,'missing_page');cases++;
  const missing=await good(submitCheckpointPage(db,p,one));assert.equal(missing.checkpoint.blocked_reason,'capture_missing');cases++;
  await received(b);assert.equal((await good(readCheckpoint(db,p,config.runId))).checkpoint.acknowledged_sequence,0);cases++;
  const firstReceipt=await received(a);const complete=await good(readCheckpoint(db,p,config.runId));assert.equal(complete.checkpoint.acknowledged_sequence,2);assert.equal(complete.checkpoint.source_coverage,'unverified');cases++;
  const replay=await good(submitCheckpointPage(db,p,one));assert.equal(replay.manifest_hash,checkpointHash(one));assert.equal(replay.checkpoint.acknowledged_sequence,2);cases++;
  await bad(submitCheckpointPage(db,p,{...one,page:{...one.page,cursor_ref:null}}),'page_reused');
  const reordered={page:one.page,binding:one.binding,manifest_version:1};assert.equal((await good(submitCheckpointPage(db,p,reordered))).manifest_hash,checkpointHash(one));cases++;
  const timestamps=(await db.query('select received_at from capture_checkpoint.pages order by sequence')).rows;
  await db.close();db=new PGlite(path.join(dir,'pg'));assert.deepEqual((await db.query('select received_at from capture_checkpoint.pages order by sequence')).rows,timestamps);
  assert.deepEqual(await good(readCheckpoint(db,p,config.runId)),complete);assert.deepEqual(await received(a),firstReceipt);cases++;
  await bad(readCheckpoint(db,{...p,owner_scope:'other-owner'},config.runId),'actor_not_authorized');
  await db.query("insert into capture_receiver.actors values($1,'other-actor',true)",[p.owner_scope]);
  await bad(readCheckpoint(db,{...p,actor_ref:'other-actor'},config.runId),'run_not_authorized');
  await bad(submitCheckpointPage(db,p,{...one,binding:{...one.binding,lease_epoch:99}}),'checkpoint_binding_mismatch');
  await bad(submitCheckpointPage(db,p,{...one,page:{...one.page,acknowledged:true}}),'invalid_checkpoint_request');
  await bad(submitCheckpointPage(db,p,{...one,page:{...one.page,cursor_ref:'https://example.com/?token=secret'}}),'invalid_cursor_ref');
  await bad(submitCheckpointPage(db,p,{...one,page:{...one.page,items:Array(21).fill(one.page.items[0])}}),'invalid_checkpoint_page');
  await bad(submitCheckpointPage(db,p,{...one,page:{...one.page,items:[one.page.items[0],one.page.items[0]]}}),'duplicate_checkpoint_item');
  await bad(submitCheckpointPage(db,p,await manifest(config,[a],3,checkpointHash(two))),'capture_already_listed');
  assert.equal((await db.query('select count(*)::int n from capture_checkpoint.pages')).rows[0].n,2);cases++;

  config=await setup();a=await fixtureCapture(config);one=await manifest(config,[a]);await received(a);
  await db.exec(`create function capture_checkpoint.test_failure() returns trigger language plpgsql as $$ begin raise exception 'synthetic_commit_failure';end;$$;
    create constraint trigger test_failure after insert on capture_checkpoint.pages deferrable initially deferred for each row execute function capture_checkpoint.test_failure();`);
  await bad(submitCheckpointPage(db,p,one),'checkpoint_unavailable');
  for(const table of ['pages','items'])assert.equal((await db.query('select count(*)::int n from capture_checkpoint.'+table)).rows[0].n,0);
  assert.equal((await good(readCheckpoint(db,p,config.runId))).checkpoint.acknowledged_sequence,0);cases++;
  await db.exec('drop trigger test_failure on capture_checkpoint.pages;drop function capture_checkpoint.test_failure();');
  assert.equal((await good(submitCheckpointPage(db,p,one))).checkpoint.acknowledged_sequence,1);cases++;

  for(const [items,extra,reason]of [
    [[],{},'empty_page_unverified'],
    [[{kind:'failure',item_ref:'item:'+randomUUID(),error_code:'parse_failed'}],{reported_coverage:'partial',stop_reason:'partial_failure'},'item_failed'],
    [[{kind:'capture',capture_id:a.capture_id,envelope_hash:'0'.repeat(64)}],{},'capture_hash_mismatch'],
  ]){
    config=await setup();a=await fixtureCapture(config);await received(a);
    if(reason==='capture_hash_mismatch')items[0].capture_id=a.capture_id;
    one=await manifest(config,[],1,null,{...extra,items});const status=await good(submitCheckpointPage(db,p,one));assert.equal(status.checkpoint.blocked_reason,reason);assert.equal(status.checkpoint.acknowledged_sequence,0);cases++;
  }
  // An actual receiver receipt bound to a different historical run cannot ACK this page.
  config=await setup();a=await fixtureCapture(config,{run_id:randomUUID()});await received(a);one=await manifest(config,[a]);
  assert.equal((await good(submitCheckpointPage(db,p,one))).checkpoint.blocked_reason,'capture_binding_mismatch');cases++;

  // Initial historical manifest upload after cancellation, expiration and run switch; ACK arrives later.
  config=await setup();a=await fixtureCapture(config);one=await manifest(config,[a]);const newer=await newRun(config);
  await db.exec("update capture_budget.tasks set cancelled=true;update capture_budget.runs set lease_until=clock_timestamp()-interval '1 second' where lease_epoch=1");
  assert.equal((await good(submitCheckpointPage(db,p,one))).checkpoint.blocked_reason,'capture_missing');await received(a);
  assert.equal((await good(readCheckpoint(db,p,config.runId))).checkpoint.acknowledged_sequence,1);
  assert.equal((await good(readCheckpoint(db,p,newer.runId))).checkpoint.acknowledged_sequence,0);cases++;
  await db.exec('update capture_receiver.actors set enabled=false');await bad(submitCheckpointPage(db,p,one),'actor_not_authorized');

  // SQLite outbox -> receiver -> server manifest: lost ACK replays envelope, never captures again.
  config=await setup();a=await fixtureCapture(config);let sourceCalls=1,transportCalls=0;
  const scope={...Object.fromEntries(['owner_scope','actor_ref','session_ref','task_ref','run_id','lease_epoch','credential_epoch','source_kind'].map(key=>[key,a[key]])),platform:'xiaohongshu',adapter_version:'self-parser-1'};
  const ctx={...p,session_ref:'session-1',authenticated:true,auth_epoch:1,collection_allowed:true,delivery_allowed:true};
  let queue=openCaptureOutbox(path.join(dir,'outbox.sqlite'),scope);
  one=await manifest(config,[a]);
  await queue.stagePage(ctx,{sequence:one.page.sequence,cursor_ref:one.page.cursor_ref,coverage:one.page.reported_coverage,stop_reason:one.page.stop_reason,items:[{kind:'capture',capture:a}]});
  await good(submitCheckpointPage(db,p,one));let original;
  await queue.deliverOne(ctx,async envelope=>{transportCalls++;original=await received(envelope);return null;});queue.close();
  queue=openCaptureOutbox(path.join(dir,'outbox.sqlite'),scope);
  assert.equal((await queue.deliverOne(ctx,()=>{throw new Error('must_wait');})).kind,'deferred');
  const fixtureDb=new DatabaseSync(path.join(dir,'outbox.sqlite'));fixtureDb.exec('update outbox_items set next_allowed_at=0');fixtureDb.close();
  await queue.deliverOne(ctx,async envelope=>{transportCalls++;const result=await received(envelope);assert.deepEqual(result,original);return result;});
  assert.equal(queue.status(ctx).delivered_sequence,1);queue.close();assert.equal(sourceCalls,1);assert.equal(transportCalls,2);
  assert.equal((await good(readCheckpoint(db,p,config.runId))).checkpoint.acknowledged_sequence,1);cases++;

  // New lease is compatible; recovery only supplies advisory metadata, never permission.
  let next=await newRun(config),grantId=await grant(config,next);let advice=await good(readRecoveryAdvice(db,p,grantId));
  assert.equal(advice.acknowledged_prefix.acknowledged_sequence,1);assert.equal(advice.candidate_cursor_ref,one.page.cursor_ref);
  assert.equal(advice.automatic_resume_allowed,false);assert.equal(advice.old_outbox_drain,'unverified');assert.ok(advice.blockers.includes('source_coverage_unverified'));cases++;
  await db.query('update capture_checkpoint.recovery_grants set revoked=true where grant_id=$1',[grantId]);await bad(readRecoveryAdvice(db,p,grantId),'recovery_not_authorized');
  grantId=await grant(config,next,"clock_timestamp()-interval '1 second'","clock_timestamp()-interval '2 seconds'");await bad(readRecoveryAdvice(db,p,grantId),'recovery_grant_expired');
  grantId=await grant(config,next,"clock_timestamp()+interval '2 hours'","clock_timestamp()+interval '1 hour'");await bad(readRecoveryAdvice(db,p,grantId),'recovery_grant_expired');
  grantId=await grant(config,next);await db.exec('update capture_budget.tasks set lease_epoch=3');await bad(readRecoveryAdvice(db,p,grantId),'recovery_target_stale');
  await db.exec('update capture_budget.tasks set lease_epoch=2,cancelled=true');await bad(readRecoveryAdvice(db,p,grantId),'recovery_target_paused');
  await db.exec('update capture_budget.tasks set cancelled=false;update capture_budget.sessions set active=false');await bad(readRecoveryAdvice(db,p,grantId),'recovery_session_invalid');
  await db.exec("update capture_budget.sessions set active=true;update capture_budget.runs set lease_until=clock_timestamp()-interval '1 second' where lease_epoch=2");await bad(readRecoveryAdvice(db,p,grantId),'recovery_target_expired');
  for(const overrides of [{credential_epoch:2},{parser_version:'self-parser-2'},{requested_fields:['title']}]){
    config=await setup();next=await newRun(config,overrides);grantId=await grant(config,next);await bad(readRecoveryAdvice(db,p,grantId),'cursor_incompatible');
  }
  // Partial discovery is never erased by a later complete page.
  for(const stop_reason of ['source_incomplete','truncated_by_budget','partial_capture']){
    config=await setup();a=await fixtureCapture(config);b=await fixtureCapture(config);await received(a);await received(b);
    one=await manifest(config,[a],1,null,{reported_coverage:'partial',stop_reason});two=await manifest(config,[b],2,checkpointHash(one));
    await good(submitCheckpointPage(db,p,two));await good(submitCheckpointPage(db,p,one));next=await newRun(config);grantId=await grant(config,next);advice=await good(readRecoveryAdvice(db,p,grantId));
    assert.equal(advice.candidate_cursor_ref,null);assert.equal(advice.acknowledged_prefix.reported_coverage,'partial');
    assert.equal(advice.acknowledged_prefix.acknowledged_sequence,stop_reason==='partial_capture'?2:1);cases++;
  }
  // A separately registered task cannot inherit another creator/task's cursor.
  config=await setup();const foreignTask=randomUUID(),foreignRun=randomUUID();
  await db.query(`insert into capture_budget.tasks select owner_scope,$1,$2,platform,allowed_targets,task_bucket_id,platform_bucket_id,$3,2,cancelled,paused,expires_at from capture_budget.tasks where task_id=$4`,
    [foreignTask,{namespace:'legacy_v4',legacy_task_id:'9007199254740994'},foreignRun,config.taskId]);
  await db.query(`insert into capture_budget.runs select owner_scope,$1,$2,actor_ref,session_ref,2,credential_epoch,lease_until,source_kind,parser_version,normalization_version,requested_fields,paused from capture_budget.runs where run_id=$3`,[foreignRun,foreignTask,config.runId]);
  grantId=await grant(config,{runId:foreignRun});await bad(readRecoveryAdvice(db,p,grantId),'recovery_task_mismatch');
  await bad(readRecoveryAdvice(db,p,randomUUID()),'recovery_not_authorized');
  await db.query("insert into capture_receiver.actors values($1,'other-actor',true)",[p.owner_scope]);
  await bad(readRecoveryAdvice(db,{...p,actor_ref:'other-actor'},grantId),'recovery_not_authorized');
  // Out-of-order malicious predecessor never links into an already persisted page.
  config=await setup();a=await fixtureCapture(config);b=await fixtureCapture(config);one=await manifest(config,[a]);two=await manifest(config,[b],2,'0'.repeat(64));
  await good(submitCheckpointPage(db,p,two));await bad(submitCheckpointPage(db,p,one),'page_chain_mismatch');
  // Same immutable page concurrently replayed persists exactly once (PGlite serializes).
  config=await setup();a=await fixtureCapture(config);await received(a);one=await manifest(config,[a]);
  const concurrent=await Promise.all([submitCheckpointPage(db,p,one),submitCheckpointPage(db,p,one)]);
  assert.deepEqual(concurrent[0],concurrent[1]);assert.equal((await db.query('select count(*)::int n from capture_checkpoint.pages')).rows[0].n,1);cases++;
  // A grant expiring during ledger work is rejected using the final DB clock.
  config=await setup();next=await newRun(config);grantId=await grant(config,next,"clock_timestamp()+interval '100 milliseconds'");
  const slow={transaction:work=>db.transaction(tx=>work({query:async(sql,args)=>{const result=await tx.query(sql,args);if(sql.startsWith('update capture_checkpoint.watermarks'))await new Promise(resolve=>setTimeout(resolve,180));return result;}}))};
  await bad(readRecoveryAdvice(slow,p,grantId),'recovery_grant_expired');
  await db.exec('set role anon');await assert.rejects(db.query('select * from capture_checkpoint.pages'));await db.exec('reset role');cases++;
  console.log(JSON.stringify({ok:true,cases,scope:'isolated PGlite server ACK ledger and SQLite outbox integration; no production or source requests'}));
}finally{await db.close();fs.rmSync(dir,{recursive:true,force:true});}
