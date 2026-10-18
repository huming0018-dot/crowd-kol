import { DatabaseSync } from 'node:sqlite';
import { createHash, randomUUID } from 'node:crypto';
import { closeSync, existsSync, lstatSync, openSync } from 'node:fs';
import { canonicalJson, normalizeCapture } from './capture-contract.mjs';

class OutboxError extends Error {}
const check = (condition, code) => { if (!condition) throw new OutboxError(code); };
const ref = value => typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(value);
const uuid = value => typeof value === 'string' && /^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/.test(value);
const scopeKeys = ['owner_scope','actor_ref','session_ref','task_ref','run_id','lease_epoch','credential_epoch','platform','source_kind','adapter_version'];
const failureCodes = ['parse_failed','not_found','private','auth_required','risk_paused','timeout','source_error'];
const authCodes = ['principal_required','principal_mismatch','actor_not_authorized'];
const rejectionCodes = ['invalid_capture','capture_too_complex','capture_too_large','unsupported_contract','invalid_source_kind',
  'invalid_canonical_url','unsafe_canonical_url','unsafe_embedded_url','credential_material','unobserved_value','target_mismatch',
  'incomplete_capture','envelope_hash_mismatch','capture_binding_mismatch','principal_required','principal_mismatch',
  'actor_not_authorized','admission_missing','admission_revoked','invalid_admission','requested_fields_mismatch',
  'admission_expired','capture_time_invalid','admission_used','request_reused'];
const shape = (value, keys, code) => check(value && typeof value === 'object' && !Array.isArray(value)
  && Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key)), code);
const snapshot = value => JSON.parse(canonicalJson(value));
const hash = value => createHash('sha256').update(canonicalJson(value)).digest('hex');

function validateScope(input) {
  const scope = snapshot(input); shape(scope, scopeKeys, 'invalid_outbox_scope');
  check(['owner_scope','actor_ref','session_ref','adapter_version'].every(key => ref(scope[key])), 'invalid_outbox_scope');
  check(uuid(scope.run_id) && ['lease_epoch','credential_epoch'].every(key => Number.isSafeInteger(scope[key]) && scope[key] >= 1), 'invalid_outbox_scope');
  check(['xiaohongshu','bilibili','douyin','kuaishou','weibo','zhihu','tieba'].includes(scope.platform), 'invalid_outbox_scope');
  check(['rendered_public_dom','platform_api','authorized_export'].includes(scope.source_kind), 'invalid_outbox_scope');
  const task = scope.task_ref;
  if (task?.namespace === 'legacy_v4') {
    shape(task, ['namespace','legacy_task_id'], 'invalid_outbox_scope');
    check(typeof task.legacy_task_id === 'string' && /^[1-9]\d{0,18}$/.test(task.legacy_task_id)
      && BigInt(task.legacy_task_id) <= 9223372036854775807n, 'invalid_outbox_scope');
  } else {
    shape(task, ['namespace','id'], 'invalid_outbox_scope');
    check(task.namespace === 'capture_v1' && uuid(task.id), 'invalid_outbox_scope');
  }
  return scope;
}

// Experimental Node 22 SQLite. Local evidence only; this is not browser storage.
export function openCaptureOutbox(filename, scopeInput) {
  const scope = validateScope(scopeInput), scopeJson = canonicalJson(scope);
  if (filename !== ':memory:') {
    if (!existsSync(filename)) closeSync(openSync(filename, 'wx', 0o600));
    const stat = lstatSync(filename);
    check(stat.isFile() && !stat.isSymbolicLink() && (stat.mode & 0o077) === 0, 'unsafe_outbox_file');
  }
  const db = new DatabaseSync(filename);
  const keys = [scope.owner_scope, scope.run_id];
  const stmt = sql => db.prepare(sql);
  function transaction(action) {
    try {
      db.exec('BEGIN IMMEDIATE');
      try { const result = action(); db.exec('COMMIT'); return result; }
      catch (failure) { db.exec('ROLLBACK'); throw failure; }
    } catch (failure) {
      if (failure instanceof OutboxError) throw failure;
      throw new OutboxError('outbox_storage_failure');
    }
  }
  function authorize(context, action = 'read') {
    const ctx = snapshot(context);
    shape(ctx, ['owner_scope','actor_ref','session_ref','authenticated','auth_epoch','collection_allowed','delivery_allowed'], 'invalid_outbox_context');
    check(ctx.authenticated === true && ['owner_scope','actor_ref','session_ref'].every(key => ctx[key] === scope[key]), 'outbox_not_authorized');
    check(typeof ctx.collection_allowed === 'boolean' && typeof ctx.delivery_allowed === 'boolean', 'invalid_outbox_context');
    check(Number.isSafeInteger(ctx.auth_epoch) && ctx.auth_epoch >= 1, 'invalid_outbox_context');
    if (action === 'collect') check(ctx.collection_allowed, 'collection_paused');
    if (action === 'deliver') check(ctx.delivery_allowed, 'delivery_stopped');
    return ctx;
  }
  function run() { return stmt('select * from outbox_runs where owner_scope=? and run_id=?').get(...keys); }
  function advanceDelivered() {
    let sequence = run().delivered_sequence;
    for (;;) {
      const next = stmt('select cursor_ref from outbox_pages where owner_scope=? and run_id=? and sequence=?').get(...keys, sequence + 1);
      if (!next) break;
      const unresolved = stmt("select count(*) as n from outbox_items where owner_scope=? and run_id=? and sequence=? and state!='received'").get(...keys, sequence + 1).n;
      if (unresolved) break;
      sequence++;
      stmt('update outbox_runs set delivered_sequence=?,delivered_cursor=? where owner_scope=? and run_id=?').run(sequence, next.cursor_ref, ...keys);
    }
  }
  function displayState(row) {
    return ['pending','unknown'].includes(row.state) ? row.legacy_attempts_unknown ? 'legacy_unknown' : row.attempt_count >= 3 ? 'exhausted' : row.state : row.state;
  }
  function localStatus() {
    const current = run();
    const coverage = sequence => sequence === 0 ? 'none' :
      stmt("select count(*) as n from outbox_pages where owner_scope=? and run_id=? and sequence<=? and coverage='partial'").get(...keys, sequence).n
      || stmt("select count(*) as n from outbox_items where owner_scope=? and run_id=? and sequence<=? and state in ('rejected','failed')").get(...keys, sequence).n ? 'partial' : 'complete';
    const counts = { pending: 0, unknown: 0, received: 0, rejected: 0, blocked: 0, failed: 0, exhausted: 0, legacy_unknown: 0 };
    for (const row of stmt('select state,attempt_count,legacy_attempts_unknown from outbox_items where owner_scope=? and run_id=?').all(...keys)) counts[displayState(row)]++;
    return { captured_sequence: current.captured_sequence, captured_cursor: current.captured_cursor,
      delivered_sequence: current.delivered_sequence, delivered_cursor: current.delivered_cursor,
      captured_coverage: coverage(current.captured_sequence), delivered_coverage: coverage(current.delivered_sequence), counts,
      delivery: {in_flight:current.flight_token!==null,capture_id:current.flight_capture_id,process_id:current.flight_pid} };
  }
  try {
    db.exec(`pragma journal_mode=WAL; pragma synchronous=FULL; pragma foreign_keys=ON; pragma busy_timeout=1000;
      create table if not exists outbox_runs (
        owner_scope text not null,run_id text not null,scope_json text not null,
        captured_sequence integer not null default 0,delivered_sequence integer not null default 0,
        captured_cursor text,delivered_cursor text,primary key(owner_scope,run_id),
        check(delivered_sequence>=0 and captured_sequence>=delivered_sequence));
      create table if not exists outbox_pages (
        owner_scope text not null,run_id text not null,sequence integer not null check(sequence>0),
        manifest_json text not null,manifest_hash text not null,cursor_ref text,
        coverage text not null check(coverage in ('complete','partial')),primary key(owner_scope,run_id,sequence),
        foreign key(owner_scope,run_id) references outbox_runs);
      create table if not exists outbox_items (
        owner_scope text not null,run_id text not null,sequence integer not null,item_index integer not null,
        capture_id text,envelope_hash text,envelope_json text,item_ref text,error_code text,
        state text not null check(state in ('pending','unknown','received','rejected','blocked','failed')),receipt_json text,blocked_auth_epoch integer,
        primary key(owner_scope,run_id,sequence,item_index),unique(owner_scope,capture_id),
        foreign key(owner_scope,run_id,sequence) references outbox_pages,
        check((state='received')=(receipt_json is not null)),
        check((state='blocked')=(blocked_auth_epoch is not null)),
        check((state='failed' and capture_id is null and envelope_json is null and item_ref is not null)
          or (state!='failed' and capture_id is not null and envelope_hash is not null and envelope_json is not null)));
    `);
    transaction(() => {
      // Legacy unknown/blocked has no trustworthy count; only pending proves no dispatch.
      const columns = stmt('pragma table_info(outbox_items)').all().map(row => row.name);
      if (!columns.includes('attempt_count')) {
        db.exec(`alter table outbox_items add column attempt_count integer not null default 3 check(attempt_count between 0 and 3);
          alter table outbox_items add column next_allowed_at integer not null default 0;
          alter table outbox_items add column legacy_attempts_unknown integer not null default 1 check(legacy_attempts_unknown in (0,1));
          alter table outbox_runs add column flight_token text;
          alter table outbox_runs add column flight_capture_id text;
          alter table outbox_runs add column flight_pid integer;
          update outbox_items set attempt_count=0,legacy_attempts_unknown=0 where state='pending';`);
      }
      stmt('insert into outbox_runs(owner_scope,run_id,scope_json) values(?,?,?) on conflict do nothing').run(...keys, scopeJson);
      check(run().scope_json === scopeJson, 'outbox_scope_conflict');
    });
  } catch (failure) { db.close(); throw failure; }

  function applyResult(context, captureId, response, claim = null) {
      const ctx = authorize(context, 'deliver'); check(uuid(captureId), 'invalid_capture_id');
      const result = snapshot(response);
      return transaction(() => {
        const row = stmt('select * from outbox_items where owner_scope=? and run_id=? and capture_id=?').get(...keys, captureId);
        check(row, 'capture_not_queued');
        if (claim !== null && run().flight_token !== claim) return { stale: true, progress: localStatus() };
        let state = 'unknown', errorCode = 'ack_unknown', receiptJson = null;
        if (result !== null) {
          shape(result, ['receipt','error'], 'invalid_capture_ack');
          if (result.error === null) {
            const receipt = result.receipt, capture = JSON.parse(row.envelope_json);
            shape(receipt, ['capture_id','status','verdict','received_at','envelope_hash','run_id','lease_epoch','credential_epoch','admission_id'], 'invalid_capture_ack');
            check(receipt.status === 'received' && receipt.verdict === 'stored_unreviewed', 'invalid_capture_ack');
            for (const key of ['capture_id','envelope_hash','run_id','lease_epoch','credential_epoch','admission_id'])
              check(receipt[key] === capture[key], 'capture_ack_mismatch');
            check(typeof receipt.received_at === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(receipt.received_at)
              && Number.isFinite(Date.parse(receipt.received_at)) && new Date(receipt.received_at).toISOString() === receipt.received_at
              && Date.parse(receipt.received_at) >= Date.parse(capture.captured_at), 'invalid_capture_ack');
            state = 'received'; errorCode = null; receiptJson = canonicalJson(receipt);
          } else {
            check(result.receipt === null, 'invalid_capture_ack'); shape(result.error, ['code'], 'invalid_capture_ack');
            check(result.error.code === 'receiver_unavailable' || rejectionCodes.includes(result.error.code), 'invalid_capture_ack');
            errorCode = result.error.code; state = errorCode === 'receiver_unavailable' ? 'unknown' : authCodes.includes(errorCode) ? 'blocked' : 'rejected';
          }
        }
        check(claim !== null || !run().flight_token || state === 'received', 'delivery_in_flight');
        if (claim !== null && row.state === 'received' && state !== 'received') return {stale:true,progress:localStatus()};
        if (row.state === 'received') {
          check(state === 'received' && row.receipt_json === receiptJson, 'receipt_conflict'); return localStatus();
        }
        if (row.state === 'blocked') {
          check(state === 'blocked' && row.error_code === errorCode, 'auth_resume_required'); return localStatus();
        }
        check(row.state !== 'rejected' || state === 'received' || state === 'rejected' && row.error_code === errorCode, 'rejection_conflict');
        stmt('update outbox_items set state=?,error_code=?,receipt_json=?,blocked_auth_epoch=? where owner_scope=? and run_id=? and capture_id=?')
          .run(state, errorCode, receiptJson, state === 'blocked' ? ctx.auth_epoch : null, ...keys, captureId);
        advanceDelivered(); return localStatus();
      });
   }
  function releaseFlight(token) {
    return transaction(() => {
      const active=run();
      if(active.flight_token!==token)return;
      // A slow failed call still receives the full backoff after it settles.
      stmt("update outbox_items set next_allowed_at=max(next_allowed_at,?+case when attempt_count=1 then 5000 else 20000 end) where owner_scope=? and run_id=? and capture_id=? and state!='received'").run(Date.now(),...keys,active.flight_capture_id);
      stmt('update outbox_runs set flight_token=null,flight_capture_id=null,flight_pid=null where owner_scope=? and run_id=? and flight_token=?').run(...keys,token);
    });
  }
  function claimDelivery(context) {
    authorize(context,'deliver');
    return transaction(() => {
      const active=run();
      if(active.flight_token){
        let dead=false;
        try { process.kill(active.flight_pid,0); } catch(failure) { dead=failure.code==='ESRCH'; }
        // No time-based lease: a slow live transport cannot be dispatched twice.
        // PID reuse conservatively blocks; the queue is local to this machine.
        if(!dead)return {kind:'busy'};
        stmt('update outbox_runs set flight_token=null,flight_capture_id=null,flight_pid=null where owner_scope=? and run_id=?').run(...keys);
      }
      if(stmt("select 1 from outbox_items where owner_scope=? and run_id=? and state='blocked'").get(...keys))return {kind:'idle',reason:'auth_blocked'};
      const now=Date.now();
      const row=stmt("select * from outbox_items where owner_scope=? and run_id=? and state in ('pending','unknown') and legacy_attempts_unknown=0 and attempt_count<3 and next_allowed_at<=? order by sequence,item_index limit 1").get(...keys,now);
      if(!row){
        const waiting=stmt("select min(next_allowed_at) as at from outbox_items where owner_scope=? and run_id=? and state in ('pending','unknown') and legacy_attempts_unknown=0 and attempt_count<3").get(...keys).at;
        return waiting!==null?{kind:'deferred',next_allowed_at:waiting}:{kind:'idle',reason:'no_automatic_attempt'};
      }
      const token=randomUUID(),attempt=row.attempt_count+1,next=now+(attempt===1?5000:20000);
      stmt("update outbox_items set state='unknown',error_code='ack_unknown',attempt_count=?,next_allowed_at=? where owner_scope=? and run_id=? and capture_id=?").run(attempt,next,...keys,row.capture_id);
      stmt('update outbox_runs set flight_token=?,flight_capture_id=?,flight_pid=? where owner_scope=? and run_id=?').run(token,row.capture_id,process.pid,...keys);
      return {token,capture:JSON.parse(row.envelope_json)};
    });
  }

  let activeDispatch=false;
  const api = {
    async stagePage(context, input) {
      authorize(context, 'collect');
      const page = snapshot(input);
      shape(page, ['sequence','cursor_ref','coverage','stop_reason','items'], 'invalid_outbox_page');
      check(Number.isSafeInteger(page.sequence) && page.sequence >= 1, 'invalid_outbox_page');
      check(page.cursor_ref === null || typeof page.cursor_ref === 'string' && page.cursor_ref.startsWith('cursor:') && uuid(page.cursor_ref.slice(7)), 'invalid_cursor_ref');
      check(Array.isArray(page.items) && page.items.length <= 20, 'invalid_outbox_page');
      check(page.coverage === 'complete' ? page.stop_reason === null
        : page.coverage === 'partial' && ['partial_failure','partial_capture','truncated_by_budget','source_incomplete'].includes(page.stop_reason), 'invalid_outbox_coverage');
      const entries = [], manifestItems = [], seen = new Set();
      for (const item of page.items) {
        if (item.kind === 'capture') {
          shape(item, ['kind','capture'], 'invalid_outbox_item');
          const capture = await normalizeCapture(item.capture);
          for (const key of scopeKeys.filter(key => !['adapter_version','platform'].includes(key)))
            check(canonicalJson(capture[key]) === canonicalJson(scope[key]), 'outbox_capture_binding_mismatch');
          check(capture.payload.platform === scope.platform, 'outbox_capture_binding_mismatch');
          check(!seen.has(capture.capture_id), 'duplicate_page_item'); seen.add(capture.capture_id);
          check(page.coverage === 'partial' || capture.completeness.status === 'complete', 'invalid_outbox_coverage');
          entries.push({capture}); manifestItems.push({kind:'capture',capture_id:capture.capture_id,envelope_hash:capture.envelope_hash});
        } else {
          shape(item, ['kind','item_ref','error_code'], 'invalid_outbox_item');
          check(item.kind === 'failure' && typeof item.item_ref === 'string' && item.item_ref.startsWith('item:') && uuid(item.item_ref.slice(5))
            && failureCodes.includes(item.error_code), 'invalid_outbox_item');
          check(!seen.has(item.item_ref), 'duplicate_page_item'); seen.add(item.item_ref);
          check(page.coverage === 'partial', 'invalid_outbox_coverage');
          entries.push(item); manifestItems.push(item);
        }
      }
      const manifest = { ...page, items: manifestItems }, manifestJson = canonicalJson(manifest), manifestHash = hash(manifest);
      authorize(context, 'collect'); // Hashing yielded; login/collection may have changed.
      return transaction(() => {
        const prior = stmt('select manifest_hash from outbox_pages where owner_scope=? and run_id=? and sequence=?').get(...keys, page.sequence);
        if (prior) { check(prior.manifest_hash === manifestHash, 'page_reused'); return localStatus(); }
        check(page.sequence === run().captured_sequence + 1, 'page_sequence_gap');
        stmt('insert into outbox_pages values(?,?,?,?,?,?,?)').run(...keys, page.sequence, manifestJson, manifestHash, page.cursor_ref, page.coverage);
        for (const [index, item] of entries.entries()) {
          if (item.capture) {
            const capture = item.capture;
            const priorCapture = stmt('select envelope_hash from outbox_items where owner_scope=? and capture_id=?').get(scope.owner_scope, capture.capture_id);
            check(!priorCapture, priorCapture?.envelope_hash === capture.envelope_hash ? 'capture_already_queued' : 'request_reused');
            stmt("insert into outbox_items(owner_scope,run_id,sequence,item_index,capture_id,envelope_hash,envelope_json,state,attempt_count,legacy_attempts_unknown) values(?,?,?,?,?,?,?,'pending',0,0)")
              .run(...keys, page.sequence, index, capture.capture_id, capture.envelope_hash, canonicalJson(capture));
          } else {
            stmt("insert into outbox_items(owner_scope,run_id,sequence,item_index,item_ref,error_code,state,attempt_count,legacy_attempts_unknown) values(?,?,?,?,?,?,'failed',0,0)")
              .run(...keys, page.sequence, index, item.item_ref, item.error_code);
          }
        }
        stmt('update outbox_runs set captured_sequence=?,captured_cursor=? where owner_scope=? and run_id=?').run(page.sequence, page.cursor_ref, ...keys);
        advanceDelivered(); return localStatus();
      });
    },
    pending(context, limit = 20) {
      authorize(context, 'deliver'); check(Number.isInteger(limit) && limit >= 1 && limit <= 20, 'invalid_outbox_limit');
      // One identity failure blocks this run, rather than trying each remaining item.
      if (stmt("select 1 from outbox_items where owner_scope=? and run_id=? and state='blocked' limit 1").get(...keys)) return [];
      return stmt("select envelope_json from outbox_items where owner_scope=? and run_id=? and state in ('pending','unknown') order by sequence,item_index limit ?")
        .all(...keys, limit).map(row => JSON.parse(row.envelope_json));
    },
    applyResult(context, captureId, response) { return applyResult(context, captureId, response); },
    resumeDelivery(context, captureId) {
      const ctx = authorize(context, 'deliver'); check(uuid(captureId), 'invalid_capture_id');
      return transaction(() => {
        const row = stmt('select state,blocked_auth_epoch from outbox_items where owner_scope=? and run_id=? and capture_id=?').get(...keys, captureId);
        check(row?.state === 'blocked', 'capture_not_auth_blocked');
        // auth_epoch is issued by the trusted caller after actual system reauthentication;
        // it does not change the source credential_epoch or rewrite the saved envelope.
        check(ctx.auth_epoch > row.blocked_auth_epoch, 'reauthentication_required');
        stmt("update outbox_items set state='unknown',error_code='ack_unknown',blocked_auth_epoch=null where owner_scope=? and run_id=? and capture_id=?").run(...keys,captureId);
        return localStatus();
      });
    },
    async deliverOne(context, transport) {
      check(typeof transport === 'function', 'invalid_outbox_transport');
      const sent=authorize(context,'deliver'),claim=claimDelivery(context);
      if(!claim.token)return claim;
      let outcome;activeDispatch=true;
      try {
        let response;try{response=await transport(claim.capture);}catch{response=null;}
        const current=authorize(context,'deliver');
        check(current.auth_epoch>=sent.auth_epoch,'auth_epoch_regressed');
        response=snapshot(response??null);
        if(current.auth_epoch>sent.auth_epoch&&authCodes.includes(response?.error?.code)){
          shape(response,['receipt','error'],'invalid_capture_ack');shape(response.error,['code'],'invalid_capture_ack');
          check(response.receipt===null,'invalid_capture_ack');
          outcome={reason:'stale_auth_response'};
        }else{
          const applied=applyResult(context,claim.capture.capture_id,response,claim.token);
          outcome=applied.stale?{reason:'stale_delivery_response'}:{};
        }
      } finally { try { releaseFlight(claim.token); } finally { activeDispatch=false; } }
      const state=stmt('select state,attempt_count,legacy_attempts_unknown from outbox_items where owner_scope=? and run_id=? and capture_id=?').get(...keys,claim.capture.capture_id);
      return {kind:displayState(state),...outcome,progress:localStatus()};
    },
    status(context) { authorize(context); return localStatus(); },
    itemStates(context) {
      authorize(context);
      return stmt('select sequence,item_index,capture_id,item_ref,state,error_code,attempt_count,next_allowed_at,legacy_attempts_unknown from outbox_items where owner_scope=? and run_id=? order by sequence,item_index').all(...keys).map(row => ({...row,state:displayState(row)}));
    },
    close() { check(!activeDispatch,'delivery_in_flight'); db.close(); },
  };
  return api;
}
