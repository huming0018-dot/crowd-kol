// Reuse real pilot enrollment/setup and deployed SQL definitions in an isolated DB.
import fs from 'node:fs';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
if(!process.env.CROWD_PILOT_TERMINAL_FIXTURE)throw new Error('Set CROWD_PILOT_TERMINAL_FIXTURE');
const original=new URL('./pilot-cohort-db.mjs',import.meta.url);
const originalSource=fs.readFileSync(original,'utf8');
const split='const otherMembers=[];';
if(originalSource.split(split).length!==2)throw new Error('pilot_setup_anchor_changed');
const source=originalSource.split(split)[0].replaceAll('import.meta.url',JSON.stringify(original.href))+'\n'+fs.readFileSync(fileURLToPath(import.meta.url),'utf8').split('// @isolated-body\n')[1];
const result=spawnSync(process.execPath,['--input-type=module','--eval',source],{encoding:'utf8',env:process.env,maxBuffer:1024*1024});
if(result.error)throw result.error;
process.stdout.write(result.stdout||'');
if(result.status!==0)process.stderr.write((result.stderr||'').slice(-4000));
process.exit(result.status===0?0:(Number.isInteger(result.status)&&result.status>0?result.status:1));

// @isolated-body
process.on('uncaughtException',error=>{console.error(error.message,error.where||'');process.exit(1);});
await db.exec("create schema crowd_machine;create table crowd_machine.unified_dispatches(dispatch_id uuid,pilot_invite_hash text);create table crowd_machine.unified_participant_tasks(dispatch_id uuid,task_id bigint);");
await db.exec(fs.readFileSync(process.env.CROWD_PILOT_TERMINAL_FIXTURE,'utf8'));
for(const name of ['20261007051154_crowd_v4_diagnostics.sql','20261013135950_crowd_v4_participant_health_history.sql','20261013165118_crowd_distributed_nodes.sql'])await db.exec(fs.readFileSync(path.join(migrations,name),'utf8'));
const migration=fs.readFileSync(path.join(migrations,'20261014021213_crowd_v4_pilot_acceptance_terminal.sql'),'utf8');
const functions=async()=>(await db.query("select oid::regprocedure::text name,pg_get_functiondef(oid) definition,proacl::text acl from pg_proc where pronamespace in ('public'::regnamespace,'crowd_v4'::regnamespace,'crowd_observation'::regnamespace) order by name")).rows;
const beforeFunctions=await functions();
const claim=async(task=null)=>(await db.query('select public.crowd_v4_claim($1) result',[task])).rows[0].result;
const block=async task=>(await db.query('select crowd_v4.pilot_block_reason($1,$2) result',[task,member])).rows[0].result;
await db.query("select set_config('request.jwt.claim.sub',$1,false)",[member]);
await db.query("select public.crowd_v4_node_register($1,'{\"version\":\"4.2.65\",\"enabled\":true,\"login_state\":\"ready\"}')",[member]);
const lease=(await claim()).task;assert.equal(lease.id,13);
const second=(await claim()).task;assert.equal(second.lease_token,lease.lease_token);
for(let i=1;i<=2;i++)await db.query('insert into crowd_v4.proofs(note_id,user_id,task_id,record) values($1,$2,13,$3::jsonb)',[String(i).padStart(24,'0'),member,JSON.stringify({fixture:true})]);
await db.exec('update crowd_v4.tasks set received=2 where id=13');
await db.query("insert into crowd_v4.receipts(user_id,request,payload,result) values($1,'00000000-0000-4000-8000-000000000011','{\"task\":13,\"record\":{}}','{\"inserted\":true,\"proof\":1,\"immutable\":true}')",[member]);
assert.equal(await block(13),'task_full','reproduce deployed reason priority defect');
assert.equal((await claim()).error,'daily_quota','reproduce tomorrow retry instead of acceptance complete');
const snapshot=async()=>(await db.query("select (select jsonb_agg(to_jsonb(t) order by id) from crowd_v4.tasks t) tasks,(select jsonb_agg(to_jsonb(p) order by id) from crowd_v4.proofs p) proofs,(select jsonb_agg(to_jsonb(r) order by request) from crowd_v4.receipts r) receipts")).rows[0];
const dataBefore=await snapshot();await db.exec(migration);assert.deepEqual(await snapshot(),dataBefore,'migration is definitions only, no task/lease/proof/receipt mutation');
const afterFunctions=await functions();
assert.deepEqual(afterFunctions.filter(f=>!['crowd_v4.pilot_block_reason(bigint,uuid)','crowd_v4_claim(bigint)'].includes(f.name)),beforeFunctions.filter(f=>!['crowd_v4.pilot_block_reason(bigint,uuid)','crowd_v4_claim(bigint)'].includes(f.name)),'all other functions incl submit/guard remain byte exact');
assert.deepEqual(afterFunctions.map(f=>[f.name,f.acl]),beforeFunctions.map(f=>[f.name,f.acl]),'ACLs unchanged');
const expected={error:'test_completed',pilot_phase:'awaiting_acceptance'};
assert.equal(await block(13),'test_completed');assert.equal(await block(14),'test_completed');assert.equal(await block(null),'test_completed');
for(const task of [null,13,14])assert.deepEqual(await claim(task),expected);
assert.deepEqual((await db.query('select public.crowd_v4_node_claim($1,null) result',[member])).rows[0].result,expected,'actual node adapter propagates completion without wrapping a task');
assert.deepEqual(await snapshot(),dataBefore,'completion query must not extend lease or take second task');
// A single accepted proof and an unrelated cohort proof cannot complete this cohort.
await db.exec('begin');await db.exec("delete from crowd_v4.proofs where note_id='000000000000000000000002';update crowd_v4.tasks set received=1 where id=13");
assert.equal(await block(13),null);assert.equal((await claim()).task.id,13);await db.exec('rollback');
await db.exec('begin');
await db.query("insert into crowd_v4.invites(token_hash,expires_at,max_people,quota_day) values($1,now()+interval '1 day',2,2)",['c'.repeat(64)]);
await db.query('insert into crowd_v4.pilot_experiments(invite_hash) values($1)',['c'.repeat(64)]);
await db.query('insert into crowd_v4.pilot_task_map(task_id,invite_hash) values(12,$1)',['c'.repeat(64)]);
await db.exec("update crowd_v4.proofs set task_id=12 where note_id='000000000000000000000002';update crowd_v4.proofs set received_at=now()-interval '2 days';update crowd_v4.tasks set received=1 where id=13");
assert.equal(await block(13),null);assert.equal(await block(12),'user_stopped');assert.equal((await claim()).task.id,13);await db.exec('rollback');
// The public guard retains its real wrapper and sends denied source work through control only.
for(const action of ['control','search','detail','comment','scroll']){
 const value=(await db.query('select public.crowd_v4_guard($1,13,null) result',[action])).rows[0].result;
 assert.equal(value.reason,'test_completed');assert.equal(value.pilot_phase,'awaiting_acceptance');assert.equal(value.allowed,false);
}
assert((await db.query('select action from crowd_observation.guard_calls')).rows.every(r=>r.action==='control'));
const receipt=(await db.query("select public.crowd_v4_submit('00000000-0000-4000-8000-000000000011',13,$1,'{}') result",[lease.lease_token])).rows[0].result;
assert.deepEqual(receipt,{inserted:true,proof:1,immutable:true},'exact stored ACK survives terminal state');
await db.query("update crowd_v4.proofs set received_at=now()-interval '2 days' where user_id=$1",[member]);
for(const task of [null,13,14])assert.deepEqual(await claim(task),expected,'acceptance cap remains terminal across midnight');
// Consent and approval still run before terminal completion.
await db.query("update crowd_v4.participants set status='suspended' where user_id=$1",[member]);await assert.rejects(claim(),/approval_required/);
await db.query("update crowd_v4.participants set status='approved' where user_id=$1",[member]);
await assert.rejects(db.query("update crowd_v4.participants set consent='other-consent' where user_id=$1",[member]),/participants_consent_check/,'database rejects invalid consent before RPC');
assert.deepEqual(await claim(),expected);
// Existing active experiment and ordinary account behavior is unchanged.
await db.exec("update crowd_v4.pilot_experiments set phase='active',armed_at=now(),ends_at=now()+interval '48 hours'");
assert.equal(await block(13),'task_full');assert.equal((await claim()).task.id,14);
await db.query('update crowd_v4.proofs set received_at=now() where user_id=$1',[member]);assert.equal((await claim()).error,'daily_quota');
await db.exec("update crowd_v4.pilot_experiments set phase='awaiting_acceptance',armed_at=null,ends_at=null");
await db.exec('update crowd_v4.invites set revoked=true');assert.equal(await block(13),'user_stopped');assert.notDeepEqual(await claim(),expected,'revoked invitations do not become completed acceptance');
await db.exec('update crowd_v4.invites set revoked=false');
await db.query("select set_config('request.jwt.claim.sub',$1,false)",[outsider]);assert.equal((await claim()).task.id,12,'nonpilot still claims ordinary task');
await db.query("select set_config('request.jwt.claim.sub','',false)");await assert.rejects(claim(),/login_required/);
await assert.rejects(db.exec(migration),/pilot_terminal_reason_anchor_mismatch/,'second apply cannot silently change another function shape');await db.exec('rollback');
assert.equal((await db.query('select count(*)::int n from crowd_v4.proofs')).rows[0].n,2);
assert.equal((await db.query('select count(*)::int n from crowd_v4.receipts')).rows[0].n,1);
await db.close();
console.log('PASS pilot acceptance terminal: deployed defect reproduced; exact two-definition patch; waiting completion before full-task/daily quota; cross-midnight completion; approval/consent/cohort/active/ordinary guards; no lease/count/receipt changes; stored ACK intact. Isolated PGlite, real wrappers, source guard/validator fixtures only.');
