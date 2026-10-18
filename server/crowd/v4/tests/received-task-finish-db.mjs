import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {randomUUID} from 'node:crypto';
if(!process.env.CROWD_TEST_TOOLS||!process.env.CROWD_FINISH_BASELINE)throw Error('Set CROWD_TEST_TOOLS and CROWD_FINISH_BASELINE');
const {PGlite}=createRequire(import.meta.url)(path.join(process.env.CROWD_TEST_TOOLS,'node_modules/@electric-sql/pglite'));
const db=new PGlite(),users=[randomUUID(),randomUUID()];
const migrations=new URL('../supabase/migrations/',import.meta.url);
const migration=fs.readFileSync(new URL('20261014031206_crowd_v4_received_task_finish.sql',migrations),'utf8');
let cases=0;
try{
 await db.exec(`create role anon;create role authenticated;create role service_role;create schema auth;create table auth.users(id uuid primary key);
 create function auth.uid() returns uuid language sql as $$select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$;
 create function auth.role() returns text language sql as $$select current_setting('request.jwt.claim.role',true)$$;
 grant usage on schema auth to authenticated;grant execute on function auth.uid(),auth.role() to authenticated;`);
 for(const name of ['20261006145016_crowd_v4.sql','20261008033028_crowd_v4_task_scheduling.sql'])await db.exec(fs.readFileSync(new URL(name,migrations),'utf8'));
 // These three columns exactly match the live schema; no source or auth adapters are mocked.
 await db.exec("alter table crowd_v4.tasks add comments_capture boolean not null default false,add structured_capture boolean not null default false,add comment_repair_parents uuid[] not null default '{}';");
 await db.exec(fs.readFileSync(process.env.CROWD_FINISH_BASELINE,'utf8'));
 for(const user of users){await db.query('insert into auth.users values($1)',[user]);await db.query("insert into crowd_v4.participants(user_id,status,consent,quota_day) values($1,'approved','crowd-public-v4',2)",[user]);}
 const newTask=async()=> (await db.query("insert into crowd_v4.tasks(source_key,query,anchor_terms,target,received,status,claimed_by,lease_token,lease_until,lease_start_received) values($1,'测试任务','[\"测试任务\"]',2,2,'leased',$2,$3,now()-interval '1 minute',0) returning *",[randomUUID(),users[0],randomUUID()])).rows[0];
 const finish=async(task,user=users[0])=>{
  await db.query("select set_config('request.jwt.claim.sub',$1,false)",[user]);await db.exec('set role authenticated');
  try{return (await db.query('select public.crowd_v4_finish($1,$2) result',[task.id,task.lease_token])).rows[0].result;}finally{await db.exec('reset role');}
 };
 const row=async id=>(await db.query('select * from crowd_v4.tasks where id=$1',[id])).rows[0];
 const snapshot=async()=>(await db.query("select (select jsonb_agg(to_jsonb(t) order by id) from crowd_v4.tasks t) tasks,(select jsonb_agg(to_jsonb(p) order by id) from crowd_v4.proofs p) proofs,(select jsonb_agg(to_jsonb(r) order by request) from crowd_v4.receipts r) receipts,(select jsonb_agg(to_jsonb(p) order by user_id) from crowd_v4.participants p) participants")).rows[0];
 const definitions=async()=>(await db.query("select oid::regprocedure::text name,pg_get_functiondef(oid) definition,proacl::text acl from pg_proc where pronamespace in ('public'::regnamespace,'crowd_v4'::regnamespace) order by name")).rows;
 const full=await newTask();
 await db.query("insert into crowd_v4.proofs(note_id,user_id,task_id,record) values($1,$2,$3,'{\"retained\":true}')",['a'.repeat(24),users[0],full.id]);
 await db.query("insert into crowd_v4.receipts(user_id,request,payload,result) values($1,$2,$3,'{\"gate\":\"received\",\"inserted\":true}')",[users[0],randomUUID(),JSON.stringify({task:full.id,record:{retained:true}})]);
 assert.deepEqual(await finish(full),{error:'lease_lost'},'live defect reproduced');cases++;
 const before=await snapshot(),beforeDefinitions=await definitions();await db.exec(migration);
 assert.deepEqual(await snapshot(),before,'deployment itself does not finish tasks or mutate data');
 const afterDefinitions=await definitions();
 assert.deepEqual(afterDefinitions.filter(x=>x.name!=='crowd_v4_finish(bigint,uuid)'),beforeDefinitions.filter(x=>x.name!=='crowd_v4_finish(bigint,uuid)'));
 assert.deepEqual(afterDefinitions.map(x=>[x.name,x.acl]),beforeDefinitions.map(x=>[x.name,x.acl]),'ACLs unchanged');
 const completed=await finish(full);assert.equal(completed.status,'complete');assert.equal(completed.received,2);
 const afterRow=await row(full.id);for(const key of ['claimed_by','lease_token','lease_until','target','received','comments_capture','structured_capture','comment_repair_parents'])assert.deepEqual(afterRow[key],full[key],key);
 assert.deepEqual(await finish(full),completed,'lost response replays exactly');assert.deepEqual(await row(full.id),afterRow);cases++;
 const after=await snapshot();for(const key of ['proofs','receipts','participants'])assert.deepEqual(after[key],before[key],key+' unchanged');
 const rejects=[
  ['not full','received=1'],['null deadline','lease_until=null'],['comments','comments_capture=true'],['structured','structured_capture=true'],
  ['repair',"comment_repair_parents=array[gen_random_uuid()]"],['null repair entry',"comment_repair_parents=array[null::uuid]"],
  ['changed token','lease_token=gen_random_uuid()']
 ];
 for(const [name,update] of rejects){const task=await newTask();await db.exec('update crowd_v4.tasks set '+update+' where id='+task.id);const original=await row(task.id);assert.deepEqual(await finish(task),{error:'lease_lost'},name);assert.deepEqual(await row(task.id),original,name+' stays unchanged');cases++;}
 for(const [name,change,user] of [['wrong owner',null,users[1]],['null token',{lease_token:null},users[0]],['missing task',{id:99999},users[0]]]){const task=await newTask();assert.deepEqual(await finish({...task,...change},user),{error:'lease_lost'},name);cases++;}
 const live=await newTask();await db.exec("update crowd_v4.tasks set received=1,comments_capture=true,lease_until=now()+interval '1 minute' where id="+live.id);assert.equal((await finish(live)).status,'open','ordinary live partial task behavior unchanged');cases++;
 const revoked=await newTask();await db.query("update crowd_v4.participants set status='suspended' where user_id=$1",[users[0]]);await assert.rejects(finish(revoked),/approval_required/);await db.query("update crowd_v4.participants set status='approved' where user_id=$1",[users[0]]);cases++;
 await assert.rejects(finish(revoked,''),/login_required/);cases++;
 const stolen=await newTask();await db.query("update crowd_v4.tasks set claimed_by=$1,lease_token=gen_random_uuid() where id=$2",[users[1],stolen.id]);assert.deepEqual(await finish(stolen),{error:'lease_lost'},'reclaimed task rejects original owner and token');cases++;
 const acl=(await db.query("select has_function_privilege('anon','public.crowd_v4_finish(bigint,uuid)','execute') anon,has_function_privilege('authenticated','public.crowd_v4_finish(bigint,uuid)','execute') participant,has_table_privilege('authenticated','crowd_v4.tasks','update') direct_update")).rows[0];assert.deepEqual(acl,{anon:false,participant:true,direct_update:false});
 await assert.rejects(db.exec(migration),/received_finish_anchor_mismatch/);await db.exec('rollback');cases++;
 console.log(JSON.stringify({status:'PASS',cases,scope:'isolated PGlite, deployed finish baseline, no real tasks changed',preserved:['ACL','other functions','original owner and lease','proofs','receipts','quota'],limitations:['PGlite serializes queries; no real concurrent transaction test']}));
}finally{await db.close();}
