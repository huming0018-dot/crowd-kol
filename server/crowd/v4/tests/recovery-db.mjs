import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {randomUUID} from 'node:crypto';
const {PGlite}=createRequire(import.meta.url)(path.join(process.env.CROWD_TEST_TOOLS,'node_modules/@electric-sql/pglite'));
const db=new PGlite(),u=randomUUID(),request=randomUUID();
const dir=new URL('../supabase/migrations/',import.meta.url);
try{
 await db.exec(`create role anon;create role authenticated;create role service_role;create schema auth;create table auth.users(id uuid primary key);
 create function auth.uid() returns uuid language sql as $$select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$;
 create function auth.role() returns text language sql as $$select current_setting('request.jwt.claim.role',true)$$;
 grant usage on schema auth to authenticated;grant execute on function auth.uid(),auth.role() to authenticated;`);
 const suffixes=['20261006145016_crowd_v4.sql','_crowd_v4_diagnostics.sql','_crowd_v4_navigation_diagnostics.sql','_crowd_v4_view_count.sql','_crowd_v4_safety.sql','_crowd_v4_receipt_recovery.sql'];
 for(const suffix of suffixes)await db.exec(fs.readFileSync(new URL(fs.readdirSync(dir).find(n=>n.endsWith(suffix)),dir),'utf8'));
 await db.query('insert into auth.users values($1)',[u]);
 await db.query("insert into crowd_v4.participants(user_id,status,consent,quota_day) values($1,'approved','crowd-public-v4',1)",[u]);
 await db.exec("insert into crowd_v4.tasks(source_key,query,anchor_terms,target) values('fixture','测试餐厅','[\"测试餐厅\"]',5)");
 await db.query("select set_config('request.jwt.claim.sub',$1,false)",[u]);
 async function query(sql,args=[]){await db.exec('set role authenticated');try{return (await db.query(sql,args)).rows[0].r;}finally{await db.exec('reset role');}}
 const task=(await query('select public.crowd_v4_claim() as r')).task;
 await db.query("insert into crowd_v4.proofs(note_id,user_id,task_id,record) values($1,$2,$3,'{}')",['b'.repeat(24),u,task.id]);
 const captured=new Date().toISOString(),text='测试餐厅清蒸鱼好吃，原始正文证据。';
 const record={schema_version:4,standard:{platform:'xiaohongshu',note_id:'a'.repeat(24),url:'https://www.xiaohongshu.com/explore/'+'a'.repeat(24),title:'测试餐厅',captured_at:captured,published_at:null,author_display:null,like_count:null,collect_count:null,comment_count:null,view_count:null},extra:{author_opinion_quotes:[]},evidence:{text,original_length:text.length,truncated:false,source:'rendered_public_dom',parser_version:'4.0.6'}};
 const submit=()=>query('select public.crowd_v4_submit($1,$2,$3,$4::jsonb) as r',[request,task.id,task.lease_token,JSON.stringify(record)]);
 const denied=await submit(),claim=await query('select public.crowd_v4_claim($1) as r',[task.id]);
 for(const r of [denied,claim]){assert.equal(r.error,'daily_quota');assert.ok(r.retry_after_ms>0&&r.retry_after_ms<=86400000);const end=new Date(r.reset_at);assert.equal(end.getUTCHours(),16);assert.equal(end.getUTCMinutes(),0);}
 assert.equal((await db.query('select count(*)::int as n from crowd_v4.receipts')).rows[0].n,0,'temporary quota never poisons idempotency');
 await db.exec("update crowd_v4.proofs set received_at=now()-interval '1 day'");
 const accepted=await submit();assert.equal(accepted.inserted,true);assert.equal(accepted.gate,'received');assert.equal(accepted.request,request);
 assert.deepEqual(await submit(),accepted,'exact receipt replays after quota becomes full again');
 const stored=(await db.query('select record from crowd_v4.proofs where note_id=$1',['a'.repeat(24)])).rows[0].record;
 assert.equal(stored.standard.captured_at,captured);assert.equal(stored.evidence.text,text);
 assert.equal((await db.query('select count(*)::int as n from crowd_v4.receipts')).rows[0].n,1);
 await query("select public.crowd_v4_diagnostics('enable',1,null) as r");
 const snapshot={version:'4.0.6',enabled:true,phase:'idle',error:'invalid_receipt',task_id:null,queued:1,rejected:0,page_kind:'unknown',tab_status:'missing',document:'unknown',gate:null,links:0,search_note_links:0,body_chars:0,visible:false};
 await query("select public.crowd_v4_diagnostics('report',1,$1::jsonb) as r",[JSON.stringify(snapshot)]);
 console.log('PASS PostgreSQL recovery: Shanghai reset deadline, no quota receipt poison, same UUID succeeds after quota reset, exact replay and unchanged evidence/capture time, fixed diagnostic enum');
}finally{await db.close();}
