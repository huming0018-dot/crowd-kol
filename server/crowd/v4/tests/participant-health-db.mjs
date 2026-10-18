import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {handleMachine} from '../supabase/functions/crowd-machine/core.mjs';
import {sha} from '../supabase/functions/crowd-machine/contract.mjs';
const require=createRequire(import.meta.url);
if(!process.env.CROWD_TEST_TOOLS)throw new Error('Set CROWD_TEST_TOOLS');
const {PGlite}=require(path.join(process.env.CROWD_TEST_TOOLS,'node_modules/@electric-sql/pglite'));
const db=new PGlite();
const user='00000000-0000-4000-8000-000000000001',other='00000000-0000-4000-8000-000000000002';
await db.exec(`create role anon;create role authenticated;create role service_role;create schema auth;create schema crowd_v4;
create function auth.uid() returns uuid language sql as $$select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$;
create table crowd_v4.participants(user_id uuid primary key,status text,consent text);
insert into crowd_v4.participants values('${user}','approved','crowd-public-v4'),('${other}','approved','crowd-public-v4');`);
const migrations=fileURLToPath(new URL('../supabase/migrations/',import.meta.url));
await db.exec(fs.readFileSync(path.join(migrations,'20261007051154_crowd_v4_diagnostics.sql'),'utf8'));
if(process.env.CROWD_DIAGNOSTICS_BASE)await db.exec(fs.readFileSync(process.env.CROWD_DIAGNOSTICS_BASE,'utf8'));
await db.exec(fs.readFileSync(path.join(migrations,'20261013135950_crowd_v4_participant_health_history.sql'),'utf8'));
const base={version:'4.2.16',enabled:true,phase:'idle',error:null,task_id:null,queued:0,rejected:0,page_kind:'missing',tab_status:'missing',document:'unknown',gate:null,links:0,search_note_links:0,body_chars:0,visible:false};
async function diagnostic(id,action,revision,state=null){await db.query("select set_config('request.jwt.claim.sub',$1,false)",[id]);return (await db.query('select public.crowd_v4_diagnostics($1,$2,$3::jsonb) result',[action,revision,state===null?null:JSON.stringify(state)])).rows[0].result;}
async function health(actor='owner',scope='crowd-owner-main',payload={}){return (await db.query('select public.crowd_participant_health_rpc($1,$2,$3::jsonb) result',[scope,actor,JSON.stringify(payload)])).rows[0].result;}
async function count(){return (await db.query('select count(*)::int n from crowd_v4.participant_health_events')).rows[0].n;}
await diagnostic(user,'enable',1);await diagnostic(user,'report',1,base);
assert.equal(await count(),2);
await diagnostic(user,'report',1,base);assert.equal(await count(),2,'unchanged reports refresh but no extra history');
await diagnostic(user,'report',1,{...base,error:'logged_out',queued:2});assert.equal(await count(),3);
let result=await health();assert.equal(result.participants[0].error,'logged_out');assert.equal(result.participants[0].queued,2);assert.equal(result.participants[0].stale,false);assert.equal(result.events[0].error,'logged_out');
const ota={...base,ota_last_poll_at:1791892800,ota_poll_status:'error',ota_poll_error:'hash_mismatch',ota_poll_query_error:null};
await diagnostic(user,'report',1,ota);const previous=await count();await diagnostic(user,'report',1,{...ota,ota_last_poll_at:1791892860});assert.equal(await count(),previous,'poll timestamp alone not history flood');
result=await health();assert.equal(result.participants[0].ota_last_poll_at,1791892860);assert.equal(result.participants[0].ota_poll_error,'hash_mismatch');
for(const [field,values] of Object.entries({ota_last_poll_at:[-1,4102444801,1.5,'123',{},true],ota_poll_status:['PRIVATE_URL',{},1,true],ota_poll_error:['PRIVATE_TOKEN',{},1,true],ota_poll_query_error:['PRIVATE_COOKIE',{},1,true]}))for(const value of values)await assert.rejects(diagnostic(user,'report',1,{...ota,[field]:value}),/invalid_diagnostics/);
for(const value of ['invalid_signature','hash_mismatch','permission_change','replayed_release','recovery_required','busy','operation_failed','invalid_manifest','invalid_url','wrong_extension','update_failed'])await diagnostic(user,'report',1,{...ota,ota_poll_error:value});
await diagnostic(user,'report',1,{...base,ota_last_poll_at:null,ota_poll_status:null,ota_poll_error:null,ota_poll_query_error:null});
await diagnostic(other,'enable',1);await diagnostic(other,'report',1,{...base,error:'captcha'});
await db.query("update crowd_v4.diagnostics set updated_at=now()-interval '181 seconds' where user_id=$1",[user]);result=await health();assert.equal(result.participants.find(p=>p.user_id===user).stale,true);assert.equal(result.participants.find(p=>p.user_id===other).stale,false);
// Privileged malformed snapshot must still never leak arbitrary text or identifiers.
await db.query('update crowd_v4.diagnostics set state=$1::jsonb,updated_at=now() where user_id=$2',[JSON.stringify({...base,error:'Cookie=secret',kol:{error:'https://secret.invalid/token'},url:'https://secret.invalid',body:'PRIVATE_BODY',ota_poll_error:'PRIVATE_KEY'}),user]);
result=await health();assert.equal(result.participants.find(p=>p.user_id===user).error,'unexpected_error');assert.equal(result.participants.find(p=>p.user_id===user).kol_error,'unexpected_error');assert(!JSON.stringify(result).includes('secret'));assert(!JSON.stringify(result).includes('PRIVATE_'));
await diagnostic(user,'disable',2);result=await health();assert(!result.events.some(e=>e.user_id===user));assert.equal(result.participants.find(p=>p.user_id===user).diagnostics_enabled,false);assert.equal(result.participants.find(p=>p.user_id===user).version,null);
await assert.rejects(health('worker'),/principal_denied/);await assert.rejects(health('owner','another-project'),/principal_denied/);
for(const payload of [{limit:0},{limit:101},{event_limit:201},{event_limit:1.5},{user_id:user},{limit:'1'},null,[]])await assert.rejects(health('owner','crowd-owner-main',payload),/invalid_request/);
const privileges=(await db.query("select has_function_privilege('anon','public.crowd_participant_health_rpc(text,text,jsonb)','EXECUTE') anon,has_function_privilege('authenticated','public.crowd_participant_health_rpc(text,text,jsonb)','EXECUTE') auth,has_function_privilege('service_role','public.crowd_participant_health_rpc(text,text,jsonb)','EXECUTE') service,has_table_privilege('authenticated','crowd_v4.participant_health_events','SELECT') direct")).rows[0];assert.deepEqual(privileges,{anon:false,auth:false,service:true,direct:false});
await db.exec(`insert into crowd_v4.participant_health_events(user_id,at,snapshot) select '${other}',now(),'{"error":"captcha"}'::jsonb from generate_series(1,502); update crowd_v4.diagnostics set updated_at=now() where user_id='${other}';`);assert.equal((await db.query('select count(*)::int n from crowd_v4.participant_health_events where user_id=$1',[other])).rows[0].n,500);
await db.exec(`insert into crowd_v4.participant_health_events(user_id,at,snapshot) values('${other}',now()-interval '8 days','{}');`);await health();assert.equal((await db.query("select count(*)::int n from crowd_v4.participant_health_events where at<now()-interval '7 days'")).rows[0].n,0);
// Global hard bound applies on diagnostic writes, with a serial transaction lock.
await db.exec(`insert into crowd_v4.participant_health_events(user_id,at,snapshot) select '${user}',now(),'{"error":null}'::jsonb from generate_series(1,10001); update crowd_v4.diagnostics set updated_at=now() where user_id='${other}';`);assert.equal(await count(),10000);
let calls=0;const ownerKey='1'.repeat(64),ownerHash=await sha(ownerKey),workerKey='2'.repeat(64);
const backend={rpc:async(name,args)=>{calls++;assert.equal(name,'crowd_participant_health_rpc');return {data:await health(args.p_actor_kind,args.p_owner_scope,args.p_payload),error:null};}};
function request(headers,payload={}){return new Request('https://example.supabase.co/functions/v1/crowd-machine',{method:'POST',headers:{'Content-Type':'application/json',...headers},body:JSON.stringify({action:'participant_health',payload})});}
assert.equal((await handleMachine(request({'X-Crowd-Owner-Key':ownerKey}),backend,ownerHash)).status,200);assert.equal(calls,1);
assert.equal((await handleMachine(request({'X-Crowd-Worker-Key':workerKey}),backend,ownerHash)).status,403);assert.equal(calls,1);
assert.equal((await handleMachine(request({}),backend,ownerHash)).status,403);assert.equal(calls,1);
assert.equal((await handleMachine(request({'X-Crowd-Owner-Key':ownerKey},{limit:101}),backend,ownerHash)).status,400);assert.equal(calls,1);
await db.close();console.log('PASS participant health: private ACLs, safe projection, dedup/freshness, OTA whitelist, opt-out clear, owner-only Edge/RPC, retention and hard capacity bounds');
