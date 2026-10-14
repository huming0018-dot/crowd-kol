import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import vm from 'node:vm';
import {execFileSync} from 'node:child_process';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
const require=createRequire(import.meta.url), here=path.dirname(fileURLToPath(import.meta.url));
if(!process.env.CROWD_TEST_TOOLS) throw Error('Set CROWD_TEST_TOOLS to the existing development tools directory');
if(!process.env.CROWD_FROZEN_62_ZIP) throw Error('Set CROWD_FROZEN_62_ZIP to the reviewed 4.2.62 participant ZIP');
const archive=fs.readFileSync(process.env.CROWD_FROZEN_62_ZIP);
assert.equal(crypto.createHash('sha256').update(archive).digest('hex'),'37b064ed5fec6cfdd929ca2c1929b95f301d21e79674f32e95ff71904d480c89');
const background=execFileSync('/usr/bin/unzip',['-p',process.env.CROWD_FROZEN_62_ZIP,'src/background.js'],{encoding:'utf8'});
const start=background.indexOf('async function reportDiagnostics() {'),end=background.indexOf('async function setDiagnostics(',start);
assert(start>=0 && end>start);
const errors=background.match(/const diagnosticErrors = (\[[^\n]+\]);/);
assert(errors);
const snapshots=[],saved=[];
const context=vm.createContext({AbortController,setTimeout,clearTimeout,Date,Number,Math,Promise,
 diagnosticSettings:async()=>({id:'00000000-0000-4000-8000-000000000001',enabled:true,revision:1}),
 diagnosticKey:(_id,field)=>field,
 storage:{get:async()=>null,set:async(key,value)=>saved.push({key,value})},
 api:{rpc:async(name,params)=>{assert.equal(name,'diagnostics');assert.equal(params.p_action,'report');snapshots.push(JSON.parse(JSON.stringify(params.p_state)));return {saved_at:new Date().toISOString()};}},
 agent:{read:async()=>({enabled:false,phase:'search',last_error:'login_required',task:{id:19},outbox:[],rejected:[],next_at:0})},
 workingTab:async()=>null,updater:{status:async()=>({state:'applied',enabled:true})},
 trace:{snapshot:async()=>[]},localTests:{status:async()=>({enabled:false})},
 CrowdCore:{VERSION:'4.2.62'},workTabs:{lastFailure:null}
});
await vm.runInContext(`let diagnosticReport=null;const diagnosticErrors=${errors[1]};\n${background.slice(start,end)}\nreportDiagnostics();`,context);
assert.equal(snapshots.length,1,'execute actual frozen reporter without source/API requests');
assert.equal(snapshots[0].pool_failure,null);
assert.equal(saved.at(-1).value.error,null);
const snapshot=snapshots[0];
const {PGlite}=require(path.join(process.env.CROWD_TEST_TOOLS,'node_modules/@electric-sql/pglite'));
const db=new PGlite(),user='00000000-0000-4000-8000-000000000001',other='00000000-0000-4000-8000-000000000002';
await db.exec(`create role anon;create role authenticated;create schema auth;create schema crowd_v4;
create function auth.uid() returns uuid language sql as $$select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$;
create table crowd_v4.participants(user_id uuid primary key,status text,consent text);
insert into crowd_v4.participants values('${user}','approved','crowd-public-v4'),('${other}','approved','crowd-public-v4');`);
const migrations=path.join(here,'../supabase/migrations');
await db.exec(fs.readFileSync(path.join(migrations,'20261007051154_crowd_v4_diagnostics.sql'),'utf8'));
await db.exec('alter table crowd_v4.diagnostics drop constraint diagnostics_state_check; alter table crowd_v4.diagnostics add constraint diagnostics_state_check check(state is null or (jsonb_typeof(state)=\'object\' and octet_length(state::text)<=8192));');
await db.exec(fs.readFileSync(path.join(here,'fixtures/diagnostics-20261014-before-nullable-pool.sql'),'utf8'));
async function call(uid,action,revision,state=null){
 await db.query("select set_config('request.jwt.claim.sub',$1,false)",[uid||'']);
 return (await db.query('select public.crowd_v4_diagnostics($1,$2,$3::jsonb) result',[action,revision,state===null?null:JSON.stringify(state)])).rows[0].result;
}
await call(user,'enable',1);
await assert.rejects(call(user,'report',1,snapshot),/invalid_diagnostics/,'exact 62 reporter must reproduce production rejection');
const withoutPool={...snapshot};delete withoutPool.pool_failure;
await call(user,'report',1,withoutPool);
const before=(await db.query("select pg_get_functiondef('public.crowd_v4_diagnostics(text,bigint,jsonb)'::regprocedure) definition")).rows[0].definition;
const patch=fs.readFileSync(path.join(migrations,'20261014011736_crowd_v4_diagnostics_nullable_pool.sql'),'utf8');
await db.exec(patch);
const after=(await db.query("select pg_get_functiondef('public.crowd_v4_diagnostics(text,bigint,jsonb)'::regprocedure) definition")).rows[0].definition;
assert.equal(after,before.replace("if p_state ? 'pool_failure' and (jsonb_typeof(p_state->'pool_failure') is distinct from 'string'","if p_state ? 'pool_failure' and jsonb_typeof(p_state->'pool_failure') <> 'null' and (jsonb_typeof(p_state->'pool_failure') is distinct from 'string'"),'only nullable-pool predicate changes');
await call(user,'report',1,snapshot);
assert.deepEqual((await db.query('select state from crowd_v4.diagnostics where user_id=$1',[user])).rows[0].state,snapshot);
await call(user,'report',1,withoutPool);
const accepted=['entry_state','tab_missing','tab_discarded','url_changed','token_changed','document_changed','unbound_restart','bind_failed','presentation_identity','close_identity','unknown'];
for(const pool_failure of accepted)await call(user,'report',1,{...snapshot,pool_failure});
const invalid=[false,0,{},[],1.1,'','null','https://private.invalid/','PRIVATE_COOKIE','unsupported'];
for(const pool_failure of invalid)await assert.rejects(call(user,'report',1,{...snapshot,pool_failure}),/invalid_diagnostics/);
for(const extra of [{cookie:'PRIVATE_COOKIE'},{trace:[{id:'00000000-0000-4000-8000-000000000001',at:1,stage:'nav_complete',url:'private'}]},{ota_poll_error:'PRIVATE_TOKEN'},{version:'3.5.1'}])await assert.rejects(call(user,'report',1,{...snapshot,...extra}),/invalid_diagnostics/);
await assert.rejects(call(null,'report',1,snapshot),/login_required/);
await assert.rejects(call(other,'report',1,snapshot),/stale_diagnostics/);
await call(other,'enable',1);await call(other,'report',1,{...snapshot,error:null});
await call(user,'disable',2);await assert.rejects(call(user,'report',1,snapshot),/stale_diagnostics/);
await assert.rejects(call(user,'enable',1),/stale_diagnostics/);
const rows=(await db.query('select user_id,state from crowd_v4.diagnostics order by user_id')).rows;
assert.equal(rows[0].state,null);assert.equal(rows[1].state.error,null);
const grants=(await db.query("select has_function_privilege('anon','public.crowd_v4_diagnostics(text,bigint,jsonb)','EXECUTE') anon,has_function_privilege('authenticated','public.crowd_v4_diagnostics(text,bigint,jsonb)','EXECUTE') auth,has_table_privilege('authenticated','crowd_v4.diagnostics','SELECT') direct")).rows[0];
assert.deepEqual(grants,{anon:false,auth:true,direct:false});
await assert.rejects(db.exec(patch),/diagnostics_pool_contract_changed/,'fail closed when already modified or anchor changed');
await db.exec('rollback');
await db.close();
console.log(JSON.stringify({pass:true,frozen_reporter:'4.2.62',production_rejection_reproduced:true,only_nullable_predicate_changed:true,accepted_pool_states:accepted.length+2,rejected_pool_states:invalid.length,auth_optout_isolation_grants_preserved:true,source_requests:0,production_writes:0}));
