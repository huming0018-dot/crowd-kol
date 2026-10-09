import assert from 'node:assert/strict';
import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import {createRequire} from 'node:module';import {randomUUID} from 'node:crypto';
const {PGlite}=createRequire(import.meta.url)(path.join(process.env.CROWD_TEST_TOOLS,'node_modules/@electric-sql/pglite'));
const databasePath=fs.mkdtempSync(path.join(os.tmpdir(),'crowd-kol-recovery-')),owner=randomUUID(),other=randomUUID();let db=new PGlite(databasePath),cases=0;
try{
 await db.exec(`create role anon;create role authenticated;create role service_role;create schema auth;create table auth.users(id uuid primary key,email text);
 create function auth.uid() returns uuid language sql as $$select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$;
 create function auth.role() returns text language sql as $$select current_setting('request.jwt.claim.role',true)$$;
 grant usage on schema auth to authenticated;grant execute on function auth.uid(),auth.role() to authenticated;`);
 const dir=new URL('../supabase/migrations/',import.meta.url);
 for(const name of fs.readdirSync(dir).filter(name=>name.endsWith('.sql')).sort()){
  try{await db.exec(fs.readFileSync(new URL(name,dir),'utf8'));}catch(error){throw new Error(name+': '+error.message,{cause:error});}
 }
 for(const user of [owner,other]){await db.query('insert into auth.users(id) values($1)',[user]);await db.query("insert into crowd_v4.participants(user_id,status,consent,joined_at) values($1,'approved','crowd-public-v4',clock_timestamp()-interval '30 days')",[user]);}
 async function call(action,payload={},user=owner){await db.query("select set_config('request.jwt.claim.sub',$1,false)",[user]);await db.exec('set role authenticated');try{return (await db.query('select public.crowd_v4_kol($1,$2) r',[action,payload])).rows[0].r;}finally{await db.exec('reset role');}}
 const check=result=>{assert.equal(result.error,undefined,JSON.stringify(result));return result;};
 const waitEnd=()=>db.exec("update crowd_v4.safety set next_action=clock_timestamp()-interval '1 second'");
 const upsert=async url=>check(await call('upsert',{url,label:'KOL test',group:'test'})).target;
 const a=randomUUID(),b=randomUUID(),cid='BV1xx411c7mD',cid2='BV1xx411c7mE';
 const fixture=JSON.parse(fs.readFileSync(new URL('./fixtures/kol-dom-records.json',import.meta.url),'utf8')).records.find(x=>x.platform==='bilibili').record;
 const record=()=>{const r=structuredClone(fixture);r.standard.captured_at=new Date().toISOString();r.standard.note_id=cid;r.standard.url='https://www.bilibili.com/video/'+cid;return r;};
 await call('session_changed',{platform:'bilibili',principal_ref:'a'.repeat(64),verification:'rendered_account_navigation'});
 const target=await upsert(fixture.extra.author.url);let task=check(await call('start',{target_id:target.id,mode:'history',max_items:2,comment_limit:20,comment_depth:2,max_comment_pages:2})).task;
 task=check(await call('claim',{executor_id:a})).task;assert.equal(task.execution_protocol,1);assert.equal(task.max_discovery_scrolls,30);assert.equal(task.max_comment_pages,2);
 assert.equal((await call('claim',{executor_id:b})).reason,'old_executor_required');assert.equal((await call('claim')).reason,'old_executor_required');cases++;
 const params={task:task.id,lease:task.lease_token,executor_id:a};assert.equal((await call('finish',{...params,reason:'observed_only'})).error,'invalid_finish');
 const guard=async(action,id,executor=a,request=randomUUID())=>{await waitEnd();return call('guard',{...params,executor_id:executor,request,action,...(id?{content_id:id}:{})});};
 await db.exec("create function public.kol_test_abort() returns trigger language plpgsql as $$begin raise exception 'fixture_abort';end$$;create trigger kol_test_abort before insert on crowd_kol.source_attempts for each row execute function public.kol_test_abort()");
 await assert.rejects(guard('search'),/fixture_abort/);assert.equal((await call('recovery_status',{task:task.id})).task.attempts.search,0);assert.equal((await db.query('select count(*)::int n from crowd_kol.admissions where owner=$1',[owner])).rows[0].n,0);
 await db.exec('drop trigger kol_test_abort on crowd_kol.source_attempts;drop function public.kol_test_abort()');cases++;
 const searchReq=randomUUID(),search=check(await guard('search',null,a,searchReq));assert.equal(search.allowed,true);
 const replay=await guard('search',null,a,searchReq);assert.equal(replay.allowed,false);assert.equal(replay.replay,true);assert.equal(replay.admission_id,search.admission_id);
 assert.equal((await guard('detail',cid,a,searchReq)).error,'request_reused');
 assert.equal((await call('release',{...params,checkpoint_revision:0,outbox_drained:true})).error,'source_outcome_unknown');
 assert.equal((await call('action_settle',{...params,admission_id:search.admission_id,outcome:'unknown'})).error,'invalid_outcome');
 assert.equal(check(await call('action_settle',{...params,admission_id:search.admission_id,outcome:'observed'})).settled,true);cases++;
 let cp={...params,expected_revision:0,candidate_ids:[cid,cid2],processed_ids:[],scrolls:0,coverage:'partial'};
 assert.equal((await call('checkpoint',{...cp,scrolls:30})).error,'invalid_checkpoint');
 let saved=check(await call('checkpoint',cp));assert.equal(saved.checkpoint.revision,1);assert.equal((await call('checkpoint',cp)).replay,true);
 assert.equal((await call('checkpoint',{...cp,expected_revision:1,processed_ids:[cid]})).error,'receipt_missing');
 assert.equal((await call('checkpoint',{...cp,expected_revision:1,candidate_ids:[]})).error,'checkpoint_gap');
 assert.equal((await call('checkpoint',{...cp,expected_revision:1,candidate_ids:['https://bad/?token=secret']})).error,'invalid_checkpoint');cases++;
 const detail=check(await guard('detail',cid));assert.equal(detail.allowed,true);assert.equal((await guard('detail',cid2)).reason,'source_outcome_unknown');
 assert.equal((await call('action_settle',{...params,admission_id:detail.admission_id,outcome:'observed'})).error,'invalid_outcome');
 const payload={request:randomUUID(),task:task.id,lease:task.lease_token,admission_id:detail.admission_id,record:record()};
 payload.record.extra.media_refs=[{url:'https://a.hdslb.com/test.jpg',kind:'image',source:'rendered_public_dom',status:'discovered_not_downloaded'}];payload.record.extra.media_status='public_refs_available';
 const invalid=structuredClone(payload);invalid.record.extra.media_refs[0].url='https://a.hdslb.com/test?key=secret';assert.equal((await call('submit',invalid)).error,'invalid_media');
 const imageComment={key:'comment-'+(payload.record.extra.comments.items.length+1),parent_key:null,comment_id:'visible-image-1',is_reply:false,author_display:null,content_type:'image',is_placeholder:true,text:'',original_length:0,truncated:false,media_count:1,reported_reply_count:null};payload.record.extra.comments.items.push(imageComment);payload.record.extra.comments.captured_count++;
 const fakeImage=structuredClone(payload);fakeImage.record.extra.comments.items.at(-1).is_placeholder=false;assert.equal((await call('submit',fakeImage)).error,'invalid_comments');
 const fakeText=structuredClone(payload);fakeText.record.extra.comments.items.at(-1).text='想象的图片文字';assert.equal((await call('submit',fakeText)).error,'invalid_comments');
 const receipt=check(await call('submit',payload));assert.equal(receipt.gate,'received');assert.deepEqual(await call('submit',payload),receipt);const imageEntity=(await call('detail',{platform:'bilibili',content_id:cid})).comment_entities.find(x=>x.comment_id==='visible-image-1');assert.equal(imageEntity.is_placeholder,true);assert.equal(imageEntity.content_type,'image');assert.equal(imageEntity.media_count,1);assert.equal(imageEntity.reported_reply_count,null);cases++;
 assert.equal((await call('release',{...params,checkpoint_revision:1,outbox_drained:true})).error,'checkpoint_missing_receipts');
 cp={...cp,expected_revision:1,candidate_ids:[cid2],processed_ids:[cid]};saved=check(await call('checkpoint',cp));assert.equal(saved.checkpoint.revision,2);cases++;
 for(let i=0;i<2;i++){const comment=check(await guard('comment',cid));assert.equal(comment.allowed,true);check(await call('action_settle',{...params,admission_id:comment.admission_id,outcome:'observed'}));}
 assert.equal((await guard('comment',cid)).reason,'comment_page_budget');cases++;
 const usage=(await call('recovery_status',{task:task.id})).task.attempts;
 assert.equal(check(await call('release',{...params,checkpoint_revision:2,outbox_drained:true})).released,true);
 assert.equal((await guard('search')).reason,'executor_released');assert.equal((await call('recover',{task:task.id,executor_id:b},other)).error,'task_missing');
 task=check(await call('recover',{task:task.id,executor_id:b})).task;assert.deepEqual(task.attempts,usage);assert.equal(task.executor_id,b);assert.deepEqual(task.checkpoint.processed_ids,[cid]);const recoveredAgain=check(await call('recover',{task:task.id,executor_id:b})).task;assert.deepEqual(recoveredAgain,task);cases++;
 assert.equal((await guard('search')).error,'executor_mismatch');assert.equal((await call('checkpoint',{...cp,expected_revision:2})).error,'executor_mismatch');assert.equal((await call('finish',{...params,reason:'completed'})).error,'executor_mismatch');
 assert.deepEqual(await call('submit',payload),receipt);assert.equal((await guard('detail',cid,b)).reason,'content_already_received');
 const resumed=check(await guard('search',null,b));assert.equal(resumed.allowed,true);check(await call('action_settle',{...params,executor_id:b,admission_id:resumed.admission_id,outcome:'observed'}));cases++;
 await db.query("update crowd_kol.tasks set lease_until=clock_timestamp()-interval '1 second' where id=$1",[task.id]);
 assert.equal((await call('claim',{executor_id:b})).reason,'lease_expired_requires_release');
 check(await call('release',{...params,executor_id:b,checkpoint_revision:2,outbox_drained:true}));task=check(await call('recover',{task:task.id,executor_id:a})).task;assert.equal(task.attempts.search,2);cases++;
 const speech={platform:'bilibili',content_id:cid,kind:'transcript',authorization_ref:'local-test',evidence:{source_kind:'authorized_local_file',asset_sha256:'d'.repeat(64),observed_at:new Date().toISOString(),raw_text:'本机音频转录',processor:'faster_whisper_local'}};
 assert.ok(check(await call('attach_evidence',speech)).evidence_id);cases++;
 check(await call('release',{...params,checkpoint_revision:2,outbox_drained:true}));await call('session_changed',{platform:'bilibili',principal_ref:'b'.repeat(64),verification:'rendered_account_navigation'});
 assert.equal((await call('recover',{task:task.id,executor_id:b})).error,'recovery_not_active');assert.deepEqual(await call('submit',payload),receipt);cases++;
 // Unknown dispatch blocks new task claiming even after the old task stops, until its original evidence arrives.
 await call('start',{target_id:target.id,max_items:2,comment_limit:20,comment_depth:2});const unknown=check(await call('claim',{executor_id:a})).task;
 await waitEnd();const admitted=check(await call('guard',{task:unknown.id,lease:unknown.lease_token,executor_id:a,request:randomUUID(),action:'detail',content_id:cid2}));assert.equal(admitted.allowed,true);
 check(await call('finish',{task:unknown.id,lease:unknown.lease_token,executor_id:a,reason:'partial'}));await call('start',{target_id:target.id});assert.equal((await call('claim',{executor_id:b})).reason,'source_outcome_unknown');
 const late=record();late.standard.note_id=cid2;late.standard.url='https://www.bilibili.com/video/'+cid2;
 assert.equal(check(await call('submit',{request:randomUUID(),task:unknown.id,lease:unknown.lease_token,admission_id:admitted.admission_id,record:late})).gate,'received');assert.ok(check(await call('claim',{executor_id:b})).task);cases++;
 assert.equal((await db.query('select count(*)::int n from crowd_v4.rewards')).rows[0].n,0);
 assert.equal((await db.query("select has_function_privilege('authenticated','crowd_kol.rpc_base(text,jsonb)','execute') b")).rows[0].b,false);
 assert.equal((await db.query("select has_table_privilege('authenticated','crowd_kol.source_attempts','select') b")).rows[0].b,false);cases++;
 // Scan windows are server-fixed; partial DOM observations never establish complete coverage.
 const scanner=randomUUID();await db.query('insert into auth.users(id) values($1)',[scanner]);await db.query("insert into crowd_v4.participants(user_id,status,consent,joined_at) values($1,'approved','crowd-public-v4',clock_timestamp()-interval '30 days')",[scanner]);
 const scanTarget=check(await call('upsert',{url:'https://space.bilibili.com/99999'},scanner)).target;
 assert.equal((await call('start',{target_id:scanTarget.id,mode:'periodic',window_days:1},scanner)).error,'invalid_overlap_window');
 const shortCycle=await call('start',{target_id:scanTarget.id,mode:'periodic',window_days:2,interval_minutes:720},scanner);assert.equal(shortCycle.error,'invalid_overlap_window');assert.equal(shortCycle.required_window_days,3);
 let scanTask=check(await call('start',{target_id:scanTarget.id,mode:'periodic',window_days:7,max_comment_pages:3},scanner)).task;assert.equal(scanTask.overlap_hours,48);assert.equal(Date.parse(scanTask.scan_until)-Date.parse(scanTask.scan_from),7*86400000);
 scanTask=check(await call('claim',{executor_id:a},scanner)).task;assert.equal((await call('list',{},scanner)).targets[0].last_attempted_scan,null);
 await waitEnd();const scanGrant=check(await call('guard',{task:scanTask.id,lease:scanTask.lease_token,executor_id:a,request:randomUUID(),action:'search'},scanner));assert.equal(scanGrant.allowed,true);
 assert.ok((await call('list',{},scanner)).targets[0].last_attempted_scan);assert.equal((await call('list',{},scanner)).targets[0].last_complete_coverage,null);
 check(await call('action_settle',{task:scanTask.id,lease:scanTask.lease_token,executor_id:a,admission_id:scanGrant.admission_id,outcome:'observed'},scanner));
 check(await call('finish',{task:scanTask.id,lease:scanTask.lease_token,executor_id:a,reason:'error'},scanner));
 assert.equal((await call('start',{target_id:scanTarget.id,mode:'periodic',window_days:3},scanner)).error,'incomplete_window_outside_authorization');
 assert.equal((await call('list',{},scanner)).targets[0].last_complete_coverage,null);
 const expanded=check(await call('start',{target_id:scanTarget.id,mode:'periodic',window_days:8,max_comment_pages:3},scanner)).task;assert.ok(Date.parse(expanded.scan_from)<Date.parse(scanTask.scan_from));assert.equal(expanded.overlap_hours,48);
 await db.exec("update crowd_v4.note_reservations set expires_at=clock_timestamp()-interval '1 second'"); // Separate fixture owners share the real reservation guard.
 const expandedLease=check(await call('claim',{executor_id:a},scanner)).task;await waitEnd();const expandedGrant=check(await call('guard',{task:expandedLease.id,lease:expandedLease.lease_token,executor_id:a,request:randomUUID(),action:'detail',content_id:cid},scanner));assert.equal(expandedGrant.allowed,true,JSON.stringify(expandedGrant));
 const scanRecord=record();scanRecord.extra.author={id:'99999',url:'https://space.bilibili.com/99999'};delete scanRecord.extra.comments;scanRecord.standard.published_at=new Date(expanded.scan_from).toISOString().slice(0,10);
 const scanPayload={request:randomUUID(),task:expandedLease.id,lease:expandedLease.lease_token,admission_id:expandedGrant.admission_id,record:scanRecord};const tooOld=structuredClone(scanPayload);tooOld.record.standard.published_at=new Date(Date.parse(expanded.scan_from)-2*86400000).toISOString().slice(0,10);assert.equal((await call('submit',tooOld,scanner)).error,'outside_window');
 assert.equal(check(await call('submit',scanPayload,scanner)).gate,'received');assert.equal(check(await call('finish',{task:expandedLease.id,lease:expandedLease.lease_token,executor_id:a,reason:'completed'},scanner)).task.reason,'observed_only');
 const afterOldFault=check(await call('start',{target_id:scanTarget.id,mode:'periodic',window_days:3},scanner)).task;assert.ok(afterOldFault.id);assert.equal((await call('list',{},scanner)).targets[0].last_complete_coverage,null);cases++;
 // Typed visible source failures are retained without a false content receipt.
 const failedTask=check(await call('claim',{executor_id:a},scanner)).task;await waitEnd();const failedGrant=check(await call('guard',{task:failedTask.id,lease:failedTask.lease_token,executor_id:a,request:randomUUID(),action:'search'},scanner));assert.equal(failedGrant.allowed,true);
 const failedArgs={task:failedTask.id,lease:failedTask.lease_token,executor_id:a,admission_id:failedGrant.admission_id,outcome:'failed',failure_reason:'source_private'};
 assert.equal((await call('action_settle',{...failedArgs,failure_reason:'private://secret'},scanner)).error,'invalid_outcome');assert.equal(check(await call('action_settle',failedArgs,scanner)).state,'failed');
 assert.equal((await call('action_settle',{...failedArgs,failure_reason:'source_deleted'},scanner)).error,'outcome_conflict');
 const failedFinish=check(await call('finish',{task:failedTask.id,lease:failedTask.lease_token,executor_id:a,reason:'error',detail_reason:'source_private'},scanner)).task;assert.equal(failedFinish.reason,'source_private');assert.equal(failedFinish.received,0);await call('start',{target_id:scanTarget.id,mode:'manual'},scanner);const parserTask=check(await call('claim',{executor_id:a},scanner)).task;assert.equal(check(await call('finish',{task:parserTask.id,lease:parserTask.lease_token,executor_id:a,reason:'error',detail_reason:'parser_paused'},scanner)).task.reason,'parser_paused');cases++;
 // Two real Agent instances hand off a two-page list; only receiver calls replay a lost ACK.
 const traveler=randomUUID();await db.query('insert into auth.users(id) values($1)',[traveler]);await db.query("insert into crowd_v4.participants(user_id,status,consent,joined_at) values($1,'approved','crowd-public-v4',clock_timestamp()-interval '30 days')",[traveler]);
 await call('session_changed',{platform:'bilibili',principal_ref:'d'.repeat(64),verification:'rendered_account_navigation'},traveler);
 const travelTarget=check(await call('upsert',{url:fixture.extra.author.url},traveler)).target;
 await db.exec("update crowd_v4.note_reservations set expires_at=clock_timestamp()-interval '1 second'");
 await import('../../../../../crawler-extension/v4/src/kol.js');
 const sourceDetails=[],submits=new Map();let lost=false;
 function device(){const storage=new Map([['session',{user:{id:traveler}}]]);let time=Date.now(),depth=0,currentId=null;
  const runtime={storage:{get:async k=>structuredClone(storage.get(k)),set:async(k,v)=>storage.set(k,structuredClone(v))},now:()=>time,uuid:randomUUID,schedule:async()=>{},cancel:async()=>{},close:async()=>{},verifyPrincipal:async()=>true,
   open:async url=>{if(url.includes('/video/BV')){currentId=url.match(/BV[0-9A-Za-z]{10}/)[0];sourceDetails.push(currentId);}else{depth=0;currentId=null;}},
   probe:async({action})=>{if(action==='listing_scroll'){depth++;return {ready:true};}if(action==='discover')return {ready:true,creator_id:fixture.extra.author.id,links:(depth?[cid,cid2]:[cid]).map(id=>'https://www.bilibili.com/video/'+id),pagination:{end_observed:depth>0}};
    const r=record();r.standard.note_id=currentId;r.standard.url='https://www.bilibili.com/video/'+currentId;delete r.extra.comments;r.extra.comment_status='not_requested';r.extra.replies_status='not_requested';return {ready:true,record:r};}};
  const agent=new globalThis.CrowdKOL.Agent(runtime,{rpc:async(name,p)=>{const r=await call(p.p_action,p.p_payload,traveler);if(p.p_action==='submit'){submits.set(p.p_payload.request,(submits.get(p.p_payload.request)||0)+1);if(!lost){lost=true;throw new Error('backend_unavailable');}}return r;}});
  return {agent,step:async()=>{await waitEnd();time+=60000;await agent.tick();return agent.read(traveler);}};
 }
 const firstDevice=device();await firstDevice.agent.start({target_id:travelTarget.id,mode:'history',max_items:2,comment_limit:0});let firstState;
 for(let step=0;step<25;step++){firstState=await firstDevice.step();if(firstState.received===1)break;}
 assert.equal(firstState.received,1,JSON.stringify(firstState));assert.ok(firstState.task);const handoffTask=firstState.task.id;
 assert.deepEqual(sourceDetails,[cid]);const released=await firstDevice.agent.release();assert.equal(released.released,true);assert.deepEqual(released.checkpoint.candidate_ids,[cid2]);assert.deepEqual(released.checkpoint.processed_ids,[cid]);
 const secondDevice=device();await secondDevice.agent.recover(handoffTask);let lastState;
 for(let step=0;step<25;step++){lastState=await secondDevice.step();if(lastState.received===1&&!lastState.task)break;}
 assert.equal(lastState.received,1,JSON.stringify(lastState));assert.equal(lastState.task,null);assert.deepEqual(sourceDetails,[cid,cid2]);assert.equal([...submits.values()].sort().join(','),'1,2');
 const finalTask=(await call('recovery_status',{task:handoffTask},traveler)).task;assert.equal(finalTask.attempts.detail,2);assert.equal(finalTask.attempts.search,2);assert.equal(finalTask.attempts.scroll,2);assert.deepEqual(finalTask.checkpoint.processed_ids,[cid,cid2]);assert.equal(finalTask.reason,'observed_only');assert.ok(check(await call('start',{target_id:travelTarget.id,mode:'periodic',window_days:30},traveler)).task);cases++;
 // Real Agent sees only already-received IDs: zero new content is a valid bounded observation.
 const knownDevice=device();await knownDevice.agent.start({target_id:travelTarget.id,mode:'periodic',window_days:30,max_items:2,comment_limit:0});let knownState;
 for(let step=0;step<25;step++){knownState=await knownDevice.step();if(!knownState.task&&knownState.checkpoint_revision>0)break;}
 assert.equal(knownState.task,null,JSON.stringify(knownState));assert.equal(knownState.received,0);assert.deepEqual(sourceDetails,[cid,cid2]);
 const knownTask=(await call('list',{},traveler)).tasks.find(x=>x.id!==handoffTask);assert.equal(knownTask.reason,'observed_only');assert.equal(knownTask.state,'partial');assert.equal(knownTask.received,0);
 assert.ok(check(await call('start',{target_id:travelTarget.id,mode:'periodic',window_days:30},traveler)).task);cases++;
 await db.close();db=new PGlite(databasePath);const diskTask=(await call('recovery_status',{task:handoffTask},traveler)).task;assert.deepEqual(diskTask.checkpoint,finalTask.checkpoint);assert.deepEqual(diskTask.attempts,finalTask.attempts);cases++;
 console.log(`PASS KOL recovery: ${cases} scenario groups; real SQL, explicit handoff, receipt-authoritative checkpoint, retained budgets and unknown attempts`);
}catch(error){console.error(error.stack,error.cause?.message,error.cause?.where,error.where);process.exitCode=1;}finally{await db.close();fs.rmSync(databasePath,{recursive:true,force:true});}
