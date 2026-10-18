import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import crypto from 'node:crypto';
const require=createRequire(import.meta.url);
process.on('uncaughtException',error=>{console.error(error.message,error.where||'');process.exit(1);});
if(!process.env.CROWD_TEST_TOOLS)throw new Error('Set CROWD_TEST_TOOLS');
const {PGlite}=require(path.join(process.env.CROWD_TEST_TOOLS,'node_modules/@electric-sql/pglite'));
const db=new PGlite(),dir=fileURLToPath(new URL('../supabase/migrations/',import.meta.url));
const user='00000000-0000-4000-8000-000000000001',other='00000000-0000-4000-8000-000000000002';
const node='10000000-0000-4000-8000-000000000001';
await db.exec(`create role anon;create role authenticated;create role service_role;create schema auth;
create table auth.users(id uuid primary key);create function auth.uid() returns uuid language sql as $$select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$;
create function auth.role() returns text language sql as $$select nullif(current_setting('request.jwt.claim.role',true),'')$$;`);
for(const name of ['20261006145016_crowd_v4.sql','20261007051154_crowd_v4_diagnostics.sql','20261013135950_crowd_v4_participant_health_history.sql','20261011033423_crowd_machine.sql','20261013165118_crowd_distributed_nodes.sql'])await db.exec(fs.readFileSync(path.join(dir,name),'utf8'));
const sourceDefinitions=await db.query("select pg_get_functiondef('crowd_v4.participant_health_error(text)'::regprocedure) health_definition,pg_get_functiondef('public.crowd_v4_step_events(uuid,jsonb)'::regprocedure) events_definition");
const fixture=fs.readFileSync(new URL('./fixtures/node-wait-contract-20261014.sql',import.meta.url),'utf8');
await db.exec(fixture);
assert.deepEqual((await db.query("select pg_get_functiondef('crowd_v4.participant_health_error(text)'::regprocedure) health_definition,pg_get_functiondef('public.crowd_v4_step_events(uuid,jsonb)'::regprocedure) events_definition")).rows,sourceDefinitions.rows,'checked-in migrations already match deployed function definitions exactly');
await db.exec(`insert into auth.users values('${user}'),('${other}');insert into crowd_v4.participants(user_id,status,consent) values('${user}','approved','crowd-public-v4'),('${other}','approved','crowd-public-v4');`);
const identity=async id=>db.query("select set_config('request.jwt.claim.sub',$1,false)",[id||'']);
await identity(user);
await db.query("select public.crowd_v4_node_register($1,'{\"version\":\"4.2.65\",\"enabled\":false,\"login_state\":\"ready\"}')",[node]);
await db.query("select public.crowd_v4_diagnostics('enable',1)");

const migration=fs.readFileSync(path.join(dir,'20261015062750_crowd_v4_safe_ota_errors.sql'),'utf8');
const sensitiveFunctions=['public.crowd_v4_claim()','public.crowd_v4_submit(bigint,uuid,jsonb)','public.crowd_v4_finish(bigint,uuid)'];
const sourceBefore=(await db.query("select proname,md5(pg_get_functiondef(oid)) hash from pg_proc where pronamespace='public'::regnamespace and proname in ('crowd_v4_claim','crowd_v4_submit','crowd_v4_finish') order by proname")).rows;
await db.exec(migration);
let seq=0;
const report=async code=>(await db.query('select public.crowd_v4_step_events($1,$2::jsonb) result',[node,JSON.stringify([{event_id:crypto.randomUUID(),node_seq:++seq,run_id:null,step:'ota',status:'failed',at_ms:Date.now(),duration_ms:null,error_code:code}])])).rows[0].result;
const codes=["ota_network_dns", "ota_network_connect", "ota_network_timeout", "ota_network_tls", "ota_network_http", "ota_network_transfer", "ota_io_permission", "ota_io_missing", "ota_io_space", "ota_io_failed", "ota_package_tool_failed", "ota_service_failed", "ota_process_terminated", "ota_process_launch_failed", "ota_unknown_exit", "ota_signature_invalid", "ota_hash_mismatch", "ota_permission_change", "ota_replayed_release", "ota_recovery_required", "ota_handshake_mismatch", "ota_version_mismatch", "ota_busy", "ota_invalid_package", "ota_invalid_url", "ota_wrong_extension", "ota_unknown", "ota_io_failed"];

for(const code of codes){assert.equal((await report(code)).accepted.length,1);assert.equal((await db.query('select crowd_v4.participant_health_error($1) code',[code])).rows[0].code,'unexpected_error','non-OTA health scope remains closed');}
const timeline=(await db.query("select public.crowd_unified_monitor_rpc('crowd-owner-main','owner','node_events','{}') result")).rows[0].result;
assert.deepEqual(timeline.events.map(x=>x.error_code),codes,'Owner receives exact fixed codes');
await assert.rejects(db.query('select public.crowd_v4_step_events($1,$2::jsonb)',[node,JSON.stringify([{event_id:crypto.randomUUID(),node_seq:++seq,run_id:null,step:'session',status:'failed',at_ms:Date.now(),duration_ms:null,error_code:codes[0]}])]),/invalid_events/);
for(const bad of ['PRIVATE_SECRET','ota_network_dns\n',{cookie:'PRIVATE_SECRET'},true,null]){if(bad!==null)await assert.rejects(report(bad),/invalid_events/);}
const ota={version:'4.2.69',enabled:true,phase:'idle',error:null,task_id:null,queued:0,rejected:0,page_kind:'missing',tab_status:'missing',document:'unknown',gate:null,links:0,search_note_links:0,body_chars:0,visible:false,ota_poll_status:'error'};
const pollCodes=["ota_network_dns", "ota_network_connect", "ota_network_timeout", "ota_network_tls", "ota_network_http", "ota_network_transfer", "ota_io_permission", "ota_io_missing", "ota_io_space", "ota_io_failed", "ota_package_tool_failed", "ota_service_failed", "ota_process_terminated", "ota_process_launch_failed", "ota_unknown_exit", "too_large", "unsafe_archive", "invalid_package", "lock_failed", "swap_failed", "process_check_failed", "handshake_mismatch", "version_mismatch"];

for(const code of pollCodes){await db.query("select public.crowd_v4_diagnostics('report',1,$1::jsonb)",[JSON.stringify({...ota,ota_poll_error:code})]);const r=(await db.query("select public.crowd_participant_health_rpc('crowd-owner-main','owner','{}') result")).rows[0].result;assert.equal(r.participants[0].ota_poll_error,code);}
for(const bad of ['PRIVATE_SECRET',{},true])await assert.rejects(db.query("select public.crowd_v4_diagnostics('report',1,$1::jsonb)",[JSON.stringify({...ota,ota_poll_error:bad})]),/invalid_diagnostics/);
assert.deepEqual((await db.query("select proname,md5(pg_get_functiondef(oid)) hash from pg_proc where pronamespace='public'::regnamespace and proname in ('crowd_v4_claim','crowd_v4_submit','crowd_v4_finish') order by proname")).rows,sourceBefore,'source/receipt functions unchanged');
await assert.rejects(db.exec(migration),/ota_diagnostic_anchor_mismatch/,'reapply refuses changed anchor instead of broad replacement');
await db.close();console.log('PASS OTA error SQL: exact event/projection roundtrip, non-OTA exclusion, malformed rejection, source functions unchanged, drift guard');
