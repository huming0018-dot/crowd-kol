import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
const require=createRequire(import.meta.url);
const {PGlite}=require(path.join(process.env.CROWD_TEST_TOOLS,'node_modules/@electric-sql/pglite'));
const db=new PGlite(),u='00000000-0000-4000-8000-000000000001';
const here=path.dirname(fileURLToPath(import.meta.url)),migrations=path.join(here,'../supabase/migrations');
try {
 await db.exec(`create role anon;create role authenticated;create role service_role;create schema auth;
 create table auth.users(id uuid primary key);
 create function auth.uid() returns uuid language sql as $$select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$;
 create function auth.role() returns text language sql as $$select current_setting('request.jwt.claim.role',true)$$;
 grant usage on schema auth to authenticated,service_role;grant execute on function auth.uid(),auth.role() to authenticated,service_role;`);
 for(const suffix of ['20261006145016_crowd_v4.sql','_crowd_v4_diagnostics.sql','_crowd_v4_navigation_diagnostics.sql','_crowd_v4_safety.sql','_crowd_v4_receipt_recovery.sql','_crowd_v4_task_scheduling.sql','_crowd_v4_observations.sql','_crowd_v4_relevance_aliases.sql','_crowd_v4_login_diagnostics.sql','_crowd_v4_navigation_recovery.sql'])await db.exec(fs.readFileSync(path.join(migrations,fs.readdirSync(migrations).find(n=>n.endsWith(suffix))),'utf8'));
 await db.exec(`alter table crowd_v4.tasks add column if not exists action_gap_seconds integer default 30,
 add column if not exists action_gap_milliseconds integer,
 add column if not exists daily_search_cap integer,add column if not exists daily_detail_cap integer,
 add column if not exists daily_comment_cap integer,add column if not exists session_action_limit integer default 20,
 add column if not exists session_window_seconds integer default 1200,
 add column if not exists comments_capture boolean default false,add column if not exists comment_repair_parents uuid[] default '{}';
 create table if not exists crowd_v4.test_task_owners(task_id bigint,user_id uuid);
 create table if not exists crowd_observation.recovery_controls(user_id uuid,task_id bigint,note_id text,enabled boolean,next_probe_at timestamptz);
 insert into auth.users values('${u}');
 insert into crowd_v4.participants(user_id,status,consent) values('${u}','approved','crowd-public-v4');
 insert into crowd_v4.tasks(id,source_key,query,anchor_terms,status,claimed_by,lease_until) overriding system value values(19,'pilot19','测试餐厅','["测试餐厅"]','leased','${u}',clock_timestamp()+interval '1 hour');
 insert into crowd_v4.safety(user_id) values('${u}');
 select set_config('request.jwt.claim.sub','${u}',false);`);
 await db.exec(fs.readFileSync(path.join(here,'fixtures/guard-20261014-before-idle-rest.sql'),'utf8'));
 const call=async(action='control',task=19)=>(await db.query('select crowd_observation.guard_internal($1,$2,null) r',[action,task])).rows[0].r;
 async function reset(extra=''){
  await db.exec(`update crowd_v4.policy set paused=false;
   update crowd_v4.participants set joined_at=clock_timestamp();
   update crowd_v4.tasks set lease_until=clock_timestamp()+interval '1 hour',session_action_limit=20;
   update crowd_v4.safety set day=(clock_timestamp() at time zone 'Asia/Shanghai')::date,
    counts='{"search":1,"detail":0,"comment":0,"scroll":0}',next_action=clock_timestamp()-interval '26 minutes',
    cooldown_until=clock_timestamp()-interval '1 second',cooldown_reason=null,session_count=1,
    session_started=clock_timestamp()-interval '27 minutes';${extra}`);
 }
 await reset();const old=await call('search');assert.equal(old.reason,'session_rest');assert(old.wait_ms>1799000,'reproduce needless full extra rest after 26 idle minutes');
 const patch=fs.readFileSync(path.join(migrations,'20261014014333_crowd_v4_idle_rest_deadline.sql'),'utf8');
 await db.exec(patch);
 await reset();const fixed=await call('search');assert.equal(fixed.reason,'session_rest');assert.equal(fixed.allowed,false);assert(fixed.wait_ms>239000&&fixed.wait_ms<=240000);assert.equal(fixed.counts.search,1);
 const poll=await call();assert.equal(poll.allowed,false);assert(poll.wait_ms<=fixed.wait_ms);assert.deepEqual(poll.counts,fixed.counts,'poll never adds source visits');
 await reset("update crowd_v4.safety set session_count=0,cooldown_reason='session_rest',cooldown_until=clock_timestamp()+interval '30 minutes',session_started=cooldown_until");
 const legacy=await call();assert.equal(legacy.reason,'session_rest');assert(legacy.wait_ms>239000&&legacy.wait_ms<=240000);assert.equal(legacy.counts.search,1);
 await db.exec("update crowd_v4.safety set next_action=clock_timestamp()-interval '31 minutes'");
 const expired=await call();assert.equal(expired.reason,null);assert.equal(expired.allowed,false,'expired wait is not source permission');assert.equal(expired.counts.search,1);
 assert.equal((await call('search')).allowed,true);assert.equal((await call()).counts.search,2,'source admitted exactly once after rest');
 for(const scenario of [
  "update crowd_v4.participants set joined_at=clock_timestamp()-interval '2 days'",
  "update crowd_v4.safety set counts='{"+"\"search\":20,\"detail\":0,\"comment\":0,\"scroll\":0}'",
  "update crowd_v4.safety set day=day-1",
  "update crowd_v4.safety set session_count=1",
  "update crowd_v4.safety set next_action=clock_timestamp()+interval '1 minute'",
 ]){
  await reset("update crowd_v4.safety set session_count=0,cooldown_reason='session_rest',cooldown_until=clock_timestamp()+interval '30 minutes';"+scenario);
  assert((await call()).wait_ms>1799000,'uncertain histories, action thresholds and future action clocks do not shorten active rest');
 }
 for(const reason of ['captcha','rate_limit']){
  await reset(`update crowd_v4.safety set session_count=0,cooldown_reason='${reason}',cooldown_until=clock_timestamp()+interval '1 hour'`);
  const row=await call();assert.equal(row.reason,reason);assert(row.wait_ms>3599000);
 }
 await reset("update crowd_v4.safety set session_count=20,next_action=clock_timestamp()-interval '1 second'");
 const countLimit=await call('scroll');assert.equal(countLimit.reason,'session_rest');assert(countLimit.wait_ms>1799000,'action-count rest remains full');
 await reset("update crowd_v4.safety set next_action=clock_timestamp()-interval '31 minutes',counts='{"+"\"search\":6,\"detail\":0,\"comment\":0,\"scroll\":0}'");
 assert.equal((await call('search')).reason,'action_budget');
 await reset("update crowd_v4.tasks set lease_until=clock_timestamp()-interval '1 second'");assert.equal((await call('search')).error,'lease_expired');
 await reset("update crowd_v4.policy set paused=true");assert.equal((await call('search')).reason,'global_pause');
 await reset();await assert.rejects(call('invalid'),/invalid_action/);
 const grants=(await db.query("select has_function_privilege('anon','public.crowd_v4_guard(text,bigint,text)','execute') anon,has_table_privilege('authenticated','crowd_v4.safety','update') edit,has_function_privilege('authenticated','public.crowd_v4_admin(text,jsonb)','execute') admin")).rows[0];assert.deepEqual(grants,{anon:false,edit:false,admin:false});
 await assert.rejects(db.exec(patch),/idle_rest_contract_changed/);await db.exec('rollback');
 console.log(JSON.stringify({pass:true,actual_production_guard_fixture:true,old_extra_rest_reproduced:true,idle_total_minutes:30,source_budget_unchanged:true,hard_cooldowns_unchanged:true,grants_unchanged:true,unknown_prior_histories_unchanged:true}));
}catch(error){console.error(error.message,error.where||'');process.exitCode=1;}finally{await db.close();}
