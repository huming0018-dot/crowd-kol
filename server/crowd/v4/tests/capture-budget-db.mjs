import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { randomUUID } from 'node:crypto';
import { reserveDetail,consumeDetail,finishDetail } from '../capture-budget.mjs';
import { receiveCapture } from '../capture-receiver.mjs';
import { openCaptureOutbox } from '../capture-outbox.mjs';
const {PGlite}=createRequire(import.meta.url)(path.join(process.env.CROWD_TEST_TOOLS,'node_modules/@electric-sql/pglite'));
const dir=fs.mkdtempSync(path.join(os.tmpdir(),'crowd-budget-'));
let db=new PGlite(path.join(dir,'pg')),cases=0;
const p={owner_scope:'owner-1',actor_ref:'actor-1'};
const target={platform:'xiaohongshu',kind:'content',id:'opaque-note-1'};
async function setup() {
  await db.exec('drop schema if exists capture_budget cascade;drop schema if exists capture_receiver cascade;');
  await db.exec(fs.readFileSync(new URL('./fixtures/capture-receiver.sql',import.meta.url),'utf8'));
  await db.exec(fs.readFileSync(new URL('./fixtures/capture-budget.sql',import.meta.url),'utf8'));
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
const req=config=>({request_id:randomUUID(),run_id:config.runId,action:'detail',target_ref:structuredClone(target)});
const stats=async()=>(await db.query('select kind,used_detail_attempts,used_requests,active_slots from capture_budget.buckets order by kind')).rows;
const error=async(promise,code)=>{const result=await promise;assert.equal(result.grant,null,JSON.stringify(result));assert.equal(result.error.code,code);cases++;};
// Test fixture only: advance the persisted wait boundary with isolated DB-owner SQL.
// Public budget APIs never accept a client clock, next_allowed_at or a budget key.
const endFixtureWait=async()=>db.exec("update capture_budget.buckets set next_allowed_at=clock_timestamp()-interval '1 second'");
function captureFor(binding) {
  return {...binding,contract_version:1,capture_id:randomUUID(),captured_at:new Date().toISOString(),payload_schema:'content.v1',
    payload:{platform:binding.target_ref.platform,content_id:binding.target_ref.id,creator_id:'author-1',canonical_url:'https://www.xiaohongshu.com/explore/'+binding.target_ref.id,
      content_type:'note',title:{value:'预算闭环合成样本',status:'observed'},title_origin:'original',body:{value:'只用于离线验证。',status:'observed'},published_at:{value:null,status:'not_requested'},
      metrics:Object.fromEntries(['likes','collects','comments','shares','views'].map(key=>[key,{value:null,status:'not_requested',precision:null,raw_display:null}]))},
    completeness:{status:'complete',scope:'single_content',reason:null}};
}
try {
  await db.exec('create role anon;create role authenticated;');
  let config=await setup();const first=req(config);
  const reserve=await reserveDetail(db,p,first);assert.equal(reserve.error,null,JSON.stringify(reserve));assert.equal(reserve.grant.may_dispatch,false);
  assert.deepEqual(await reserveDetail(db,p,first),reserve);
  assert.ok((await stats()).every(row=>row.used_requests===1&&row.used_detail_attempts===1&&row.active_slots===1));cases++;
  const conflict={...first,target_ref:{...target,id:'opaque-note-2'}};await error(reserveDetail(db,p,conflict),'request_reused');
  const consume=await consumeDetail(db,p,first.request_id);assert.equal(consume.error,null,JSON.stringify(consume));assert.equal(consume.grant.may_dispatch,true);
  assert.equal((await consumeDetail(db,p,first.request_id)).grant.may_dispatch,false);
  assert.equal((await db.query('select count(*)::int n from capture_receiver.admissions')).rows[0].n,1);cases++;
  await error(reserveDetail(db,p,req(config)),'concurrency_full');
  assert.equal((await finishDetail(db,p,first.request_id,'failed')).error,null);
  const gap=await reserveDetail(db,p,req(config));assert.equal(gap.error.code,'action_gap');assert.ok(gap.error.next_allowed_at);
  const waits=(await db.query('select min(extract(epoch from next_allowed_at-clock_timestamp())) as seconds from capture_budget.buckets')).rows[0];assert.ok(Number(waits.seconds)>25);cases++;
  await endFixtureWait();const retry=req(config);const second=await reserveDetail(db,p,retry);assert.equal(second.error,null);
  const allowed=await consumeDetail(db,p,retry.request_id);assert.equal(allowed.grant.may_dispatch,true);
  const capture=captureFor(allowed.grant.binding);
  const scope={...Object.fromEntries(['owner_scope','actor_ref','session_ref','task_ref','run_id','lease_epoch','credential_epoch','source_kind'].map(key=>[key,capture[key]])),platform:'xiaohongshu',adapter_version:'self-parser-1'};
  const ctx={...p,session_ref:'session-1',authenticated:true,auth_epoch:1,collection_allowed:true,delivery_allowed:true};
  const queue=openCaptureOutbox(path.join(dir,'outbox.sqlite'),scope);
  await queue.stagePage(ctx,{sequence:1,cursor_ref:null,coverage:'complete',stop_reason:null,items:[{kind:'capture',capture}]});
  const delivered=await queue.deliverOne(ctx,envelope=>receiveCapture(db,p,envelope));assert.equal(delivered.kind,'received');
  assert.equal(queue.status(ctx).delivered_sequence,1);queue.close();
  assert.equal((await finishDetail(db,p,retry.request_id,'succeeded')).error,null);
  const afterTwo=await stats();assert.ok(afterTwo.every(row=>row.used_requests===2&&row.used_detail_attempts===2&&row.active_slots===0));cases++;
  await error(reserveDetail(db,p,req(config)),'budget_exhausted');
  const storedAck=await receiveCapture(db,p,capture);await db.close();db=new PGlite(path.join(dir,'pg'));
  assert.deepEqual(await stats(),afterTwo);assert.equal((await consumeDetail(db,p,retry.request_id)).grant.may_dispatch,false);
  assert.deepEqual(await receiveCapture(db,p,capture),storedAck);await error(reserveDetail(db,p,req(config)),'budget_exhausted');cases++;

  // A newly authorized account/run changes only its own bucket, not the task counter.
  const newAccount=randomUUID(),newRun=randomUUID();
  await db.exec("update capture_budget.buckets set max_detail_attempts=60,max_requests=60 where kind<>'task'");
  const switchedPrincipal={...p,actor_ref:'actor-2'};
  await db.query('insert into capture_receiver.actors values($1,$2,true)',[switchedPrincipal.owner_scope,switchedPrincipal.actor_ref]);
  await db.query(`insert into capture_budget.buckets(bucket_id,kind,owner_scope,subject_ref,platform,max_detail_attempts,max_requests,window_start,window_end)
    values($1,'account',$2,'account-2','xiaohongshu',2,2,clock_timestamp()-interval '1 minute',clock_timestamp()+interval '1 day')`,[newAccount,p.owner_scope]);
  await db.query(`insert into capture_budget.sessions select owner_scope,'session-2',$2,platform,'account-2',device_exit_ref,$1,device_bucket_id,2,active
    from capture_budget.sessions where session_ref='session-1'`,[newAccount,switchedPrincipal.actor_ref]);
  await db.query(`insert into capture_budget.runs select owner_scope,$1,task_id,$3,'session-2',2,2,lease_until,source_kind,parser_version,normalization_version,requested_fields,paused
    from capture_budget.runs where run_id=$2`,[newRun,config.runId,switchedPrincipal.actor_ref]);
  await db.query('update capture_budget.tasks set current_run_id=$1,lease_epoch=2 where task_id=$2',[newRun,config.taskId]);
  await endFixtureWait();await error(reserveDetail(db,switchedPrincipal,req({...config,runId:newRun})),'budget_exhausted');
  assert.equal((await db.query('select used_requests from capture_budget.buckets where bucket_id=$1',[config.ids.task])).rows[0].used_requests,2);
  assert.equal((await db.query('select used_requests from capture_budget.buckets where bucket_id=$1',[newAccount])).rows[0].used_requests,0);cases++;

  for(const level of ['task','account','device_exit','platform']){
    config=await setup();await db.query('update capture_budget.buckets set max_requests=0 where bucket_id=$1',[config.ids[level]]);
    const before=await stats();await error(reserveDetail(db,p,req(config)),'budget_exhausted');assert.deepEqual(await stats(),before);cases++;
  }
  config=await setup();let r=req(config);const concurrent=await Promise.all(Array.from({length:6},()=>reserveDetail(db,p,r)));
  for(const result of concurrent)assert.deepEqual(result,concurrent[0]);assert.ok((await stats()).every(row=>row.used_requests===1));cases++;
  await error(reserveDetail(db,p,req(config)),'concurrency_full');
  const once=await Promise.all([consumeDetail(db,p,r.request_id),consumeDetail(db,p,r.request_id)]);
  assert.equal(once.filter(result=>result.grant.may_dispatch).length,1);cases++;
  await finishDetail(db,p,r.request_id,'failed');

  config=await setup();r=req(config);
  for(const bad of [{...r,action:'comment'},{...r,action:'search'},{...r,action:'media'}])await error(reserveDetail(db,p,bad),'unsupported_budget_action');
  await error(reserveDetail(db,p,{...r,now:'2099-01-01'}),'invalid_budget_request');
  await error(reserveDetail(db,p,{...r,bucket_id:config.ids.task}),'invalid_budget_request');
  await error(reserveDetail(db,p,{...r,target_ref:{...target,id:'outside-task'}}),'target_not_authorized');
  assert.ok((await stats()).every(row=>row.used_requests===0));cases++;
  await error(reserveDetail(db,{owner_scope:'other-owner',actor_ref:p.actor_ref},r),'actor_not_authorized');
  await db.query("insert into capture_receiver.actors values($1,'other-actor',true)",[p.owner_scope]);
  await error(reserveDetail(db,{owner_scope:p.owner_scope,actor_ref:'other-actor'},r),'run_not_authorized');

  for(const [mutation,expected]of [
    ["update capture_budget.tasks set cancelled=true",'task_cancelled'],
    ["update capture_budget.tasks set paused=true",'task_paused'],
    ["update capture_budget.runs set lease_until=clock_timestamp()-interval '1 second'",'lease_expired'],
    ["update capture_budget.tasks set lease_epoch=2",'stale_lease'],
    ["update capture_budget.sessions set credential_epoch=2",'stale_credential'],
    ["update capture_budget.sessions set active=false",'session_not_authorized'],
    ["update capture_budget.buckets set paused=true where kind='platform'",'budget_paused'],
    ["update capture_budget.buckets set window_end=clock_timestamp()-interval '1 second' where kind='account'",'budget_window_closed'],
  ]){config=await setup();await db.exec(mutation);await error(reserveDetail(db,p,req(config)),expected);assert.ok((await stats()).every(row=>row.used_requests===0));}

  config=await setup();r=req(config);await reserveDetail(db,p,r);
  await db.exec('update capture_budget.tasks set cancelled=true');await error(consumeDetail(db,p,r.request_id),'task_cancelled');
  assert.equal((await finishDetail(db,p,r.request_id,'not_started')).error,null);
  assert.ok((await stats()).every(row=>row.active_slots===0&&row.used_requests===1));
  assert.equal((await consumeDetail(db,p,r.request_id)).grant.may_dispatch,false);cases++;
  config=await setup();r=req(config);await reserveDetail(db,p,r);const dispatched=await consumeDetail(db,p,r.request_id);
  const late=captureFor(dispatched.grant.binding);await db.exec('update capture_budget.tasks set cancelled=true');
  assert.equal((await receiveCapture(db,p,late)).receipt.status,'received');await finishDetail(db,p,r.request_id,'succeeded');cases++;

  // Inject elapsed time after the bucket lock query. No caller-visible clock override.
  for(const operation of ['reserve','consume']){
    config=await setup();r=req(config);if(operation==='consume')await reserveDetail(db,p,r);
    await db.exec("update capture_budget.tasks set expires_at=clock_timestamp()+interval '100 milliseconds'");
    const before=await stats();let delayed=false;
    const slow={transaction:work=>db.transaction(tx=>work({query:async(sql,args)=>{
      const result=await tx.query(sql,args);
      if(!delayed&&sql.includes('as window_open')){delayed=true;await new Promise(resolve=>setTimeout(resolve,180));}
      return result;
    }}))};
    await error(operation==='reserve'?reserveDetail(slow,p,r):consumeDetail(slow,p,r.request_id),'lease_expired');
    assert.deepEqual(await stats(),before);assert.equal((await db.query('select count(*)::int n from capture_receiver.admissions')).rows[0].n,0);cases++;
  }
  config=await setup();r=req(config);await reserveDetail(db,p,r);
  await db.exec("update capture_budget.actions set dispatch_until=clock_timestamp()-interval '1 millisecond',reserved_at=clock_timestamp()-interval '1 second'");
  await error(consumeDetail(db,p,r.request_id),'dispatch_expired');
  assert.equal((await finishDetail(db,p,r.request_id,'not_started')).error,null);cases++;

  // Consumption must return the final shortened task/lease/window deadline, not its old reservation deadline.
  for(const [table,column,predicate]of [['tasks','expires_at',''],['runs','lease_until',''],['buckets','window_end',"where kind='account'"]]){
    config=await setup();r=req(config);const reservation=await reserveDetail(db,p,r);
    const shortened=(await db.query(`update capture_budget.${table} set ${column}=clock_timestamp()+interval '5 seconds' ${predicate} returning ${column} as until`)).rows[0].until.toISOString();
    const final=await consumeDetail(db,p,r.request_id);assert.equal(final.error,null);
    assert.ok(final.grant.dispatch_until<reservation.grant.dispatch_until);
    assert.equal(final.grant.dispatch_until,shortened);
    const persisted=(await db.query('select dispatch_until from capture_budget.actions where request_id=$1',[r.request_id])).rows[0].dispatch_until.toISOString();
    assert.equal(persisted,shortened);
    assert.equal((await consumeDetail(db,p,r.request_id)).grant.dispatch_until,shortened);cases++;
  }
  config=await setup();r=req(config);await reserveDetail(db,p,r);
  await db.exec("update capture_budget.tasks set expires_at=clock_timestamp()+interval '100 milliseconds'");
  const beforeLateCommit=await stats();
  const delayedCommit={transaction:work=>db.transaction(tx=>work({query:async(sql,args)=>{
    const result=await tx.query(sql,args);
    if(sql.includes('insert into capture_receiver.admissions'))await new Promise(resolve=>setTimeout(resolve,180));
    return result;
  }}))};
  await error(consumeDetail(delayedCommit,p,r.request_id),'authorization_expired');
  assert.deepEqual(await stats(),beforeLateCommit);
  assert.equal((await db.query('select count(*)::int n from capture_receiver.admissions')).rows[0].n,0);
  assert.equal((await db.query('select state from capture_budget.actions where request_id=$1',[r.request_id])).rows[0].state,'reserved');cases++;

  config=await setup();r=req(config);const beforeFailure=await stats();
  await db.exec(`create function capture_budget.test_failure() returns trigger language plpgsql security invoker as $$ begin raise exception 'synthetic_failure'; end; $$;
    create constraint trigger test_failure after insert on capture_budget.actions deferrable initially deferred for each row execute function capture_budget.test_failure();`);
  await error(reserveDetail(db,p,r),'budget_unavailable');assert.deepEqual(await stats(),beforeFailure);
  assert.equal((await db.query('select count(*)::int n from capture_budget.actions')).rows[0].n,0);
  await db.exec('drop trigger test_failure on capture_budget.actions;drop function capture_budget.test_failure();');cases++;
  await reserveDetail(db,p,r);await consumeDetail(db,p,r.request_id);await finishDetail(db,p,r.request_id,'unknown');
  assert.ok((await stats()).every(row=>row.used_requests===1&&row.active_slots===1));
  await error(reserveDetail(db,p,req(config)),'concurrency_full');await error(finishDetail(db,p,r.request_id,'failed'),'action_state_conflict');
  assert.equal((await consumeDetail(db,p,r.request_id)).grant.may_dispatch,false);cases++;

  const privilege=(await db.query(`select has_schema_privilege('authenticated','capture_budget','usage') s,
    has_table_privilege('anon','capture_budget.actions','select') t,
    has_function_privilege('authenticated','capture_budget.freeze_configuration()','execute') f`)).rows[0];
  assert.deepEqual(privilege,{s:false,t:false,f:false});
  await assert.rejects(db.exec('update capture_budget.buckets set min_interval_seconds=2'),/check constraint/);
  await assert.rejects(db.exec('update capture_budget.runs set credential_epoch=2'),/immutable_budget_binding/);cases++;
  console.log(`PASS capture budget: ${cases} scenario groups; four-layer precharge, one-use dispatch, strict two attempts, cancellation, disk restart, receiver/outbox integration`);
  console.log('BOUNDARY: isolated detail only; no production guard bridge, network auth, source requests, daily reset or unknown-dispatch reconciliation; PGlite serializes concurrent promises');
} finally {await db.close();fs.rmSync(dir,{recursive:true,force:true});}
