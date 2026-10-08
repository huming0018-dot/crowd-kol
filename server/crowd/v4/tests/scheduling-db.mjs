import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {randomUUID} from 'node:crypto';
const {PGlite}=createRequire(import.meta.url)(path.join(process.env.CROWD_TEST_TOOLS,'node_modules/@electric-sql/pglite'));
const db=new PGlite(),users=[randomUUID(),randomUUID()];
try {
 await db.exec(`create role anon;create role authenticated;create role service_role;create schema auth;create table auth.users(id uuid primary key);
 create function auth.uid() returns uuid language sql as $$select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$;
 create function auth.role() returns text language sql as $$select current_setting('request.jwt.claim.role',true)$$;
 grant usage on schema auth to authenticated;grant execute on function auth.uid(),auth.role() to authenticated;`);
 const dir=new URL('../supabase/migrations/',import.meta.url);
 for(const suffix of ['20261006145016_crowd_v4.sql','_crowd_v4_diagnostics.sql','_crowd_v4_navigation_diagnostics.sql','_crowd_v4_view_count.sql','_crowd_v4_safety.sql','_crowd_v4_receipt_recovery.sql','_crowd_v4_task_scheduling.sql','_crowd_v4_observations.sql','_crowd_v4_relevance_aliases.sql'])await db.exec(fs.readFileSync(new URL(fs.readdirSync(dir).find(n=>n.endsWith(suffix)),dir),'utf8'));
 for(const u of users){await db.query('insert into auth.users values($1)',[u]);await db.query("insert into crowd_v4.participants(user_id,status,consent) values($1,'approved','crowd-public-v4')",[u]);}
 async function call(user,sql,args=[]){await db.query("select set_config('request.jwt.claim.sub',$1,false)",[user]);await db.exec('set role authenticated');try{return (await db.query(sql,args)).rows[0].r;}finally{await db.exec('reset role');}}
 const claim=(u=users[0],id=null)=>call(u,'select public.crowd_v4_claim($1) as r',[id]);
 const finish=(task,u=users[0])=>call(u,'select public.crowd_v4_finish($1,$2) as r',[task.id,task.lease_token]);
 await db.exec("insert into crowd_v4.tasks(source_key,query,anchor_terms,target) values ('a','同店','[\"同店\"]',5),('b','同店','[\"同店\"]',5),('c','别店','[\"别店\"]',5)");
 const a=(await claim()).task;assert.equal(a.id,1);
 assert.equal((await claim(users[0],1)).task.lease_token,a.lease_token,'renewal keeps token');
 const b=(await claim(users[1])).task;assert.equal(b.id,2,'another participant cannot steal a live lease');
 assert.equal((await claim(users[1],1)).task,null,'explicit renewal cannot acquire another owner task');
 assert.equal((await finish(a,users[1])).error,'lease_lost');
 assert.equal((await finish({id:999,lease_token:null})).error,'lease_lost','missing task and null lease cannot pass null comparisons');
 const deferred=await finish(a);assert.equal(deferred.status,'open');
 assert.deepEqual(await finish(a),deferred,'lost finish response replays without extending delay/count');
 let row=(await db.query('select *,extract(epoch from available_at-now())::int as wait from crowd_v4.tasks where id=1')).rows[0];
 assert.equal(row.empty_passes,1);assert.ok(row.wait>890&&row.wait<=900);
 assert.equal((await claim(users[0],1)).task,null,'cannot bypass task delay by explicit claim');
 const c=(await claim()).task;assert.equal(c.id,3,'deferred oldest task does not starve new task');
 await finish(c);await finish(b,users[1]);assert.equal((await claim()).task,null,'all delayed is a normal empty pool');
 await db.exec("update crowd_v4.tasks set available_at=now()-interval '1 minute' where id=1");
 const again=(await claim()).task;assert.equal(again.id,1);assert.notEqual(again.lease_token,a.lease_token);
 assert.equal((await finish(a)).error,'lease_lost','stale finish cannot terminate a new lease');
 await finish(again);
 row=(await db.query('select empty_passes,extract(epoch from available_at-now())::int as wait from crowd_v4.tasks where id=1')).rows[0];
 assert.equal(row.empty_passes,2);assert.ok(row.wait>1790&&row.wait<=1800);
 // Relevant records include rejected records: all statuses occupy the global unique key.
 await db.query("insert into crowd_v4.proofs(note_id,user_id,task_id,record,status) values($1,$2,2,'{}','rejected'),($3,$2,3,'{}','received')",['a'.repeat(24),users[1],'b'.repeat(24)]);
 await db.exec("update crowd_v4.tasks set available_at=now()-interval '1 minute' where id=1");
 const productive=(await claim()).task;assert.deepEqual(productive.known_note_ids,['a'.repeat(24)]);
 await db.exec('update crowd_v4.tasks set received=1 where id=1');
 await finish(productive);assert.equal((await db.query('select empty_passes from crowd_v4.tasks where id=1')).rows[0].empty_passes,0,'new records reset the empty streak');
 await db.exec("update crowd_v4.tasks set available_at=now()-interval '1 minute' where id=1");
 const complete=(await claim()).task;await db.exec('update crowd_v4.tasks set received=target where id=1');
 assert.equal((await finish(complete)).status,'complete');
 await db.exec("update crowd_v4.tasks set status='leased',claimed_by='"+users[1]+"',lease_token=gen_random_uuid(),lease_until=now()-interval '1 minute',last_claimed_at=now() where id=2; update crowd_v4.tasks set available_at=now()-interval '1 minute',last_claimed_at=null where id=3");
 const capped=(await claim()).task;assert.equal(capped.id,3,'never attempted supply precedes recently expired supply');
 await db.exec('update crowd_v4.tasks set empty_passes=6 where id=3');
 await finish(capped);
 const cap=(await db.query('select empty_passes,extract(epoch from available_at-now())::int as wait from crowd_v4.tasks where id=3')).rows[0];
 assert.equal(cap.empty_passes,6);assert.ok(cap.wait>21590&&cap.wait<=21600,'empty retries cap at six hours');
 const acl=(await db.query("select has_function_privilege('anon','public.crowd_v4_claim(bigint)','execute') as anon,has_function_privilege('authenticated','public.crowd_v4_finish(bigint,uuid)','execute') as participant,has_table_privilege('authenticated','crowd_v4.tasks','select') as direct")).rows[0];
 assert.deepEqual(acl,{anon:false,participant:true,direct:false});
 console.log('PASS scheduling DB: lease ownership/renewal, deferred fairness, exact finish replay, rotated token rejects stale finish, exponential empty retry, progress reset, known IDs across same query, completion, grants');
} finally {await db.close();}
