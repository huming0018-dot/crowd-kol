import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {handleMachine} from '../supabase/functions/crowd-machine/core.mjs';
import {sha} from '../supabase/functions/crowd-machine/contract.mjs';
const require=createRequire(import.meta.url);
process.on('uncaughtException',error=>{console.error(error.message,error.where||'',error.position||'');process.exit(1);});
if(!process.env.CROWD_TEST_TOOLS)throw new Error('Set CROWD_TEST_TOOLS');
const {PGlite}=require(path.join(process.env.CROWD_TEST_TOOLS,'node_modules/@electric-sql/pglite'));
const db=new PGlite();
const user='00000000-0000-4000-8000-000000000001',other='00000000-0000-4000-8000-000000000002';
const node='10000000-0000-4000-8000-000000000001',otherNode='10000000-0000-4000-8000-000000000002';
const dir=fileURLToPath(new URL('../supabase/migrations/',import.meta.url));
await db.exec(`create role anon;create role authenticated;create role service_role;create schema auth;
create table auth.users(id uuid primary key);create function auth.uid() returns uuid language sql as $$select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$;
create function auth.role() returns text language sql as $$select nullif(current_setting('request.jwt.claim.role',true),'')$$;`);
for(const file of ['20261006145016_crowd_v4.sql','20261007051154_crowd_v4_diagnostics.sql','20261013135950_crowd_v4_participant_health_history.sql','20261011033423_crowd_machine.sql'])await db.exec(fs.readFileSync(path.join(dir,file),'utf8'));
const definitions=(await db.query("select oid::regprocedure::text name,md5(pg_get_functiondef(oid)) hash from pg_proc where pronamespace='public'::regnamespace and proname in ('crowd_v4_claim','crowd_v4_submit','crowd_v4_finish') order by proname")).rows;
await db.exec(fs.readFileSync(path.join(dir,'20261013165118_crowd_distributed_nodes.sql'),'utf8'));
await db.exec(`insert into auth.users values('${user}'),('${other}');insert into crowd_v4.participants(user_id,status,consent) values('${user}','approved','crowd-public-v4'),('${other}','approved','crowd-public-v4');
insert into crowd_v4.tasks(source_key,query,anchor_terms) values('task1','上海餐厅','["餐厅"]'),('task2','上海咖啡','["咖啡"]');`);
async function identity(id){await db.query("select set_config('request.jwt.claim.sub',$1,false)",[id||'']);}
async function register(id,installation,state={version:'4.2.60',enabled:true,login_state:'ready'}){await identity(id);return (await db.query('select public.crowd_v4_node_register($1,$2::jsonb) result',[installation,JSON.stringify(state)])).rows[0].result;}
async function claim(id,installation,task=null){await identity(id);return (await db.query('select public.crowd_v4_node_claim($1,$2) result',[installation,task])).rows[0].result;}
async function report(id,installation,events){await identity(id);return (await db.query('select public.crowd_v4_step_events($1,$2::jsonb) result',[installation,JSON.stringify(events)])).rows[0].result;}
async function monitor(action='unified_status',payload={},actor='owner'){return (await db.query('select public.crowd_unified_monitor_rpc($1,$2,$3,$4::jsonb) result',['crowd-owner-main',actor,action,JSON.stringify(payload)])).rows[0].result;}
assert.equal((await register(user,node)).diagnostics_enabled,false);
await assert.rejects(register(other,node),/node_binding_denied/);
// Exercise the exact upsert's conflict branch after a competing identity has appeared.
// PGlite serializes statements; this tests the vulnerable statement, not real concurrent sessions.
const migration=fs.readFileSync(path.join(dir,'20261013165118_crowd_distributed_nodes.sql'),'utf8');
const upsert=migration.match(/insert into crowd_v4\.nodes\(installation_id,user_id,version,enabled,login_state,release_digest\)[\s\S]*?returning \* into n;/)[0]
 .replace(/\bp_installation\b/g,'$1::uuid').replace(/\bp_state\b/g,'$3::jsonb').replace(/\bu\b/g,'$2::uuid').replace('returning * into n;','returning *;');
assert.equal((await db.query(upsert,[node,other,JSON.stringify({version:'4.2.60',enabled:false,login_state:'needs_login'})])).rows.length,0);
assert.equal((await db.query('select enabled from crowd_v4.nodes where installation_id=$1',[node])).rows[0].enabled,true);
await assert.rejects(register(null,node),/login_required/);
for(const state of [{version:'4.2.60',enabled:true,login_state:'ready',cookie:'secret'},{version:'4.2.60',enabled:true,login_state:'token'},{version:'4.2.60',enabled:true,login_state:'ready',release_digest:'private'}])await assert.rejects(register(user,node,state),/invalid_node/);
const run=await claim(user,node);assert.equal(run.task.id,1);assert.equal(run.node_run.task_id,1);
assert.equal((await claim(user,node)).node_run.run_id,run.node_run.run_id,'renewal keeps one binding and original lease');
await register(user,otherNode);await assert.rejects(claim(user,otherNode),/node_binding_denied/,'same account cannot hand one lease to two installations');
await register(other,'10000000-0000-4000-8000-000000000003');
const second=await claim(other,'10000000-0000-4000-8000-000000000003');assert.equal(second.task.id,2,'different identities receive separate original tasks');
await identity(user);await db.query("select public.crowd_v4_diagnostics('enable',1)");
const event={event_id:'20000000-0000-4000-8000-000000000001',node_seq:1,run_id:run.node_run.run_id,step:'detail',status:'completed',at_ms:Date.now(),duration_ms:1234,error_code:null,counts:{contents:1}};
let ack=await report(user,node,[event]);assert.deepEqual(ack.accepted,[event.event_id]);
ack=await report(user,node,[event]);assert.deepEqual(ack.duplicates,[event.event_id]);assert.equal(ack.max_node_seq,1);
await assert.rejects(report(user,node,[{...event,counts:{contents:2}}]),/event_conflict/);
assert.equal((await report(other,'10000000-0000-4000-8000-000000000003',[event])).discard,true);
// Enable the second participant so cross-account binding is checked beyond opt-out handling.
await identity(other);await db.query("select public.crowd_v4_diagnostics('enable',1)");
await assert.rejects(report(other,'10000000-0000-4000-8000-000000000003',[event]),/node_binding_denied/);
for(const patch of [{cookie:'secret'},{counts:{token:1}},{counts:{contents:100001}},{error_code:'https://secret.invalid'},{node_seq:9007199254740992},{duration_ms:-1},{step:'eval'},{run_id:null}])await assert.rejects(report(user,node,[{...event,...patch}]),/invalid_events|node_binding_denied/);
const next={...event,event_id:'20000000-0000-4000-8000-000000000002',node_seq:2,step:'receipt',counts:{received:1}};
await report(user,node,[next]);
let timeline=await monitor('node_events',{limit:1});assert.equal(timeline.events.length,1);assert.equal(timeline.has_more,true);assert.equal(timeline.events[0].logical_task_id,'participant:1');
assert(!JSON.stringify(timeline).includes(run.task.lease_token),'lease credential never in owner telemetry');
timeline=await monitor('node_events',{after_id:timeline.cursor,limit:1});assert.equal(timeline.events[0].node_seq,2);assert.equal(timeline.has_more,false);
assert.equal((await monitor('node_events',{installation_id:otherNode})).events.length,0);
// Expiry prevents source operations via old guard; historical telemetry can still close its timeline.
await db.exec("update crowd_v4.tasks set lease_until=now()-interval '1 day',status='closed' where id=1");
await report(user,node,[{...next,event_id:'20000000-0000-4000-8000-000000000003',node_seq:3,step:'stop'}]);
let unified=await monitor();assert.equal(unified.tasks.length,2);assert.equal(unified.nodes.length,3);assert.equal(unified.coverage.machine_step_events,'not_integrated');
assert.equal(unified.tasks.find(t=>t.task_id===1).state,'closed');
await db.exec(`insert into crowd_machine.workers(worker_id,owner_scope,token_hash,name,platforms,expires_at) values('30000000-0000-4000-8000-000000000001','crowd-owner-main','${'a'.repeat(64)}','fixture','["bili"]',now()+interval '1 day');
insert into crowd_machine.tasks(task_id,owner_scope,idempotency_key,request_hash,proposal) values('30000000-0000-4000-8000-000000000002','crowd-owner-main','fixture','hash','{"mode":"search"}');
insert into crowd_machine.children(child_id,task_id,platform,plan,state) values('30000000-0000-4000-8000-000000000003','30000000-0000-4000-8000-000000000002','bili','{}','queued');`);
unified=await monitor();assert.equal(unified.tasks.length,3);assert.equal(unified.nodes.length,4);
const machine=unified.tasks.find(t=>t.execution_kind==='machine_worker');assert.equal(machine.state,'queued');assert.equal(machine.source_kind,'machine_api');assert.equal(machine.reward_eligible,false);assert.deepEqual(machine.platforms,['bili']);
await db.exec("update crowd_machine.children set state='running',lease_until=now()-interval '1 second'");
assert.equal((await monitor()).tasks.find(t=>t.execution_kind==='machine_worker').state,'interrupted_unknown','read-only projection does not advertise an expired machine lease as running');
assert.equal((await db.query('select state from crowd_machine.children')).rows[0].state,'running','monitor does not reconcile or redispatch source work');
await identity(user);
await db.query("insert into crowd_v4.receipts(user_id,request,payload,result) values($1,'40000000-0000-4000-8000-000000000001','{\"task\":1,\"record\":{}}','{\"immutable\":true}')",[user]);
assert.deepEqual((await db.query("select public.crowd_v4_submit('40000000-0000-4000-8000-000000000001',1,$1,'{}') result",[run.task.lease_token])).rows[0].result,{immutable:true},'expired closed run preserves exact old receipt');
// Pruning is bounded and observable through monotonic server IDs, not invisible local eviction.
await db.exec(`insert into crowd_v4.node_step_events(installation_id,event_id,node_seq,event) select '${node}',gen_random_uuid(),100+i,'{}' from generate_series(1,2001) i;`);
await report(user,node,[]);assert.equal((await db.query('select count(*)::int n from crowd_v4.node_step_events where installation_id=$1',[node])).rows[0].n,2000);
await db.exec("update crowd_v4.node_step_events set received_at=now()-interval '8 days'");
assert.equal((await monitor('node_events')).events.length,0);await report(user,node,[]);assert.equal((await db.query('select count(*)::int n from crowd_v4.node_step_events')).rows[0].n,0);
const discarded=await report(user,node,[next]);assert.deepEqual(discarded.discarded,[next.event_id]);assert.equal(discarded.discard_reason,'sequence_not_retained');assert.equal(discarded.accepted.length,0);
assert.equal((await db.query('select count(*)::int n from crowd_v4.node_step_events')).rows[0].n,0,'old sequence does not resurrect a log outside retained history');
await identity(user);await db.query("select public.crowd_v4_diagnostics('disable',2)");
assert.equal((await monitor('node_events')).events.length,0,'opt-out clears and suppresses events');
ack=await report(user,node,[next]);assert.equal(ack.discard,true);assert.equal(ack.diagnostics_enabled,false);
assert.equal((await monitor()).nodes.find(n=>n.installation_id===node).login_state,'unknown');
// Opt-out does not block claim. Restore task solely in isolated fixture.
await db.exec("update crowd_v4.tasks set status='leased' where id=1");assert.equal((await claim(user,node)).task.id,1);
await register(user,node,{version:'4.2.60',enabled:false,login_state:'unknown'});assert.equal((await claim(user,node)).task.id,1,'cached disabled status must not block original outbox claim/renewal');
await assert.rejects(monitor('unified_status',{},'worker'),/principal_denied/);
for(const [action,payload] of [['unified_status',{limit:101}],['node_events',{after_id:-1}],['node_events',{installation_id:'token'}],['node_events',{user_id:user}]])await assert.rejects(monitor(action,payload),/invalid_request/);
const acl=(await db.query("select has_function_privilege('anon','public.crowd_v4_node_register(uuid,jsonb)','EXECUTE') anon,has_function_privilege('authenticated','public.crowd_v4_node_register(uuid,jsonb)','EXECUTE') participant,has_function_privilege('authenticated','public.crowd_unified_monitor_rpc(text,text,text,jsonb)','EXECUTE') owner,has_function_privilege('service_role','public.crowd_unified_monitor_rpc(text,text,text,jsonb)','EXECUTE') service,has_table_privilege('authenticated','crowd_v4.node_step_events','SELECT') direct")).rows[0];assert.deepEqual(acl,{anon:false,participant:true,owner:false,service:true,direct:false});
assert.deepEqual((await db.query("select oid::regprocedure::text name,md5(pg_get_functiondef(oid)) hash from pg_proc where pronamespace='public'::regnamespace and proname in ('crowd_v4_claim','crowd_v4_submit','crowd_v4_finish') order by proname")).rows,definitions);
const ownerKey='1'.repeat(64),ownerHash=await sha(ownerKey);let calls=0;
const backend={rpc:async(name,args)=>{calls++;assert.equal(name,'crowd_unified_monitor_rpc');return {data:await monitor(args.p_action,args.p_payload,args.p_actor_kind),error:null};}};
function request(action,headers,payload={}){return new Request('https://unit.invalid',{method:'POST',headers:{'Content-Type':'application/json',...headers},body:JSON.stringify({action,payload})});}
for(const action of ['unified_status','node_events'])assert.equal((await handleMachine(request(action,{'X-Crowd-Owner-Key':ownerKey}),backend,ownerHash)).status,200);
assert.equal(calls,2);assert.equal((await handleMachine(request('node_events',{'X-Crowd-Worker-Key':'2'.repeat(64)}),backend,ownerHash)).status,403);assert.equal(calls,2);
await db.close();console.log('PASS distributed nodes: original claim adapter, opt-out independent claim, identity/installation/run binding, immutable telemetry ACK, incremental owner timeline, private ACLs, original receipt functions unchanged. Isolated fixtures, not physical-device evidence.');
