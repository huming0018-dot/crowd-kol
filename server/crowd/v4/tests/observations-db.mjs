import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {randomUUID} from 'node:crypto';
const {PGlite}=createRequire(import.meta.url)(path.join(process.env.CROWD_TEST_TOOLS,'node_modules/@electric-sql/pglite'));
const db=new PGlite(), user=randomUUID(), stranger=randomUUID(), parent=randomUUID(), note='a'.repeat(24), author='b'.repeat(24);
try {
 await db.exec(`create role anon;create role authenticated;create role service_role;create schema auth;create table auth.users(id uuid primary key);
 create function auth.uid() returns uuid language sql as $$select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$;
 create function auth.role() returns text language sql as $$select current_setting('request.jwt.claim.role',true)$$;
 grant usage on schema auth to authenticated;grant execute on function auth.uid(),auth.role() to authenticated;`);
 const dir=new URL('../supabase/migrations/',import.meta.url);
 for(const suffix of ['20261006145016_crowd_v4.sql','_crowd_v4_diagnostics.sql','_crowd_v4_navigation_diagnostics.sql','_crowd_v4_view_count.sql','_crowd_v4_safety.sql','_crowd_v4_receipt_recovery.sql','_crowd_v4_task_scheduling.sql','_crowd_v4_observations.sql','_crowd_v4_relevance_aliases.sql']){
  try {await db.exec(fs.readFileSync(new URL(fs.readdirSync(dir).find(n=>n.endsWith(suffix)),dir),'utf8'));}catch(e){throw new Error(suffix+': '+e.message);}
 }
 for(const u of [user,stranger]){await db.query('insert into auth.users values($1)',[u]);await db.query("insert into crowd_v4.participants(user_id,status,consent) values($1,'approved','crowd-public-v4')",[u]);}
 async function call(sql,args=[],u=user){await db.query("select set_config('request.jwt.claim.sub',$1,false)",[u]);await db.exec('set role authenticated');try{return (await db.query(sql,args)).rows[0].r;}finally{await db.exec('reset role');}}
 await db.exec("insert into crowd_v4.tasks(source_key,query,anchor_terms,target) values('obs','餐厅','[\"餐厅\"]',1)");
 const task=(await call('select public.crowd_v4_claim() r')).task;
 const record={schema_version:4,standard:{platform:'xiaohongshu',note_id:note,url:'https://www.xiaohongshu.com/explore/'+note,title:'餐厅',captured_at:new Date().toISOString(),published_at:null,author_display:'作者',like_count:12000,collect_count:null,comment_count:2,view_count:null},extra:{author:{id:author,url:'https://www.xiaohongshu.com/user/profile/'+author},author_opinion_quotes:[]},evidence:{text:'好吃',original_length:2,truncated:false,parser_version:'4.1.0',source:'rendered_public_dom'}};
 const submit=()=>call('select public.crowd_v4_submit($1,$2,$3,$4) r',[parent,task.id,task.lease_token,record]);
 const result=await submit();assert.equal(result.gate,'received');assert.deepEqual(await submit(),result);
 assert.equal((await db.query('select count(*)::int n from crowd_observation.snapshots')).rows[0].n,1);
 assert.equal((await db.query('select count(*)::int n from crowd_observation.authors')).rows[0].n,1);
 const control=await call("select public.crowd_v4_guard('control') r");assert.equal(control.observations,1);
 const claim=()=>call('select public.crowd_v4_profile_claim($1) r',[parent]);
 assert.equal((await claim()).reason,'consent_required');
 await call('select public.crowd_v4_observation_preferences(true) r');
 const grant=await claim();assert.equal(grant.allowed,true,JSON.stringify(grant));assert.ok(grant.token);
 assert.equal((await claim()).reason,'profile_cached');
 await assert.rejects(call("select public.crowd_v4_guard('profile',1,$1) r",[note]),/invalid_action/);
 const observe=(id,kind,data,u=user)=>call('select public.crowd_v4_observe($1,$2,$3,$4) r',[id,parent,kind,data],u);
 const supplement=structuredClone(record);supplement.extra.comments={items:[{key:'comment-1',parent_key:null,text:'不错',original_length:2,truncated:false}],coverage:'visible_loaded_only',complete:false,captured_count:1,truncated:false};
 const request=randomUUID(), receipt=await observe(request,'note',supplement);assert.equal(receipt.gate,'observed',JSON.stringify(receipt));assert.deepEqual(await observe(request,'note',supplement),receipt);
 const changed=structuredClone(supplement);changed.evidence.text='其他';assert.equal((await observe(request,'note',changed)).error,'request_reused');
 assert.equal((await observe(randomUUID(),'note',supplement,stranger)).error,'parent_missing');
 assert.equal((await observe(randomUUID(),'note',supplement)).error,'already_observed');
 const profile={author_id:author,url:record.extra.author.url,nickname:'作者新名字',public_handle:'公开号',captured_at:new Date().toISOString(),source:'rendered_public_dom',parser_version:'4.1.0',metrics:{followers:{value:12000,label:'1.2万',status:'approximate'}},notes:[{note_id:note,title:'餐厅'}],grant:grant.token};
 const pr=randomUUID();assert.equal((await observe(pr,'profile',profile)).gate,'observed');
 await call('select public.crowd_v4_observation_preferences(false) r');assert.equal((await observe(pr,'profile',profile)).gate,'observed','existing exact receipt replays after opt-out');
 const totals=(await db.query('select (select count(*)::int from crowd_v4.proofs) proofs,(select count(*)::int from crowd_observation.snapshots) snapshots,(select received from crowd_v4.tasks where id=1) received')).rows[0];assert.deepEqual(totals,{proofs:1,snapshots:3,received:1});
 assert.equal((await db.query("select record->'extra' ? 'comments' as changed from crowd_v4.proofs")).rows[0].changed,false,'original proof not overwritten');
 assert.equal((await db.query("select has_schema_privilege('authenticated','crowd_observation','usage') s,has_function_privilege('anon','public.crowd_v4_observe(uuid,uuid,text,jsonb)','execute') a,has_function_privilege('authenticated','crowd_observation.guard_internal(text,bigint,text)','execute') g")).rows[0].g,false);
 // Alias registry repairs canonical task creation, without accepting the ambiguous bare name.
 await db.exec(`insert into crowd_v4.tasks(source_key,query,store_name,anchor_terms,target) values('alias','晴川sushi','晴川sushi（午市）','["晴川sushi"]',2)`);
 const aliases=(await db.query("select anchor_terms from crowd_v4.tasks where source_key='alias'")).rows[0].anchor_terms;
 assert.deepEqual(aliases,['晴川sushi','晴川寿司','晴川日本料理']);assert.equal(aliases.includes('晴川'),false);
 const ar=structuredClone(record);ar.standard.title='晴川寿司';ar.evidence.text='这顿饭不错';ar.evidence.original_length=5;
 assert.deepEqual((await db.query("select crowd_observation.validate_note($1,(select id from crowd_v4.tasks where source_key='alias')) r",[ar])).rows[0].r,{});
 ar.standard.title='晴川风景';assert.equal((await db.query("select crowd_observation.validate_note($1,(select id from crowd_v4.tasks where source_key='alias')) r",[ar])).rows[0].r.error,'unrelated_note');
 const bad=structuredClone(record);bad.standard.title='其他店';bad.evidence.text='另外的地方';bad.evidence.original_length=5;
 const badId=randomUUID();assert.equal((await call('select public.crowd_v4_submit($1,1,$2,$3) r',[badId,task.lease_token,bad])).error,'task_full');
 const summary=(await db.query('select * from crowd_observation.submission_status where user_id=$1',[user])).rows[0];assert.equal(summary.error,'task_full');assert.equal('data' in summary,false);
 // A profile consumes detail/session/gap budgets, and the per-user daily cap cannot be bypassed by new authors.
 assert.equal((await db.query("select (counts->>'detail')::int n from crowd_v4.safety where user_id=$1",[user])).rows[0].n,1);
 await call('select public.crowd_v4_observation_preferences(true) r');
 await db.exec('update crowd_v4.tasks set target=5 where id=1');
 for(let index=0;index<2;index++){
  const r2=structuredClone(record),p2=randomUUID();r2.standard.note_id=(index?'d':'c').repeat(24);r2.standard.url='https://www.xiaohongshu.com/explore/'+r2.standard.note_id;
  r2.extra.author={id:(index?'f':'e').repeat(24),url:'https://www.xiaohongshu.com/user/profile/'+(index?'f':'e').repeat(24)};
  delete r2.standard.view_count; // Older clients remain compatible.
  assert.equal((await call('select public.crowd_v4_submit($1,1,$2,$3) r',[p2,task.lease_token,r2])).gate,'received');
  await db.exec("update crowd_v4.safety set next_action=now()-interval '1 second'");
  const g2=await call('select public.crowd_v4_profile_claim($1) r',[p2]);
  if(index===0)assert.equal(g2.allowed,true);else assert.equal(g2.reason,'profile_budget');
 }
 const privileges=(await db.query("select has_schema_privilege('authenticated','crowd_observation','usage') s,has_function_privilege('anon','public.crowd_v4_observe(uuid,uuid,text,jsonb)','execute') a,has_function_privilege('authenticated','crowd_observation.guard_internal(text,bigint,text)','execute') g")).rows[0];assert.deepEqual(privileges,{s:false,a:false,g:false});
 await call("select public.crowd_v4_guard('rate_limit') r");assert.equal((await db.query('select paused from crowd_v4.policy')).rows[0].paused,false);
 await call("select public.crowd_v4_guard('rate_limit') r",[],stranger);assert.equal((await db.query('select paused from crowd_v4.policy')).rows[0].paused,true);
 assert.equal((await db.query("select count(*)::int n from crowd_v4.audit where action='automatic_pause'")).rows[0].n,1);
 console.log('PASS observations SQL: short note, atomic base projection, private schema, exact replay, immutable evidence, identity ownership, explicit profile opt-in, global cache/shared guard, snapshots do not increase rewards');
} catch(e){console.error(e.message,e.detail || "",e.where || "");process.exitCode=1;}finally{await db.close();}
