import fs from 'node:fs';import path from 'node:path';import assert from 'node:assert/strict';import {createRequire} from 'node:module';import {fileURLToPath} from 'node:url';
const {PGlite}=createRequire(import.meta.url)(path.join(process.env.CROWD_TEST_TOOLS,'node_modules/@electric-sql/pglite'));
const db=new PGlite(),dir=fileURLToPath(new URL('../supabase/migrations/',import.meta.url));
const u='00000000-0000-4000-8000-000000000001',other='00000000-0000-4000-8000-000000000002',req='00000000-0000-4000-8000-000000000003';
try{
 await db.exec(`create role anon;create role authenticated;create role service_role;create schema auth;create table auth.users(id uuid primary key);
 create function auth.uid() returns uuid language sql as $$select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$;
 create function auth.role() returns text language sql as $$select current_setting('request.jwt.claim.role',true)$$;
 grant usage on schema auth to authenticated,service_role;grant execute on function auth.uid(),auth.role() to authenticated,service_role;`);
 for(const suffix of ['20261006145016_crowd_v4.sql','_crowd_v4_ratings.sql'])await db.exec(fs.readFileSync(path.join(dir,fs.readdirSync(dir).find(n=>n.endsWith(suffix))),'utf8'));
 for(const id of [u,other]){await db.query('insert into auth.users values($1)',[id]);await db.query("insert into crowd_v4.participants(user_id,status,consent)values($1,'approved','crowd-public-v4')",[id]);}
 await db.exec(`insert into crowd_v4.tasks(source_key,query,anchor_terms)values('test','测试餐厅','["测试餐厅"]');`);
 for(let i=1;i<=3;i++)await db.query("insert into crowd_v4.proofs(note_id,user_id,task_id,record,status)values($1,$2,1,'{\"standard\":{\"title\":\"测试餐厅\"}}',$3)",[String(i).padStart(24,'a'),i===3?other:u,i===2?'rejected':'received']);
 async function call(user,name,args=[]){await db.query("select set_config('request.jwt.claim.sub',$1,false)",[user]);await db.exec('set role authenticated');try{return(await db.query('select public.crowd_v4_'+name+'('+args.map((_,i)=>'$'+(i+1)).join(',')+') as r',args)).rows[0].r;}finally{await db.exec('reset role');}}
 const args=[req,1,5,'本人吃过这里的清蒸鱼'];
 assert.equal((await call(u,'rating',[req,3,5,args[3]])).error,'invalid_anchor');
 assert.equal((await call(u,'rating',[req,2,5,args[3]])).error,'invalid_anchor');
 assert.equal((await call(u,'rating',[req,1,6,args[3]])).error,'invalid_rating');
 assert.equal((await call(u,'rating',[req,1,5,'........'])).error,'invalid_rating');
 assert.equal((await call(u,'rating',args)).inserted,true);
 assert.equal((await call(u,'rating',args)).inserted,false);
 assert.equal((await call(u,'rating',[req,1,4,args[3]])).error,'request_reused');
 assert.equal((await call(u,'rating',['00000000-0000-4000-8000-000000000004',1,4,args[3]])).error,'already_rated');
 const mine=await call(u,'progress');assert.equal(mine.ratings.length,1);assert.equal(mine.ratings[0].score,5);assert.equal(mine.tasks[0].own_received,2);
 assert.equal((await call(other,'progress')).ratings[0].score,null,'another participant cannot read this rating');
 assert.equal((await db.query('select count(*) n from crowd_v4.rewards')).rows[0].n,0,'rating never changes financial ledgers');
 const grants=(await db.query("select has_function_privilege('anon','public.crowd_v4_rating(uuid,bigint,int,text)','execute') as anon,has_table_privilege('authenticated','crowd_v4.ratings','select') as direct")).rows[0];assert.deepEqual(grants,{anon:false,direct:false});
 console.log('PASS ratings: own nonrejected anchor, range/reason, stable idempotent receipt, one vote per task, identity isolation and unchanged rewards');
}finally{await db.close();}
