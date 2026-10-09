import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { randomUUID } from 'node:crypto';
import { receiveCapture } from '../capture-receiver.mjs';
import { normalizeCapture } from '../capture-contract.mjs';

const { PGlite } = createRequire(import.meta.url)(path.join(process.env.CROWD_TEST_TOOLS, 'node_modules/@electric-sql/pglite'));
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'crowd-capture-receiver-'));
let db = new PGlite(dir), cases = 0;
const principal = { owner_scope: 'owner-1', actor_ref: 'worker-1' };
const bindingKeys = ['owner_scope','actor_ref','session_ref','task_ref','run_id','lease_epoch','credential_epoch','admission_id','target_ref','source_kind'];
const requested = ['title','body','published_at','metrics.likes'];
const unavailable = status => ({ value: null, status });
const fixture = () => ({
  contract_version: 1, capture_id: randomUUID(), ...principal, session_ref: 'session-1',
  task_ref: { namespace: 'legacy_v4', legacy_task_id: '9007199254740993' },
  run_id: randomUUID(), lease_epoch: 1, credential_epoch: 1, admission_id: randomUUID(),
  target_ref: { platform: 'xiaohongshu', kind: 'content', id: 'opaque-content-1' },
  source_kind: 'platform_api', captured_at: new Date().toISOString(), payload_schema: 'content.v1',
  payload: {
    platform: 'xiaohongshu', content_id: 'opaque-content-1', creator_id: 'author-1',
    canonical_url: 'https://www.xiaohongshu.com/explore/opaque-content-1', content_type: 'note',
    title: { value: '隔离测试标题', status: 'observed' }, title_origin: 'original',
    body: { value: '仅供离线测试的合成内容。', status: 'observed' }, published_at: unavailable('not_visible'),
    metrics: Object.fromEntries(['likes','collects','comments','shares','views'].map(key => [key,
      key === 'likes' ? { value: 0, status: 'observed', precision: 'exact', raw_display: null }
        : { ...unavailable('not_requested'), precision: null, raw_display: null }])),
  }, completeness: { status: 'partial', scope: 'single_content', reason: 'field_unavailable' },
});
async function admit(value, { issuedSeconds = -60, untilSeconds = 3600, revoked = false, requestedFields = requested } = {}) {
  const binding = Object.fromEntries(bindingKeys.map(key => [key, value[key]]));
  await db.query(`insert into capture_receiver.admissions
    (owner_scope,admission_id,actor_ref,binding,parser_version,normalization_version,requested_fields,issued_at,accept_until,revoked)
    values($1,$2,$3,$4,'self-parser-1','capture-v1',$5,clock_timestamp()+($6 * interval '1 second'),clock_timestamp()+($7 * interval '1 second'),$8)`,
  [value.owner_scope, value.admission_id, value.actor_ref, binding, requestedFields, issuedSeconds, untilSeconds, revoked]);
}
const submit = value => receiveCapture(db, principal, value);
async function rejected(value, code, caller = principal) {
  assert.deepEqual(await receiveCapture(db, caller, value), { receipt: null, error: { code } }); cases++;
}
const rowCount = async () => (await db.query('select count(*)::int n from capture_receiver.captures')).rows[0].n;

try {
  await db.exec('create role anon; create role authenticated;');
  await db.exec(fs.readFileSync(new URL('./fixtures/capture-receiver.sql', import.meta.url), 'utf8'));
  await db.query('insert into capture_receiver.actors values($1,$2,true)', [principal.owner_scope, principal.actor_ref]);
  const first = fixture(); await admit(first);
  const ack = await submit(first);
  assert.equal(ack.error, null, JSON.stringify(ack));
  assert.equal(ack.receipt.status, 'received'); assert.equal(ack.receipt.verdict, 'stored_unreviewed');
  assert.equal(ack.receipt.envelope_hash, (await normalizeCapture(first)).envelope_hash);
  assert.ok(new Date(ack.receipt.received_at).getTime() >= new Date(first.captured_at).getTime());
  assert.equal(await rowCount(), 1);
  const record = (await db.query('select envelope,parser_version,normalization_version,requested_fields,run_id,lease_epoch,credential_epoch,received_at from capture_receiver.captures')).rows[0];
  assert.equal(record.envelope.payload.metrics.likes.value, 0);
  assert.equal(record.envelope.payload.published_at.value, null);
  assert.deepEqual(record.requested_fields, requested);
  assert.equal(record.parser_version, 'self-parser-1'); assert.equal(record.normalization_version, 'capture-v1');
  assert.equal(record.run_id, first.run_id); assert.equal(record.lease_epoch, 1); assert.equal(record.credential_epoch, 1);
  assert.equal(record.received_at.toISOString(), ack.receipt.received_at); cases++;

  // Lost ACK and repeated calls return the original receipt without source access.
  const simultaneous = await Promise.all(Array.from({length: 8}, () => submit(structuredClone(first))));
  for (const result of simultaneous) assert.deepEqual(result, ack);
  assert.equal(await rowCount(), 1); cases++;
  const distinct = fixture(); await admit(distinct);
  const duplicates = await Promise.all(Array.from({length: 8}, () => submit(structuredClone(distinct))));
  for (const result of duplicates) assert.deepEqual(result, duplicates[0]);
  assert.equal(duplicates[0].error, null); assert.equal(await rowCount(), 2); cases++;
  const changed = structuredClone(first); changed.payload.body.value = '不同正文'; await rejected(changed, 'request_reused');
  const changedAdmission = structuredClone(first); changedAdmission.admission_id = randomUUID(); await admit(changedAdmission);
  await rejected(changedAdmission, 'request_reused');
  const reusedAdmission = structuredClone(first); reusedAdmission.capture_id = randomUUID(); await rejected(reusedAdmission, 'admission_used');
  assert.equal(await rowCount(), 2);

  const competing = fixture(); await admit(competing);
  const competingChanged = structuredClone(competing); competingChanged.admission_id = randomUUID(); competingChanged.payload.body.value = '另一份'; await admit(competingChanged);
  const race = await Promise.all([submit(competing), submit(competingChanged)]);
  assert.equal(race.filter(result => result.receipt).length, 1);
  assert.deepEqual(race.find(result => result.error).error, { code: 'request_reused' }); cases++;

  const otherOwner = { owner_scope: 'owner-2', actor_ref: 'worker-2' };
  await db.query('insert into capture_receiver.actors values($1,$2,true)', [otherOwner.owner_scope, otherOwner.actor_ref]);
  await rejected(first, 'principal_mismatch', otherOwner);
  const otherActor = { owner_scope: 'owner-1', actor_ref: 'worker-2' };
  await db.query('insert into capture_receiver.actors values($1,$2,true)', [otherActor.owner_scope, otherActor.actor_ref]);
  await rejected(first, 'principal_mismatch', otherActor);
  const forgedActor = { ...structuredClone(first), ...otherActor };
  await rejected(forgedActor, 'principal_mismatch', otherActor);
  await rejected(first, 'principal_required', null);
  const absentActor = { owner_scope: 'owner-1', actor_ref: 'absent-actor' };
  await rejected({ ...fixture(), ...absentActor }, 'actor_not_authorized', absentActor);
  const absentAdmission = fixture(); await rejected(absentAdmission, 'admission_missing');

  // Same opaque content/capture ID in a different tenant is not another tenant's ACK.
  const separate = { ...structuredClone(first), ...otherOwner, admission_id: randomUUID(), run_id: randomUUID() };
  await admit(separate);
  const ownAck = await receiveCapture(db, otherOwner, separate);
  assert.equal(ownAck.error, null); assert.notEqual(ownAck.receipt.envelope_hash, ack.receipt.envelope_hash); cases++;

  const expired = fixture(); await admit(expired, { untilSeconds: -1 });
  // Backdating does not reopen a server-expired admission.
  expired.captured_at = new Date(Date.now() - 30000).toISOString(); await rejected(expired, 'admission_expired');
  const futureIssued = fixture(); await admit(futureIssued, { issuedSeconds: 60 }); await rejected(futureIssued, 'admission_expired');
  const futureCapture = fixture(); await admit(futureCapture); futureCapture.captured_at = '2099-01-01T00:00:00.000Z'; await rejected(futureCapture, 'capture_time_invalid');
  const beforeIssued = fixture(); await admit(beforeIssued); beforeIssued.captured_at = '2000-01-01T00:00:00.000Z'; await rejected(beforeIssued, 'capture_time_invalid');
  const revoked = fixture(); await admit(revoked, { revoked: true }); await rejected(revoked, 'admission_revoked');
  const quick = fixture(); await admit(quick, { untilSeconds: 1 });
  const quickAck = await submit(quick); assert.equal(quickAck.error, null);
  await new Promise(resolve => setTimeout(resolve, 1100));
  assert.deepEqual(await submit(quick), quickAck); cases++;
  await db.query('update capture_receiver.admissions set revoked=true where owner_scope=$1 and admission_id=$2', [principal.owner_scope, first.admission_id]);
  assert.deepEqual(await submit(first), ack); cases++;
  const afterRevocation = structuredClone(first); afterRevocation.capture_id = randomUUID(); await rejected(afterRevocation, 'admission_revoked');
  await db.query('update capture_receiver.actors set enabled=false where owner_scope=$1 and actor_ref=$2', [principal.owner_scope, principal.actor_ref]);
  await rejected(first, 'actor_not_authorized');
  await db.query('update capture_receiver.actors set enabled=true where owner_scope=$1 and actor_ref=$2', [principal.owner_scope, principal.actor_ref]);
  assert.deepEqual(await submit(first), ack);
  assert.equal(Object.hasOwn(ack.receipt, 'payload'), false); cases++;

  const bound = fixture(); await admit(bound);
  for (const [key, value] of [['session_ref','other-session'], ['lease_epoch',2], ['credential_epoch',2], ['run_id',randomUUID()], ['source_kind','rendered_public_dom']]) {
    const wrong = structuredClone(bound); wrong[key] = value; await rejected(wrong, 'capture_binding_mismatch');
  }
  const missingRequested = structuredClone(bound); missingRequested.payload.body = unavailable('not_requested');
  await rejected(missingRequested, 'requested_fields_mismatch');
  const extraField = structuredClone(bound); extraField.payload.metrics.shares = { value: 1, status: 'observed', precision: 'exact', raw_display: null };
  await rejected(extraField, 'requested_fields_mismatch');
  const falseComplete = structuredClone(bound); falseComplete.payload.published_at = unavailable('not_requested'); falseComplete.completeness = { status: 'complete', scope: 'single_content', reason: null };
  await rejected(falseComplete, 'requested_fields_mismatch');
  const allHidden = structuredClone(bound); allHidden.payload.body = unavailable('not_visible');
  assert.equal((await submit(allHidden)).receipt.status, 'received', 'explicit partial observation is not fabricated completeness'); cases++;
  const badManifest = fixture(); await admit(badManifest, { requestedFields: ['body','body'] }); await rejected(badManifest, 'invalid_admission');

  // A legitimate old epoch stays on its original run; this receiver owns no progress table.
  const old = fixture(), newer = fixture(); newer.lease_epoch = 2; newer.credential_epoch = 2;
  await admit(old); await admit(newer);
  assert.equal((await submit(newer)).receipt.lease_epoch, 2);
  assert.equal((await submit(old)).receipt.lease_epoch, 1);
  const epochs = (await db.query('select run_id,lease_epoch from capture_receiver.captures where run_id in ($1,$2)', [old.run_id, newer.run_id])).rows;
  assert.equal(epochs.find(row => row.run_id === old.run_id).lease_epoch, 1);
  assert.equal(epochs.find(row => row.run_id === newer.run_id).lease_epoch, 2); cases++;

  // Force a COMMIT-time failure, after the envelope and receipt INSERT has executed.
  const rollback = fixture(); await admit(rollback);
  const beforeRollback = await rowCount();
  await db.exec(`create function capture_receiver.test_commit_failure() returns trigger language plpgsql security invoker as $$
    begin raise exception 'synthetic_commit_failure'; end; $$;
    create constraint trigger test_commit_failure after insert on capture_receiver.captures
    deferrable initially deferred for each row execute function capture_receiver.test_commit_failure();`);
  await rejected(rollback, 'receiver_unavailable');
  assert.equal(await rowCount(), beforeRollback);
  await db.exec('drop trigger test_commit_failure on capture_receiver.captures; drop function capture_receiver.test_commit_failure();');
  assert.equal((await submit(rollback)).receipt.status, 'received'); cases++;

  await assert.rejects(db.query('update capture_receiver.captures set receipt=$1 where capture_id=$2', [{ status: 'received' }, first.capture_id]), /immutable_capture_record/);
  await assert.rejects(db.query("update capture_receiver.admissions set parser_version='tampered' where admission_id=$1", [first.admission_id]), /immutable_capture_record/); cases++;
  const permissions = (await db.query(`select rolname,
    has_schema_privilege(rolname,'capture_receiver','usage') as schema_access,
    has_table_privilege(rolname,'capture_receiver.captures','select') as table_access,
    has_function_privilege(rolname,'capture_receiver.freeze_record()','execute') as function_access
    from pg_roles where rolname in ('anon','authenticated') order by rolname`)).rows;
  assert.equal(permissions.length, 2);
  for (const row of permissions) assert.deepEqual([row.schema_access,row.table_access,row.function_access], [false,false,false]);
  assert.equal((await db.query("select count(*)::int n from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='capture_receiver' and c.relkind='r' and c.relrowsecurity")).rows[0].n, 3);
  await db.exec('set role authenticated');
  await assert.rejects(db.query('select * from capture_receiver.captures'), /permission denied/);
  await db.exec('reset role'); cases++;

  // Disk close/reopen is a new database process state, not an in-memory receipt cache.
  const beforeClose = await rowCount(); await db.close(); db = new PGlite(dir);
  assert.deepEqual(await submit(first), ack);
  assert.equal(await rowCount(), beforeClose);
  const persisted = (await db.query('select receipt,received_at,envelope from capture_receiver.captures where owner_scope=$1 and capture_id=$2', [principal.owner_scope, first.capture_id])).rows[0];
  assert.deepEqual(persisted.receipt, ack.receipt); assert.equal(persisted.received_at.toISOString(), ack.receipt.received_at);
  assert.deepEqual(persisted.envelope, await normalizeCapture(first)); cases++;
  console.log(`PASS capture receiver SQL: ${cases} scenario groups; durable ACK, restart, atomic rollback, binding, source, revocation, exact replay`);
  console.log('BOUNDARY: concurrent promises run through one PGlite connection; multi-session PostgreSQL contention and production auth NOT VERIFIED');
} finally {
  await db.close(); fs.rmSync(dir, { recursive: true, force: true });
}
