import { createHash, randomUUID, randomInt } from 'node:crypto';
import { canonicalJson } from './capture-contract.mjs';

class Denied extends Error { constructor(code, next = null) { super(code); this.next = next; } }
const check = (value, code, next = null) => { if (!value) throw new Denied(code, next); };
const uuid = value => typeof value === 'string' && /^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/.test(value);
const ref = value => typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(value);
const shape = (value, keys) => check(value && typeof value === 'object' && !Array.isArray(value)
  && Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value,key)), 'invalid_budget_request');
const snapshot = value => JSON.parse(canonicalJson(value));
const dateText = value => value instanceof Date && Number.isFinite(value.getTime()) ? value.toISOString() : null;
function principal(input) {
  const value = snapshot(input); shape(value,['owner_scope','actor_ref']);
  check(ref(value.owner_scope) && ref(value.actor_ref),'invalid_budget_principal'); return value;
}
function request(input) {
  const value=snapshot(input);shape(value,['request_id','run_id','action','target_ref']);
  check(uuid(value.request_id)&&uuid(value.run_id),'invalid_budget_request');
  check(value.action==='detail','unsupported_budget_action');
  shape(value.target_ref,['platform','kind','id']);
  check(value.target_ref.kind==='content'&&ref(value.target_ref.platform)&&typeof value.target_ref.id==='string'
    &&value.target_ref.id.length>0&&value.target_ref.id.length<=256&&!/[\s/?#%&=\\]/u.test(value.target_ref.id),'invalid_budget_target');
  return value;
}
async function guarded(work) {
  try {return await work();}
  catch(failure){return {grant:null,error:{code:failure instanceof Denied?failure.message:'budget_unavailable',
    next_allowed_at:failure instanceof Denied?failure.next:null}};}
}
async function actorLock(tx,p) {
  const actor=(await tx.query('select enabled from capture_receiver.actors where owner_scope=$1 and actor_ref=$2 for update',[p.owner_scope,p.actor_ref])).rows[0];
  check(actor?.enabled,'actor_not_authorized');
}
async function currentRun(tx,p,runId) {
  // Task identity is looked up from a trusted run, never from a caller-selected budget key.
  const pointer=(await tx.query('select task_id from capture_budget.runs where owner_scope=$1 and run_id=$2 and actor_ref=$3',[p.owner_scope,runId,p.actor_ref])).rows[0];
  check(pointer,'run_not_authorized');
  const task=(await tx.query('select *,expires_at>clock_timestamp() as unexpired from capture_budget.tasks where owner_scope=$1 and task_id=$2 for update',[p.owner_scope,pointer.task_id])).rows[0];
  const run=(await tx.query('select *,lease_until>clock_timestamp() as unexpired from capture_budget.runs where owner_scope=$1 and run_id=$2 and actor_ref=$3 for update',[p.owner_scope,runId,p.actor_ref])).rows[0];
  check(run,'run_not_authorized');
  check(task&&!task.cancelled,'task_cancelled');check(!task.paused&&!run.paused,'task_paused');
  check(task.unexpired&&run.unexpired,'lease_expired');
  check(['xiaohongshu','bilibili','douyin','kuaishou','weibo','zhihu','tieba'].includes(task.platform),'invalid_budget_configuration');
  check(task.current_run_id===runId&&task.lease_epoch===run.lease_epoch,'stale_lease');
  const session=(await tx.query('select * from capture_budget.sessions where owner_scope=$1 and session_ref=$2 for update',[p.owner_scope,run.session_ref])).rows[0];
  check(session?.active&&session.actor_ref===p.actor_ref&&session.platform===task.platform,'session_not_authorized');
  check(session.credential_epoch===run.credential_epoch,'stale_credential');
  check(ref(run.parser_version)&&run.normalization_version==='capture-v1'&&new Set(run.requested_fields).size===run.requested_fields.length,'invalid_budget_configuration');
  const taskRef=configTaskRef(task.task_ref);
  check(taskRef&&ref(run.session_ref)&&ref(session.account_ref)&&ref(session.device_exit_ref),'invalid_budget_configuration');
  const expected=[
    {id:task.task_bucket_id,kind:'task',owner:p.owner_scope,subject:task.task_id},
    {id:session.account_bucket_id,kind:'account',owner:p.owner_scope,subject:session.account_ref},
    {id:session.device_bucket_id,kind:'device_exit',owner:p.owner_scope,subject:session.device_exit_ref},
    {id:task.platform_bucket_id,kind:'platform',owner:'global',subject:task.platform},
  ];
  check(new Set(expected.map(item=>item.id)).size===4,'invalid_budget_configuration');
  return {task,run,session,expected};
}
async function bucketLocks(tx,configuration) {
  const ids=configuration.expected.map(item=>item.id).sort();
  const buckets=(await tx.query(`select *,clock_timestamp() between window_start and window_end as window_open,
    greatest(next_allowed_at,blocked_until)>clock_timestamp() as waiting,
    blocked_until>clock_timestamp() as blocked,greatest(next_allowed_at,blocked_until) as wait_until
    from capture_budget.buckets where bucket_id=any($1::uuid[]) order by bucket_id for update`,[ids])).rows;
  check(buckets.length===4,'invalid_budget_configuration');
  for(const item of configuration.expected){
    const bucket=buckets.find(row=>row.bucket_id===item.id);
    check(bucket&&bucket.kind===item.kind&&bucket.owner_scope===item.owner&&bucket.subject_ref===item.subject&&bucket.platform===configuration.task.platform,'invalid_budget_configuration');
  }
  return buckets;
}
function configTaskRef(task) {
  if(!task||typeof task!=='object'||Array.isArray(task))return false;
  if(task.namespace==='legacy_v4')return Object.keys(task).length===2&&typeof task.legacy_task_id==='string'
    &&/^[1-9]\d{0,18}$/.test(task.legacy_task_id)&&BigInt(task.legacy_task_id)<=9223372036854775807n;
  return task.namespace==='capture_v1'&&Object.keys(task).length===2&&uuid(task.id);
}
async function freshWindow(tx,p,config,buckets,dispatchUntil=null) {
  // Re-evaluate only after all row locks: time may have advanced while waiting.
  const time=(await tx.query(`with t as materialized(select clock_timestamp() as at)
    select task.expires_at>t.at as task_valid,r.lease_until>t.at as lease_valid,
      bool_and(t.at between b.window_start and b.window_end) as windows_valid,
      least(task.expires_at,r.lease_until,min(b.window_end),coalesce($4::timestamptz,'infinity'::timestamptz)) as valid_until,
      coalesce($4::timestamptz,'infinity'::timestamptz)>t.at as dispatch_valid
    from t,capture_budget.tasks task,capture_budget.runs r,capture_budget.buckets b
    where task.owner_scope=$1 and task.task_id=$2 and r.owner_scope=$1 and r.run_id=$3 and b.bucket_id=any($5::uuid[])
    group by task.expires_at,r.lease_until,t.at`,[p.owner_scope,config.task.task_id,config.run.run_id,dispatchUntil,buckets.map(bucket=>bucket.bucket_id)])).rows[0];
  check(time.task_valid&&time.lease_valid,'lease_expired');check(time.windows_valid,'budget_window_closed');check(time.dispatch_valid,'dispatch_expired');
  return time.valid_until;
}
const metadata = action => ({request_id:action.request_id,admission_id:action.admission_id,state:action.state,
  reserved_at:action.reserved_at.toISOString(),dispatch_until:action.dispatch_until.toISOString(),may_dispatch:false});
const actionRow = async(tx,p,id)=>(await tx.query('select * from capture_budget.actions where owner_scope=$1 and request_id=$2 for update',[p.owner_scope,id])).rows[0];

// Offline trusted-service entry point. Authenticate principal outside this module.
export async function reserveDetail(db,authenticatedPrincipal,input) {
  return guarded(async()=>{
    const p=principal(authenticatedPrincipal),r=request(input);
    const requestHash=createHash('sha256').update(canonicalJson({principal:p,request:r})).digest('hex');
    return db.transaction(async tx=>{
      await actorLock(tx,p);
      const previous=await actionRow(tx,p,r.request_id);
      if(previous){check(previous.actor_ref===p.actor_ref,'run_not_authorized');check(previous.request_hash===requestHash,'request_reused');return {grant:metadata(previous),error:null};}
      const config=await currentRun(tx,p,r.run_id);
      check(r.target_ref.platform===config.task.platform&&config.task.allowed_targets.some(target=>canonicalJson(target)===canonicalJson(r.target_ref)),'target_not_authorized');
      const buckets=await bucketLocks(tx,config);
      for(const bucket of buckets){
        check(!bucket.paused,'budget_paused');check(bucket.window_open,'budget_window_closed');
        check(bucket.used_detail_attempts<bucket.max_detail_attempts&&bucket.used_requests<bucket.max_requests,'budget_exhausted');
        check(bucket.active_slots<bucket.max_concurrency,'concurrency_full');
        check(!bucket.waiting,'action_gap',dateText(bucket.wait_until));
      }
      const validUntil=await freshWindow(tx,p,config,buckets);
      const jitter=randomInt(16),admissionId=randomUUID(),ids=buckets.map(bucket=>bucket.bucket_id);
      await tx.query(`update capture_budget.buckets set used_detail_attempts=used_detail_attempts+1,used_requests=used_requests+1,
        active_slots=active_slots+1,next_allowed_at=clock_timestamp()+make_interval(secs=>min_interval_seconds+$2)
        where bucket_id=any($1::uuid[])`,[ids,jitter]);
      const saved=(await tx.query(`insert into capture_budget.actions(owner_scope,request_id,actor_ref,run_id,request_hash,target_ref,
        admission_id,bucket_ids,jitter_seconds,reserved_at,dispatch_until,state)
        select $1,$2,$3,$4,$5,$6,$7,$8,$9,clock_timestamp(),least($10::timestamptz,clock_timestamp()+interval '30 seconds'),'reserved'
        where clock_timestamp()<$10::timestamptz
        on conflict do nothing returning *`,[p.owner_scope,r.request_id,p.actor_ref,r.run_id,requestHash,r.target_ref,admissionId,ids,jitter,validUntil])).rows[0];
      if(!saved){const collision=await actionRow(tx,p,r.request_id);throw new Denied(collision?'request_reused':'authorization_expired');}
      return {grant:metadata(saved),error:null};
    });
  });
}

export async function consumeDetail(db,authenticatedPrincipal,requestId) {
  return guarded(async()=>{
    const p=principal(authenticatedPrincipal);check(uuid(requestId),'invalid_budget_request');
    return db.transaction(async tx=>{
      await actorLock(tx,p);const action=await actionRow(tx,p,requestId);
      check(action&&action.actor_ref===p.actor_ref,'action_not_authorized');
      if(action.state!=='reserved')return {grant:metadata(action),error:null};
      const config=await currentRun(tx,p,action.run_id),buckets=await bucketLocks(tx,config);
      check(config.task.allowed_targets.some(target=>canonicalJson(target)===canonicalJson(action.target_ref)),'target_not_authorized');
      check(canonicalJson([...action.bucket_ids].sort())===canonicalJson(buckets.map(bucket=>bucket.bucket_id).sort()),'budget_binding_changed');
      for(const bucket of buckets){check(!bucket.paused,'budget_paused');check(bucket.window_open,'budget_window_closed');check(!bucket.blocked,'budget_blocked',dateText(bucket.blocked_until));}
      const validUntil=await freshWindow(tx,p,config,buckets,action.dispatch_until);
      const binding={owner_scope:p.owner_scope,actor_ref:p.actor_ref,session_ref:config.run.session_ref,task_ref:config.task.task_ref,
        run_id:config.run.run_id,lease_epoch:config.run.lease_epoch,credential_epoch:config.run.credential_epoch,
        admission_id:action.admission_id,target_ref:action.target_ref,source_kind:config.run.source_kind};
      const admitted=await tx.query(`insert into capture_receiver.admissions(owner_scope,admission_id,actor_ref,binding,parser_version,
        normalization_version,requested_fields,issued_at,accept_until)
        select $1,$2,$3,$4,$5,$6,$7,date_trunc('milliseconds',clock_timestamp()),clock_timestamp()+interval '24 hours'
        where clock_timestamp()<$8::timestamptz returning admission_id`,
      [p.owner_scope,action.admission_id,p.actor_ref,binding,config.run.parser_version,config.run.normalization_version,config.run.requested_fields,validUntil]);
      check(admitted.rows.length===1,'authorization_expired');
      await tx.query(`update capture_budget.buckets set next_allowed_at=greatest(next_allowed_at,
        clock_timestamp()+make_interval(secs=>min_interval_seconds+$2)) where bucket_id=any($1::uuid[])`,[action.bucket_ids,action.jitter_seconds]);
      const consumed=(await tx.query("update capture_budget.actions set state='consumed',consumed_at=clock_timestamp(),dispatch_until=$3 where owner_scope=$1 and request_id=$2 and clock_timestamp()<$3::timestamptz returning *",[p.owner_scope,requestId,validUntil])).rows[0];
      check(consumed,'authorization_expired');
      return {grant:{...metadata(consumed),may_dispatch:true,binding},error:null};
    });
  });
}

// Success/failure mean the attempt is known to have ended; unknown retains its slot.
// Neither retries nor releases refund request/detail counters.
export async function finishDetail(db,authenticatedPrincipal,requestId,outcome) {
  return guarded(async()=>{
    const p=principal(authenticatedPrincipal);check(uuid(requestId)&&['succeeded','failed','unknown','not_started'].includes(outcome),'invalid_budget_request');
    return db.transaction(async tx=>{
      await actorLock(tx,p);const action=await actionRow(tx,p,requestId);
      check(action&&action.actor_ref===p.actor_ref,'action_not_authorized');
      if(action.state===outcome)return {grant:metadata(action),error:null};
      check(outcome==='not_started'?action.state==='reserved':action.state==='consumed','action_state_conflict');
      await tx.query('select bucket_id from capture_budget.buckets where bucket_id=any($1::uuid[]) order by bucket_id for update',[action.bucket_ids]);
      if(outcome!=='unknown')await tx.query('update capture_budget.buckets set active_slots=active_slots-1 where bucket_id=any($1::uuid[])',[action.bucket_ids]);
      const closed=(await tx.query('update capture_budget.actions set state=$3,closed_at=clock_timestamp() where owner_scope=$1 and request_id=$2 returning *',[p.owner_scope,requestId,outcome])).rows[0];
      return {grant:metadata(closed),error:null};
    });
  });
}
