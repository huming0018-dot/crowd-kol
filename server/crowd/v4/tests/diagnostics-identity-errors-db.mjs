import assert from 'node:assert/strict';import fs from 'node:fs';import path from 'node:path';import {createRequire}from'node:module';import{fileURLToPath}from'node:url';
const here=path.dirname(fileURLToPath(import.meta.url)),require=createRequire(import.meta.url);
if(!process.env.CROWD_TEST_TOOLS)throw Error('CROWD_TEST_TOOLS required');
const{PGlite}=require(path.join(process.env.CROWD_TEST_TOOLS,'node_modules/@electric-sql/pglite'));
const{reportSnapshot}=require(path.resolve(here,'../../../../../crawler-extension/v4/tests/diagnostics-identity-errors.cjs'));
const db=new PGlite(),uid='00000000-0000-4000-8000-000000000001';
await db.exec(`create role anon;create role authenticated;create schema auth;create schema crowd_v4;
create function auth.uid() returns uuid language sql as $$select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$;
create table crowd_v4.participants(user_id uuid primary key,status text,consent text);
insert into crowd_v4.participants values('${uid}','approved','crowd-public-v4');`);
await db.exec(fs.readFileSync(path.join(here,'../supabase/migrations/20261007051154_crowd_v4_diagnostics.sql'),'utf8'));
await db.exec("alter table crowd_v4.diagnostics drop constraint diagnostics_state_check;alter table crowd_v4.diagnostics add constraint diagnostics_state_check check(state is null or(jsonb_typeof(state)='object' and octet_length(state::text)<=8192));");
const baseline=fs.readFileSync(path.join(here,'fixtures/diagnostics-identity-before.sql'),'utf8');await db.exec(baseline);
async function call(action,state=null,revision=1,user=uid){await db.query("select set_config('request.jwt.claim.sub',$1,false)",[user]);return(await db.query('select public.crowd_v4_diagnostics($1,$2,$3::jsonb) result',[action,revision,state===null?null:JSON.stringify(state)])).rows[0].result;}
async function def(){return(await db.query("select pg_get_functiondef('public.crowd_v4_diagnostics(text,bigint,jsonb)'::regprocedure) d")).rows[0].d;}
async function meta(){return(await db.query("select oid,proacl::text acl,prosecdef,proconfig from pg_proc where oid='public.crowd_v4_diagnostics(text,bigint,jsonb)'::regprocedure")).rows[0];}
await call('enable');const before=await def(),metadata=await meta();const old="or (p_state->>'error' is not null and p_state->>'error' not in ('page_timeout'",add="or (p_state->>'error' is not null and p_state->>'error' not in ('identity_verification_required','platform_identity_changed','page_timeout'";
const normal=await reportSnapshot('participant-background.js','login_required');await call('report',normal);
for(const profile of ['participant-background.js','background.js'])for(const error of ['identity_verification_required','platform_identity_changed'])await assert.rejects(call('report',await reportSnapshot(profile,error)),/invalid_diagnostics/);
const patch=fs.readFileSync(path.join(here,'../diagnostics_identity_errors.sql'),'utf8');await db.exec(patch);const after=await def();assert.equal(after,before.replace(old,add));assert.deepEqual(await meta(),metadata);
let accepted=0,rejected=0;
for(const profile of ['participant-background.js','background.js'])for(const error of ['identity_verification_required','platform_identity_changed','login_required','captcha','cancelled',null]){const snap=await reportSnapshot(profile,error);await call('report',snap);assert.deepEqual((await db.query('select state from crowd_v4.diagnostics where user_id=$1',[uid])).rows[0].state,snap);accepted++;}
for(const extra of [{error:'unknown_private'},{error:{}},{error:true},{cookie:'SYNTHETIC'},{version:'3.5.2'},{version:'4.2.73;select'},{queued:-1},{queued:100000},{trace:[{stage:'idle',cookie:'SYNTHETIC'}]}]){await assert.rejects(call('report',{...normal,...extra}),/invalid_diagnostics/);rejected++;}
await assert.rejects(call('report',normal,1,''),/login_required/);await call('disable',null,2);await assert.rejects(call('report',normal),/stale_diagnostics/);await assert.rejects(db.exec(patch),/diagnostics_identity_contract_changed/);await db.exec('rollback');assert.equal(await def(),after);
// A changed/missing anchor must fail before any function mutation.
await db.exec(before.replace(old,old.replace('page_timeout','changed_anchor')));const drift=await def();await assert.rejects(db.exec(patch),/diagnostics_identity_contract_changed/);await db.exec('rollback');assert.equal(await def(),drift);
await db.close();console.log(JSON.stringify({pass:true,baseline_new_errors_rejected:4,accepted,rejected,actual_reporters:2,only_two_error_codes_changed:true,version_guard_byte_exact:true,oid_acl_security_unchanged:true,repeat_drift_fail_closed:true,production_requests:0}));
