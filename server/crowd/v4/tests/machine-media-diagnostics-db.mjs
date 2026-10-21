import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import fs from 'node:fs';
import {fileURLToPath, pathToFileURL} from 'node:url';
const require = createRequire(import.meta.url);
const {PGlite} = require(process.env.CROWD_TEST_TOOLS + '/node_modules/@electric-sql/pglite');
const root = fileURLToPath(new URL('..', import.meta.url)).replace(/\/$/, '');
const migrations = root + '/supabase/migrations/';
const files = fs.readdirSync(migrations).filter(name => name.endsWith('_central_steps_xhs_media_finite_diagnostics.sql'));
assert.equal(files.length, 1, 'exact deployed migration required');
const codes = ['xhs_manager_changed','xhs_manager_import_changed','xhs_media_budget_exhausted','xhs_media_context_changed','xhs_media_guard_failed','xhs_media_http_rejected','xhs_media_http_status','xhs_media_length_mismatch','xhs_media_output_exists','xhs_media_output_invalid','xhs_media_size_invalid','xhs_media_stopped','xhs_media_stream_invalid','xhs_media_timeout','xhs_media_transport_failed','xhs_media_transport_timeout','xhs_media_type_invalid','xhs_media_unknown_failure'];
const {machineSteps} = await import(pathToFileURL(root + '/supabase/functions/crowd-machine/machine_steps.mjs'));
const db = new PGlite();
try {
  await db.exec('create role anon; create role authenticated; create role service_role;');
  for (const name of ['20261011053338_crowd_machine_original_content_binding.sql', '20261015062743_machine_step_events.sql']) await db.exec(fs.readFileSync(migrations + name, 'utf8'));
  // Bootstrap the prior finite-diagnostic function; this test targets the new CAS migration, not historical migration sequencing.
  const prior = fs.readFileSync(migrations + '20261016011137_central_steps_weibo_finite_diagnostics_68.sql', 'utf8');
  const start = prior.indexOf('CREATE OR REPLACE FUNCTION public.crowd_machine_steps_rpc(');
  const end = prior.indexOf('end $function$', start);
  assert(start >= 0 && end > start);
  await db.exec(prior.slice(start, end + 'end $function$'.length) + ';');
  const worker = '10000000-0000-4000-8000-000000000001', run = '20000000-0000-4000-8000-000000000001', task = '40000000-0000-4000-8000-000000000001', child = '50000000-0000-4000-8000-000000000001';
  await db.query("insert into crowd_machine.workers(worker_id,owner_scope,token_hash,name,platforms,enabled,expires_at) values($1,'crowd-owner-main',$2,'isolated','[]',true,now()+interval '1 day')", [worker, 'a'.repeat(64)]);
  await db.query("insert into crowd_machine.tasks(task_id,owner_scope,idempotency_key,request_hash,proposal) values($1,'crowd-owner-main','media-diagnostics',$2,'{}')", [task, 'b'.repeat(64)]);
  await db.query("insert into crowd_machine.children(child_id,task_id,platform,plan,state) values($1,$2,'xhs','{}','completed')", [child, task]);
  await db.query('insert into crowd_machine.claims(worker_id,claim_id,run_id,lease_epoch,child_id) values($1,$2,$3,1,$4)', [worker, child, run, child]);
  let rpcCalls = 0;
  const backend = {rpc: async (_, payload) => {rpcCalls++; try {return {data: (await db.query('select public.crowd_machine_steps_rpc($1,$2,$3,$4,$5::jsonb) result', [payload.p_owner_scope, payload.p_actor_kind, payload.p_worker_hash, payload.p_action, JSON.stringify(payload.p_payload)])).rows[0].result};} catch (error) {return {error};}}};
  const event = (code, sequence) => ({event_id: '30000000-0000-4000-8000-' + String(sequence).padStart(12, '0'), run_id: run, lease_epoch: 1, sequence, observed_at_ms: Date.now(), phase: 'importing', error_code: code, exit_code: 74});
  const report = events => machineSteps('step_events', {events}, backend, 'worker', 'a'.repeat(64));
  const count = async () => Number((await db.query('select count(*) n from crowd_machine.step_events')).rows[0].n);
  await assert.rejects(report([event(codes[0], 1)]), /invalid_step_events/);
  assert.equal(await count(), 0);
  await db.exec(fs.readFileSync(migrations + files[0], 'utf8'));
  for (const [index, code] of codes.entries()) {const e = event(code, index + 1); assert.deepEqual((await report([e])).event_ids, [e.event_id]);}
  assert.equal(await count(), 18);
  for (const changed of [{error_code: 'xhs_media_arbitrary'}, {error_code: 'https://secret.invalid'}, {exit_code: true}, {exit_code: 1.5}, {exit_code: 256}, {http_status: 403}, {stage: 'stream'}, {phase: 'source_step'}]) {
    const callsBefore = rpcCalls;
    await assert.rejects(report([{...event(codes[0], 40), ...changed}]), /invalid_step_events/);
    assert.equal(rpcCalls, callsBefore);
  }
  await assert.rejects(db.query("select public.crowd_machine_steps_rpc('crowd-owner-main','worker',$1,'step_events',$2::jsonb)", ['a'.repeat(64), JSON.stringify({events: [event(codes[0], 40), event('xhs_media_arbitrary', 41)]})]), /invalid_step_events/);
  assert.equal(await count(), 18, 'invalid batch must roll back its earlier valid event');
  await assert.rejects(db.exec(fs.readFileSync(migrations + files[0], 'utf8')), /machine_steps_baseline_changed/);
  console.log(JSON.stringify({gate: 'PASS_MEDIA_FINITE_EDGE_POSTGRES', finite_codes: 18, invalid_boundaries: 8, transaction_rollback: true, source_calls: 0}));
} finally {await db.close();}
