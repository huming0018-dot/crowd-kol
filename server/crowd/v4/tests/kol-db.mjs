import assert from 'node:assert/strict';
import fs from 'node:fs';import path from 'node:path';import {createRequire} from 'node:module';import {randomUUID} from 'node:crypto';
const {PGlite}=createRequire(import.meta.url)(path.join(process.env.CROWD_TEST_TOOLS,'node_modules/@electric-sql/pglite'));
const db=new PGlite(),owner=randomUUID(),other=randomUUID();let cases=0;
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
 let target=await upsert('https://www.xiaohongshu.com/user/profile/'+ 'b'.repeat(24)+'?xsec_token=not-stored#foo');
 assert.equal(target.url,'https://www.xiaohongshu.com/user/profile/'+'b'.repeat(24));assert.equal(target.group,'test');
 assert.equal((await upsert(target.url)).id,target.id);assert.equal((await call('list')).targets.length,1);assert.equal((await call('list',{},other)).targets.length,0);cases++;
 let task=check(await call('start',{target_id:target.id,max_items:2,comment_limit:2,comment_depth:2})).task;
 task=check(await call('claim')).task;assert.equal(task.principal_ref,null);assert.equal(task.principal_verification,'unverified');assert.equal(task.target_id,'b'.repeat(24));assert.equal(task.include_replies,true);assert.equal(task.max_items,2);
 assert.equal((await db.query("select count(*)::int n from crowd_v4.tasks where status='leased'")).rows[0].n,0);cases++;
 assert.equal((await call('guard',{task:task.id,lease:task.lease_token,action:'detail',content_id:'a'.repeat(24)},other)).allowed,false);cases++;
 let g=check(await call('guard',{task:task.id,lease:task.lease_token,action:'detail',content_id:'a'.repeat(24)}));assert.equal(g.allowed,true);assert.ok(g.admission_id);
 assert.equal((await db.query("select status from crowd_v4.tasks where source_key like 'kol:%'")).rows[0].status,'closed');
 assert.equal((await call('guard',{task:task.id,lease:task.lease_token,action:'detail',content_id:'c'.repeat(24)})).reason,'action_gap');cases++;
 function record(platform='xiaohongshu',id='a'.repeat(24),creator='b'.repeat(24)){
  return {schema_version:4,standard:{platform,note_id:id,url:platform==='xiaohongshu'?'https://www.xiaohongshu.com/explore/'+id:'https://www.bilibili.com/video/'+id,title:'公开内容测试',captured_at:new Date().toISOString(),published_at:null,author_display:null,like_count:null,collect_count:null,comment_count:2,view_count:null},
   extra:{author:{id:creator,url:platform==='xiaohongshu'?'https://www.xiaohongshu.com/user/profile/'+creator:'https://space.bilibili.com/'+creator},author_opinion_quotes:[],comments:{items:[{key:'comment-1',parent_key:null,text:'根评论',original_length:3,truncated:false},{key:'comment-2',parent_key:'comment-1',text:'回复',original_length:2,truncated:false}],coverage:'visible_loaded_only',complete:false,captured_count:2,truncated:false}},
   evidence:{text:'公开原文',original_length:4,truncated:false,parser_version:'4.3.0',source:'rendered_public_dom'}};
 }
 let payload={request:randomUUID(),task:task.id,lease:task.lease_token,admission_id:g.admission_id,record:record()};
 const wrong=structuredClone(payload);wrong.record.extra.author.id='f'.repeat(24);wrong.record.extra.author.url='https://www.xiaohongshu.com/user/profile/'+'f'.repeat(24);assert.equal((await call('submit',wrong)).error,'author_mismatch');cases++;
 const receipt=check(await call('submit',payload));assert.equal(receipt.gate,'received');assert.equal(receipt.reward_eligible,false);assert.equal((await db.query('select count(*)::int n from crowd_kol.comment_entities')).rows[0].n,0,'missing real IDs remain sample-only');assert.deepEqual(await call('submit',payload),receipt);
 const changed=structuredClone(payload);changed.record.evidence.text='内容改变';assert.equal((await call('submit',changed)).error,'request_reused');
 assert.equal((await db.query('select count(*)::int n from crowd_v4.proofs')).rows[0].n,0);assert.equal((await db.query('select count(*)::int n from crowd_v4.rewards')).rows[0].n,0);cases++;
 await waitEnd();const g2=check(await call('guard',{task:task.id,lease:task.lease_token,action:'detail',content_id:'c'.repeat(24)}));assert.equal(g2.allowed,true);
 await waitEnd();assert.equal((await call('guard',{task:task.id,lease:task.lease_token,action:'detail',content_id:'d'.repeat(24)})).reason,'task_budget');cases++;
 await call('stop',{target_id:target.id});assert.equal((await call('guard',{task:task.id,lease:task.lease_token,action:'search'})).reason,'lease_expired');
 const late={...payload,request:randomUUID(),admission_id:g2.admission_id,record:record('xiaohongshu','c'.repeat(24))};
 late.record.extra.comments.items[0].is_reply=false;late.record.extra.comments.items[1].is_reply=true;late.record.extra.comments.items[1].comment_id='orphan-reply';
 assert.equal(check(await call('submit',late)).gate,'received');assert.deepEqual(await call('submit',payload),receipt);
 const orphan=check(await call('detail',{platform:'xiaohongshu',content_id:'c'.repeat(24)})).comment_entities[0];assert.equal(orphan.relationship_status,'orphan');assert.equal(orphan.parent_comment_id,null);assert.equal(orphan.root_comment_id,null);cases++;
 const list=await call('list');assert.equal(list.contents.length,2);assert.equal(list.contents[0].metrics.like_count,null);assert.equal((await call('export',{target_id:target.id})).contents.length,2);
 assert.equal((await call('export',{target_id:target.id},other)).error,'target_missing');cases++;
 await call('delete_target',{target_id:target.id});assert.equal((await call('list')).targets.length,0);assert.equal((await call('list')).contents.length,2);cases++;
 await call('delete_content',{platform:'xiaohongshu',content_id:'a'.repeat(24)});assert.deepEqual(await call('submit',payload),receipt);assert.equal((await call('list')).contents.length,1);cases++;
 // Bilibili uses its actual identity, while sharing the original source-action guard counters.
 target=await upsert('https://space.bilibili.com/12345/');await call('start',{target_id:target.id,max_items:2,comment_limit:2,comment_depth:2});task=check(await call('claim')).task;
 await waitEnd();g=check(await call('guard',{task:task.id,lease:task.lease_token,action:'detail',content_id:'BV1xx411c7mD'}));assert.equal(g.allowed,true);
 payload={request:randomUUID(),task:task.id,lease:task.lease_token,admission_id:g.admission_id,record:record('bilibili','BV1xx411c7mD','12345')};
 assert.equal(check(await call('submit',payload)).gate,'received');assert.equal((await call('list')).contents.some(row=>row.platform==='bilibili'),true);cases++;
 await call('finish',{task:task.id,lease:task.lease_token,reason:'completed'});
 await call('start',{target_id:target.id,max_items:2,comment_limit:2,comment_depth:2});task=check(await call('claim')).task;await waitEnd();g=check(await call('guard',{task:task.id,lease:task.lease_token,action:'detail',content_id:'BV1xx411c7mD'}));
 payload={...payload,request:randomUUID(),task:task.id,lease:task.lease_token,admission_id:g.admission_id,record:record('bilibili','BV1xx411c7mD','12345')};payload.record.evidence.text='新版正文';
 assert.equal(check(await call('submit',payload)).version,2);assert.equal((await db.query("select count(*)::int n from crowd_kol.versions where platform='bilibili'")).rows[0].n,2);cases++;
 const epoch=check(await call('session_changed')).credential_epoch;assert.equal(epoch,2);assert.equal((await call('guard',{task:task.id,lease:task.lease_token,action:'search'})).allowed,false);cases++;
 const periodic=await upsert('https://www.bilibili.com/video/BV1xx411c7mD');await call('start',{target_id:periodic.id,mode:'periodic',interval_minutes:60});const pt=check(await call('claim')).task;assert.equal(pt.mode,'periodic');cases++;
 // Server truth: zero ACK cannot be called completed; creator batches remain observed-only.
 const noAck=check(await call('finish',{task:pt.id,lease:pt.lease_token,reason:'completed'})).task;
 assert.equal(noAck.state,'partial');assert.equal(noAck.reason,'no_received_content');cases++;
 // Real Chromium parser fixtures, not a separately hand-built accepted shape.
 const fixtures=JSON.parse(fs.readFileSync(new URL('./fixtures/kol-dom-records.json',import.meta.url),'utf8'));
 let lastContent;
 for(const sample of fixtures.records){
  const actual=structuredClone(sample.record);actual.standard.captured_at=new Date().toISOString(); // Test time only; DOM fields unchanged.
  target=await upsert(actual.extra.author.url);await call('start',{target_id:target.id,max_items:2,comment_limit:20,comment_depth:2});task=check(await call('claim')).task;
  await waitEnd();g=check(await call('guard',{task:task.id,lease:task.lease_token,action:'detail',content_id:actual.standard.note_id}));assert.equal(g.allowed,true);
  const realPayload={request:randomUUID(),task:task.id,lease:task.lease_token,admission_id:g.admission_id,record:actual};
  const first=check(await call('submit',realPayload));assert.equal(first.gate,'received');
  const detail=check(await call('detail',{platform:sample.platform,content_id:actual.standard.note_id}));assert.ok(detail.metric_snapshots.length);
  assert.equal(detail.content.metrics.observations.like_count.status,actual.extra.field_observations.like_count.status);
  assert.equal((await call('detail',{platform:sample.platform,content_id:actual.standard.note_id},other)).error,'content_missing');
  await waitEnd();g=check(await call('guard',{task:task.id,lease:task.lease_token,action:'detail',content_id:actual.standard.note_id}));
  const metricOnly=structuredClone(actual);metricOnly.standard.like_count=123;metricOnly.extra.field_observations.like_count={value:123,label:'123',status:'exact'};
  const revisedComment=metricOnly.extra.comments.items.find(item=>item.comment_id);
  if(revisedComment){revisedComment.text+='修订';revisedComment.original_length=revisedComment.text.length;revisedComment.truncated=false;}
  if(metricOnly.extra.metric_labels)metricOnly.extra.metric_labels.like_count='123';metricOnly.evidence.parser_version='4.3.1';metricOnly.standard.captured_at=new Date().toISOString();
  const sameVersion=check(await call('submit',{...realPayload,request:randomUUID(),admission_id:g.admission_id,record:metricOnly}));assert.equal(sameVersion.version,first.version);
  const commentDetail=check(await call('detail',{platform:sample.platform,content_id:actual.standard.note_id}));
  const realIds=new Set(actual.extra.comments.items.map(item=>item.comment_id).filter(Boolean));assert.equal(commentDetail.comment_entities.length,realIds.size);
  assert.equal(commentDetail.comments.filter(row=>[realPayload.request,sameVersion.request].includes(row.request)).length,actual.extra.comments.items.length*2);
  if(revisedComment){assert.equal(commentDetail.comment_entities.find(item=>item.comment_id===revisedComment.comment_id).version,2);assert.equal(commentDetail.comment_versions.filter(item=>item.comment_id===revisedComment.comment_id).length,2);}
  for(const original of actual.extra.comments.items.filter(item=>item.parent_key&&item.comment_id)){
   const parent=actual.extra.comments.items.find(item=>item.key===original.parent_key);const entity=commentDetail.comment_entities.find(item=>item.comment_id===original.comment_id);
   assert.equal(entity.parent_comment_id,parent.comment_id);assert.equal(entity.root_comment_id,parent.comment_id);assert.equal(entity.relationship_status,'parent_observed');
  }
  cases++;
  const fin=check(await call('finish',{task:task.id,lease:task.lease_token,reason:'completed'})).task;assert.equal(fin.state,'partial');assert.equal(fin.reason,'observed_only');
  lastContent={platform:sample.platform,content_id:actual.standard.note_id};cases++;
 }
 // Authorized derivatives stay separate from the original DOM text, with strict owner scope.
 const evidence={...lastContent,kind:'ocr',authorization_ref:'user-local-fixture',evidence:{source_kind:'authorized_local_file',asset_sha256:'a'.repeat(64),observed_at:new Date().toISOString(),raw_text:'OCR text',blocks:[{text:'OCR text',confidence:0.9,bbox:[0,0,0.5,0.5],semantic_type:'unclassified',review_status:'unreviewed'}]}};
 const imported=check(await call('attach_evidence',evidence));assert.ok(imported.evidence_id);assert.deepEqual(await call('attach_evidence',evidence),imported);
 const withEvidence=check(await call('detail',lastContent));assert.equal(withEvidence.evidence.length,1);assert.notEqual(withEvidence.content.body,'OCR text');
 assert.equal((await call('attach_evidence',evidence,other)).error,'content_missing');
 const localSpeech={...evidence,kind:'transcript',evidence:{source_kind:'authorized_local_file',asset_sha256:'c'.repeat(64),observed_at:new Date().toISOString(),raw_text:'本机转录',processor:'apple_speech_ondevice'}};assert.ok(check(await call('attach_evidence',localSpeech)).evidence_id);assert.equal((await call('attach_evidence',{...localSpeech,evidence:{...localSpeech.evidence,processor:'cloud_fallback'}})).error,'invalid_evidence');cases++;
 const personal={...evidence,kind:'demographics',evidence:{...evidence.evidence,population:'public aggregate',dimension:'region',sample_size:10,coverage_period:'2026',aggregate_values:{regionA:10}}};assert.equal((await call('attach_evidence',personal)).error,'invalid_aggregate');
 const aggregate={...personal,evidence:{source_kind:'authorized_local_file',asset_sha256:'b'.repeat(64),observed_at:new Date().toISOString(),population:'public aggregate',dimension:'region',sample_size:10,coverage_period:'2026',aggregate_values:{regionA:10}}};assert.ok(check(await call('attach_evidence',aggregate)).evidence_id);cases++;
 // Profile follows its own search admission and does not increase content receipts or rewards.
 target=await upsert('https://space.bilibili.com/777');await call('start',{target_id:target.id});task=check(await call('claim')).task;await waitEnd();g=check(await call('guard',{task:task.id,lease:task.lease_token,action:'search'}));assert.equal(g.allowed,true);
 const profilePayload={request:randomUUID(),task:task.id,lease:task.lease_token,admission_id:g.admission_id,profile:{author_id:'777',url:'https://space.bilibili.com/777',nickname:'公开作者',public_handle:null,metrics:{followers:{value:12000,label:'1.2万',status:'approximate'},notes:{value:null,label:null,status:'not_visible'},likes_collected:{value:null,label:null,status:'not_visible'}},captured_at:new Date().toISOString(),source:'rendered_public_dom',parser_version:'4.3.0'}};
 const profileAck=check(await call('profile',profilePayload));assert.equal(profileAck.kind,'profile');assert.equal(profileAck.gate,'received');assert.deepEqual(await call('profile',profilePayload),profileAck);
 assert.equal((await call('list')).profiles.some(row=>row.author_id==='777'),true);cases++;
 // Risk finish persists the preexisting safety cooldown, even if another KOL is started.
 await call('finish',{task:task.id,lease:task.lease_token,reason:'risk_paused',risk_type:'captcha'});
 await call('start',{target_id:target.id});task=check(await call('claim')).task;await waitEnd();
 assert.equal((await call('guard',{task:task.id,lease:task.lease_token,action:'search'})).reason,'captcha');cases++;
 // Actual extension state machine calls the real SQL RPC, including an ACK lost after COMMIT.
 await import('../../../../../crawler-extension/v4/src/kol.js');
 for(const sample of fixtures.records.flatMap(record=>['content','creator'].map(kind=>({...record,kind})))){
  const actual=structuredClone(sample.record),stateStore=new Map([['session',{user:{id:other}}]]);let clock=Date.now(),opens=0,probes=0,submitCalls=0,profileCalls=0,firstAck,probesAtLost;
  const runtime={storage:{get:async key=>structuredClone(stateStore.get(key)),set:async(key,value)=>stateStore.set(key,structuredClone(value))},
   now:()=>clock,uuid:randomUUID,schedule:async()=>{},cancel:async()=>{},close:async()=>{},open:async()=>{opens++;},
   probe:async({action})=>{if(action==='comments')return {ready:true};probes++;if(action==='discover'){const profile=structuredClone(fixtures.profiles.find(row=>row.platform===sample.platform).profile);profile.captured_at=new Date().toISOString();return {ready:true,creator_id:profile.author_id,profile,links:[actual.standard.url]};}const r=structuredClone(actual);r.standard.captured_at=new Date().toISOString();return {ready:true,record:r};}};
  const adapter={rpc:async(name,params)=>{
   assert.equal(name,'kol');const result=await call(params.p_action,params.p_payload,other);
   if(params.p_action==='profile'){profileCalls++;assert.equal(result.kind,'profile');assert.equal(result.gate,'received');}
   if(params.p_action==='submit'){
    submitCalls++;if(submitCalls===1){firstAck=result;probesAtLost=probes;throw new Error('backend_unavailable');}
    assert.deepEqual(result,firstAck);assert.equal(probes,probesAtLost,'lost ACK must not recapture');
   }
   return result;
  }};
  await db.exec("update crowd_v4.note_reservations set expires_at=clock_timestamp()-interval '1 second'"); // End the earlier fixture owner's reservation.
  const at=check(await call('upsert',{url:sample.kind==='creator'?actual.extra.author.url:actual.standard.url,label:'Agent SQL integration'},other)).target;
  if(sample.kind==='creator')await db.query("update crowd_kol.contents set last_seen_at=clock_timestamp()-interval '25 hours' where owner=$1",[other]); // Sparse refresh fixture, not an immediate duplicate capture.
  const agent=new globalThis.CrowdKOL.Agent(runtime,adapter);await agent.start({target_id:at.id,mode:sample.kind==='creator'?'history':'manual',max_items:1,comment_limit:20,comment_depth:2});
  for(let step=0;step<40;step++){
   await db.query("update crowd_v4.safety set next_action=clock_timestamp()-interval '1 second' where user_id=$1",[other]);
   clock+=60000;await agent.tick();const state=await agent.read(other);if(state.received===1&&!state.task)break;
  }
  const state=await agent.read(other);assert.equal(state.received,1,JSON.stringify(state));assert.equal(state.outbox.length,0);assert.equal(state.task,null);
  assert.equal(opens,sample.kind==='creator'?2:1);assert.equal(profileCalls,sample.kind==='creator'?1:0);assert.equal(submitCalls,2);assert.equal(firstAck.gate,'received');cases++;
 }
 // DOM account-navigation declarations bind later tasks, without resetting shared budgets.
 const bindingPayload={platform:'bilibili',principal_ref:'a'.repeat(64),verification:'rendered_account_navigation'};
 const beforeSafety=(await db.query('select to_jsonb(s) row from crowd_v4.safety s where user_id=$1',[other])).rows[0].row;
 assert.equal((await call('session_changed',{...bindingPayload,principal_ref:'bad'},other)).error,'invalid_principal');
 const bound=check(await call('session_changed',bindingPayload,other));assert.equal(bound.identity_changed,true);
 const again=check(await call('session_changed',bindingPayload,other));assert.equal(again.credential_epoch,bound.credential_epoch);assert.equal(again.identity_changed,false);
 assert.deepEqual((await db.query('select to_jsonb(s) row from crowd_v4.safety s where user_id=$1',[other])).rows[0].row,beforeSafety);
 assert.equal((await call('list',{},owner)).principal_bindings.bilibili,undefined);cases++;
 const boundTarget=check(await call('upsert',{url:'https://www.bilibili.com/video/BV1xx411c7mD'},other)).target;
 await call('start',{target_id:boundTarget.id,max_items:2,comment_limit:2,comment_depth:2},other);const boundTask=check(await call('claim',{},other)).task;
 assert.equal(boundTask.principal_ref,bindingPayload.principal_ref);assert.equal(boundTask.principal_verification,'rendered_account_navigation');assert.ok(boundTask.principal_verification_at);
 await waitEnd();const boundAdmission=check(await call('guard',{task:boundTask.id,lease:boundTask.lease_token,action:'detail',content_id:'BV1xx411c7mD'},other));assert.equal(boundAdmission.allowed,true);
 const switched=check(await call('session_changed',{...bindingPayload,principal_ref:'b'.repeat(64)},other));assert.equal(switched.credential_epoch,bound.credential_epoch+1);
 assert.equal((await call('guard',{task:boundTask.id,lease:boundTask.lease_token,action:'search'},other)).allowed,false);
 const boundLate={request:randomUUID(),task:boundTask.id,lease:boundTask.lease_token,admission_id:boundAdmission.admission_id,record:record('bilibili','BV1xx411c7mD','123')};
 const boundReceipt=check(await call('submit',boundLate,other));assert.equal(boundReceipt.gate,'received');assert.deepEqual(await call('submit',boundLate,other),boundReceipt);cases++;
 await call('start',{target_id:boundTarget.id},other);const newBound=check(await call('claim',{},other)).task;assert.equal(newBound.principal_ref,'b'.repeat(64));
 const xhsBound=check(await call('session_changed',{...bindingPayload,platform:'xiaohongshu',principal_ref:'c'.repeat(64)},other));assert.equal(xhsBound.principal_bindings.bilibili.principal_ref,'b'.repeat(64));
 const cleared=check(await call('session_changed',{},other));assert.deepEqual(cleared.principal_bindings,{});cases++;
 await call('delete_target',{target_id:boundTarget.id},other);
 const taskCount=(await call('list',{},other)).tasks.length;
 const restored=check(await call('upsert',{url:boundTarget.url,label:'restored',interval_minutes:60},other)).target;assert.equal(restored.status,'active');assert.equal(restored.interval_minutes,0);assert.equal(restored.next_due_at,null);assert.equal((await call('list',{},other)).tasks.length,taskCount);
 await call('stop',{target_id:boundTarget.id},other);const edited=check(await call('upsert',{url:boundTarget.url,label:'paused edit'},other)).target;assert.equal(edited.status,'paused');cases++;
 await db.exec('set role anon');await assert.rejects(db.query("select public.crowd_v4_kol('list','{}')"),/permission denied/);await db.exec('reset role');
 assert.equal((await db.query("select has_schema_privilege('authenticated','crowd_kol','usage') b")).rows[0].b,false);cases++;
 console.log(`PASS KOL RPC: ${cases} scenario groups; complete migration chain, owner isolation, two-platform guard/submit, historical ACK, no rewards`);
}catch(error){console.error(error.message,error.cause?.message,error.cause?.where,error.where);process.exitCode=1;}finally{await db.close();}
