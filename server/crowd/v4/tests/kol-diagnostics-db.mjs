import assert from 'node:assert/strict';
import fs from 'node:fs';import path from 'node:path';import {createRequire} from 'node:module';import {randomUUID} from 'node:crypto';
const {PGlite}=createRequire(import.meta.url)(path.join(process.env.CROWD_TEST_TOOLS,'node_modules/@electric-sql/pglite'));
const db=new PGlite(),user=randomUUID();
try{
 await db.exec(`create role anon;create role authenticated;create role service_role;create schema auth;create table auth.users(id uuid primary key,email text);
 create function auth.uid() returns uuid language sql as $$select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$;
 create function auth.role() returns text language sql as $$select current_setting('request.jwt.claim.role',true)$$;
 grant usage on schema auth to authenticated;grant execute on function auth.uid(),auth.role() to authenticated;`);
 const dir=new URL('../supabase/migrations/',import.meta.url);
 for(const name of fs.readdirSync(dir).filter(n=>n.endsWith('.sql')).sort())await db.exec(fs.readFileSync(new URL(name,dir),'utf8'));
 await db.query('insert into auth.users(id) values($1)',[user]);
 await db.query("insert into crowd_v4.participants(user_id,status,consent,joined_at) values($1,'approved','crowd-public-v4',now()-interval '30 days')",[user]);
 await db.query("select set_config('request.jwt.claim.sub',$1,false)",[user]);await db.exec('set role authenticated');
 await db.query("select public.crowd_v4_diagnostics('enable',1,null)");
 const kol={enabled:true,phase:'discovery_scroll',error:'delivery_retry_limit',platform:'bilibili',queued:1,rejected:0,received:1,attempts:2,checkpoint_revision:2,delivery_paused:true,next_in_s:0};
 const snapshot={version:'4.2.5',enabled:false,phase:'idle',error:null,task_id:null,queued:0,rejected:0,page_kind:'unknown',tab_status:'missing',document:'unknown',gate:null,links:0,search_note_links:0,body_chars:0,visible:null,kol};
 const report=state=>db.query("select public.crowd_v4_diagnostics('report',1,$1) result",[state]);
 assert.ok((await report(snapshot)).rows[0].result.saved_at);
 for(const delta of [{secret:'PRIVATE_TOKEN'},{queued:-1},{platform:'https://secret'},{error:'PRIVATE_COOKIE'},{phase:'other'},{delivery_paused:'true'},{next_in_s:86401}])
  await assert.rejects(report({...snapshot,kol:{...kol,...delta}}),/invalid_kol_diagnostics/);
 for(const error of ['platform_identity_changed','old_executor_required','checkpoint_gap','lease_expired'])assert.ok((await report({...snapshot,kol:{...kol,error}})).rows[0].result.saved_at);
 const legacy={...snapshot};delete legacy.kol;assert.ok((await report(legacy)).rows[0].result.saved_at);
 await db.query("select public.crowd_v4_diagnostics('disable',2,null)");
 await assert.rejects(report(snapshot),/stale_diagnostics/);await db.exec('reset role');
 const state=(await db.query('select state from crowd_v4.diagnostics where user_id=$1',[user])).rows[0].state;
 assert.equal(state,null,'stale reports cannot revive opted-out diagnostics');
 console.log('PASS KOL diagnostics strict fields, real state enums, legacy compatibility, opt-out revision');
}finally{await db.close();}
