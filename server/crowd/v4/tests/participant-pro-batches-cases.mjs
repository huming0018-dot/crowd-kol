import fs from 'node:fs';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
export default async function({db,set,sqlPro,who,cohort,tx}){
 for(const d of JSON.parse(fs.readFileSync(new URL('./fixtures/participant-pro/FRESH-NATIVE-BASE.json',import.meta.url),'utf8')))await db.exec(d.definition);
 await db.exec(fs.readFileSync(new URL('../supabase/candidates/participant-pro-batches.sql',import.meta.url),'utf8'));
 const p=who[0],id=21;
 const old=(await db.query('select to_jsonb(t) r from crowd_v4.tasks t where id=19')).rows[0].r;
 await db.query("insert into crowd_v4.tasks(id,source_key,query,anchor_terms,target,received,status,claimed_by,source_executor,action_gap_milliseconds,session_action_limit,session_window_seconds,daily_search_cap,daily_detail_cap) overriding system value values($1,'pro-native-new','fixture restaurant','[\"fixture\"]',2,0,'open',$2,'mediacrawler_pro',1000,100,3600,30,200)",[id,p.u]);
 await db.query('insert into crowd_v4.test_task_owners values($1,$2)',[id,p.u]);await db.query('insert into crowd_v4.pilot_task_map values($1,$2)',[id,cohort]);
 await set(p.u);await assert.rejects(sqlPro('status',[id,p.i]),/pro_scope_denied/);
 await db.query("insert into crowd_v4.participant_pro_batches(task_id,user_id,installation_id,invite_hash,baseline_task,target,expires_at) select id,$2,$3,$4,crowd_v4.acceptance_task_input(t),target,now()+interval '1 hour' from crowd_v4.tasks t where id=$1",[id,p.u,p.i,cohort]);
 const view=async task=>(await db.query('select crowd_v4.acceptance_supplement_view($1,$2) g',[task,p.u])).rows[0].g;
 assert.equal((await view(null)).task_id,id);assert.equal((await view(id)).remaining,2);
 const claim=(await db.query('select public.crowd_v4_node_claim($1,null) r',[p.i])).rows[0].r;
 assert.equal(claim.task?.id,id,JSON.stringify(claim));assert.equal(claim.node_run.installation_id,p.i);
 const pc=await sqlPro('claim',[id,p.i]);assert.equal(pc.acceptance_supplement.remaining,2);assert.equal(pc.task.id,id);
 const lease=pc.task.lease_token;
 await assert.rejects(sqlPro('status',[id,who[1].i]),/pro_scope_denied/);
 await assert.rejects(sqlPro('claim',[id,who[1].i]),/pro_scope_denied|node_binding_denied/);
 await tx(async()=>{await db.query('update crowd_v4.participant_pro_batches set revoked=true where task_id=$1',[id]);assert.equal(await view(id),null);assert.equal((await sqlPro('status',[id,p.i])).task.id,id);await assert.rejects(sqlPro('claim',[id,p.i]),/pro_scope_denied/);});
 await tx(async()=>{await db.query("update crowd_v4.participant_pro_batches set expires_at=now()-interval '1 second' where task_id=$1",[id]);assert.equal(await view(id),null);assert.equal((await sqlPro('status',[id,p.i])).task.id,id);await assert.rejects(sqlPro('claim',[id,p.i]),/pro_scope_denied/);});
 await tx(async()=>{await db.query("update crowd_v4.tasks set query='changed input' where id=$1",[id]);assert.equal(await view(id),null);await assert.rejects(sqlPro('status',[id,p.i]),/pro_scope_denied/);});
 await tx(async()=>{await db.query("update crowd_v4.pilot_experiments set phase='closed' where invite_hash=$1",[cohort]);assert.equal(await view(id),null);await assert.rejects(sqlPro('claim',[id,p.i]),/pro_scope_denied/);});
 await tx(async()=>{await db.query('update crowd_v4.tasks set lease_until=now()-interval \'1 second\' where id=$1',[id]);await assert.rejects(sqlPro('guard',[id,lease,'search',null,p.i]),/lease_expired/);});

 // Reproduce the actual day counts before applying any additional ceiling patch.
 for(const d of JSON.parse(fs.readFileSync(new URL('./fixtures/participant-pro/FRESH-NATIVE-GUARD.json',import.meta.url),'utf8')))await db.exec(d.definition);
 const policyBefore=(await db.query('select to_jsonb(p) r from crowd_v4.policy p')).rows;
 await db.query("update crowd_v4.safety set day=(now() at time zone 'Asia/Shanghai')::date,counts='{\"search\":15,\"detail\":176,\"comment\":38,\"scroll\":200}',next_action=now()-interval '1 second',cooldown_until=now()-interval '1 second',session_count=0 where user_id=$1",[p.u]);
 const note='f'.repeat(24);
 const denied=await sqlPro('guard',[id,lease,'detail',note,p.i]);assert.equal(denied.reason,'action_budget');assert.equal(denied.caps.detail,60);
 await db.exec(fs.readFileSync(new URL('../supabase/candidates/participant-pro-batch-detail-cap.sql',import.meta.url),'utf8'));
 const actualCounts=(await db.query('select counts from crowd_v4.safety where user_id=$1',[p.u])).rows[0].counts;
 assert.equal(actualCounts.detail,176);assert.equal(actualCounts.scroll,200);
 const admitted=await sqlPro('guard',[id,lease,'detail',note,p.i]);assert.equal(admitted.allowed,true,JSON.stringify(admitted));assert.equal(admitted.caps.detail,200);assert.equal(admitted.counts.detail,177);assert.equal(admitted.counts.scroll,200);
 assert.deepEqual((await db.query('select to_jsonb(p) r from crowd_v4.policy p')).rows,policyBefore);
 console.log(JSON.stringify({result:'PASS',scope:'actual day counts detail176 scroll200; prepatch detail budget RED reproduced; scoped task200 permits one and keeps globalpolicy and counters'}));
 assert.deepEqual((await db.query('select to_jsonb(t) r from crowd_v4.tasks t where id=19')).rows[0].r,old);
 const acl=(await db.query("select has_table_privilege('authenticated','crowd_v4.participant_pro_batches','select') participant,has_table_privilege('anon','crowd_v4.participant_pro_batches','select') anon")).rows[0];assert.deepEqual(acl,{participant:false,anon:false});
 console.log(JSON.stringify({result:'PASS',checks:13,scope:'new bounded Pro task selection, old task immutable, node/grant/expiry/input/ACL negative cases'}));
}
