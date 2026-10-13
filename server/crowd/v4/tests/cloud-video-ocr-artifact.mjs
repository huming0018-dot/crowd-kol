import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
import {randomUUID} from 'node:crypto';
import {handleMachine} from '../supabase/functions/crowd-machine/core.mjs';
import {captureHash,sha,canonical} from '../supabase/functions/crowd-machine/contract.mjs';
import {transcriptPayload} from '../supabase/functions/crowd-machine/transcript_contract.mjs';
import {artifactCanonical} from '../supabase/functions/crowd-machine/artifact_contract.mjs';
const {PGlite}=createRequire(import.meta.url)(path.join(process.env.CROWD_TEST_TOOLS||'/private/tmp/crowd-fix-tools','node_modules/@electric-sql/pglite'));
const folder=fs.mkdtempSync(path.join(os.tmpdir(),'video-ocr-rpc-')),db=new PGlite(folder);
const owner='a'.repeat(64),worker='b'.repeat(64),ownerHash=await sha(owner);let cases=0;
const backend={async rpc(name,args){try{const values=name==='crowd_transcript_artifact_rpc'?[args.p_owner_scope,args.p_actor_kind,args.p_action,JSON.stringify(args.p_payload)]:[args.p_owner_scope,args.p_actor_kind,args.p_worker_hash,args.p_action,JSON.stringify(args.p_payload)];return{data:(await db.query(name==='crowd_transcript_artifact_rpc'?'select public.crowd_transcript_artifact_rpc($1,$2,$3,$4) result':'select public.crowd_machine_rpc($1,$2,$3,$4,$5) result',values)).rows[0].result};}catch(error){return{error:{message:error.message}}}}};
async function call(action,payload={},workerRole=false){const response=await handleMachine(new Request('https://offline.invalid',{method:'POST',headers:{'Content-Type':'application/json',[workerRole?'X-Crowd-Worker-Key':'X-Crowd-Owner-Key']:workerRole?worker:owner},body:JSON.stringify({action,payload})}),backend,ownerHash);return{status:response.status,...await response.json()}}
async function good(action,payload={},workerRole=false){const r=await call(action,payload,workerRole);assert.equal(r.ok,true,JSON.stringify(r));return r.result}
async function direct(payload,actor='owner',scope='crowd-owner-main'){
 const canonical_transcript=artifactCanonical(payload),normalized={...payload,canonical_transcript,artifact_hash:await sha('crowd-transcript-artifact-v1\n'+canonical_transcript)};
 return db.query('select public.crowd_transcript_artifact_rpc($1,$2,$3,$4) result',[scope,actor,'transcript_put',JSON.stringify(normalized)]);
}
const migration='20261013020000_crowd_video_ocr_report.sql';
try{
 await db.exec('create role anon;create role authenticated;create role service_role bypassrls;');
 await db.exec(fs.readFileSync(new URL('../cloud_machine.sql',import.meta.url),'utf8'));
 for(const name of ['20261012080647_crowd_transcript_artifact.sql','20261012163143_crowd_platform_subtitle_report.sql',migration,migration,'20261013061140_crowd_declared_subtitle_report.sql'])await db.exec(fs.readFileSync(new URL('../supabase/migrations/'+name,import.meta.url),'utf8'));cases++;
 const platforms={xhs:'xiaohongshu',dy:'douyin',ks:'kuaishou',bili:'bilibili',wb:'weibo',tieba:'tieba',zhihu:'zhihu'};
 await good('worker_pair',{worker_id:randomUUID(),worker_key:worker,name:'offline-video-ocr',platforms:Object.keys(platforms),expires_at:new Date(Date.now()+86400000).toISOString()});
 let last;
 for(const[p,platform]of Object.entries(platforms)){
  const targets={xhs:'66fad51c000000001b0224b8',dy:'123',ks:'fixture-123',bili:'BV1ocaW6rETo',wb:'123',tieba:'123',zhihu:'https://www.zhihu.com/question/1/answer/123'};
  const task=(await good('task_create',{platforms:[p],mode:'detail',targets_by_platform:{[p]:[targets[p]]},desired_items:1,max_api_requests:8,purpose:'noncommercial_research',idempotency_key:randomUUID()})).task;
  const lease=(await good('claim',{claim_id:randomUUID()},true)).lease,local=randomUUID(),job=randomUUID();
  await good('heartbeat',{run_id:lease.run_id,lease_epoch:lease.lease_epoch,sequence:1,local_run_id:local},true);
  const record={kind:'content',platform,content_id:'123',title:'offline',body:'saved',record_hash:'f'.repeat(64),source_kind:'mediacrawler_api',reward_eligible:false,origin:{run_id:local,file_sha256:'f'.repeat(64),line:1},...(p==='zhihu'?{content_type:'answer'}:{})};
  const envelope={schema:'crowd-machine-capture-v1',capture_id:randomUUID(),task_id:task.task_id,child_id:lease.child_id,run_id:lease.run_id,lease_epoch:lease.lease_epoch,platform,delivery_basis:'live_capture',source_kind:'machine_api',record,adapter_version:'test',normalizer_version:'test',packaged_at:new Date().toISOString()};
  const envelope_hash=await captureHash(envelope);await good('capture',{run_id:lease.run_id,lease_epoch:lease.lease_epoch,envelope,envelope_hash},true);
  // Long untranscribed gaps are valid screen-text observations, never evidence of missing speech.
  const segments=[{start:20,end:21,text:'画面文字😀'},{start:80,end:80.5,text:'末段'}],duration=100.25;
  const visual={provider:'apple_vision',source_kind:'sampled_video_text',source_video_sha256:'c'.repeat(64),source_reference_sha256:'a'.repeat(64),source_record_sha256:record.record_hash,sampling_fps:2,sample_start:0,sample_end:duration,sampled_frames:201,expected_frames:201,crop_top_origin:[.7,1],timestamp_kind:'resampled_frame_time',timestamp_uncertainty_seconds:.5,frame_evidence_sha256:'b'.repeat(64),frame_evidence_format:'gzip_json_array_v1',coverage:'all_scheduled_frames_processed',spoken_transcript:false,semantic_completeness:'unknown',truncated:false};
  const report={schema:'crowd-video-ocr-report-v1',job_id:job,video_source_job_id:randomUUID(),visual_provenance:visual,local_run_id:local,platform,content_id:'123',entity_ref:platform+':content:123'+(p==='zhihu'?':answer':''),asset_sha256:'c'.repeat(64),input_hash:'d'.repeat(64),full_result_file_sha256:'e'.repeat(64),duration_seconds:duration,segments,text_sha256:await sha(segments.map(r=>r.text).join('\n')),segment_count:2,character_count:7,semantic_review:'not_reviewed',cer:null,human_groundtruth:false,diagnostics_sha256:'b'.repeat(64),model_manifest_sha256:null,processing_profile:'apple_vision_video_hard_text_2fps_v1',processor:'apple_vision_sampled_video_text',text_revision:null};
  const input={idempotency_key:'transcript:'+job,task_id:task.task_id,child_id:lease.child_id,run_id:lease.run_id,lease_epoch:lease.lease_epoch,local_run_id:local,local_job_id:job,source_refs:[{capture_id:envelope.capture_id,envelope_hash}],report_sha256:await sha(JSON.stringify(report)),report_json:JSON.stringify(report)};
  const before=(await db.query('select to_jsonb(c) child,(select jsonb_agg(to_jsonb(z)) from crowd_machine.captures z) captures from crowd_machine.children c where child_id=$1',[lease.child_id])).rows[0];
  const receipt=(await good('transcript_put',input)).receipt;assert.equal(receipt.reward_eligible,false);assert.equal(receipt.semantic_review,'not_reviewed');
  const get=await good('transcript_get',{local_job_id:job});assert.equal(get.artifact.report_json,input.report_json);assert.deepEqual(get.receipt,receipt);
  assert.equal((await good('transcript_put',input)).replayed,true);assert.equal((await direct(input)).rows[0].result.replayed,true);
  const after=(await db.query('select to_jsonb(c) child,(select jsonb_agg(to_jsonb(z)) from crowd_machine.captures z) captures from crowd_machine.children c where child_id=$1',[lease.child_id])).rows[0];assert.deepEqual(after,before);cases+=5;
  const finish={run_id:lease.run_id,lease_epoch:lease.lease_epoch,capture_ids:[envelope.capture_id],outcome:'completed',api_attempts:1};
  await good('finish',{...finish,finish_hash:await sha('crowd-machine-finish-v1\n'+canonical(finish))},true);
  last={report,input,visual};
 }
 const{report,input,visual}=last;
 for(const delta of [{video_source_job_id:'bad'},{audio_source_job_id:report.job_id},{subtitle_source_run_id:report.local_run_id},{processor:'faster_whisper_local'},{processing_profile:'other'},{model_manifest_sha256:'f'.repeat(64)},{diagnostics_sha256:null},{cer:0},{human_groundtruth:true},{semantic_review:'reviewed'},{segments:[{start:0,end:0,text:'bad'}]},{segments:[{start:10,end:20,text:'one'},{start:19,end:21,text:'overlap'}]},{segments:[{start:80,end:81,text:'late'},{start:20,end:21,text:'early'}]},{segments:[{start:0,end:1,text:'x',chunk_index:0}]},{character_count:999},{text_sha256:'0'.repeat(64)}]){
  const raw=JSON.stringify({...report,...delta}),bad={...input,report_json:raw,report_sha256:await sha(raw)};
  await assert.rejects(transcriptPayload(bad));await assert.rejects(direct(bad));cases++;
 }
 for(const delta of [{provider:'other'},{source_kind:'asr'},{source_video_sha256:'0'.repeat(64)},{source_reference_sha256:'bad'},{source_record_sha256:'bad'},{sampling_fps:1},{sample_start:.5},{sample_end:100},{sampled_frames:200},{expected_frames:200},{sampled_frames:true},{expected_frames:201.5},{crop_top_origin:[1,.7]},{crop_top_origin:[0,1,1]},{crop_top_origin:[false,1]},{crop_top_origin:[-.1,1]},{timestamp_kind:'native_word_time'},{timestamp_uncertainty_seconds:0},{frame_evidence_sha256:'0'.repeat(64)},{frame_evidence_format:'plain_json'},{coverage:'partial'},{spoken_transcript:true},{semantic_completeness:'full'},{truncated:true},{password:'private'}]){
  const raw=JSON.stringify({...report,visual_provenance:{...visual,...delta}}),bad={...input,report_json:raw,report_sha256:await sha(raw)};
  await assert.rejects(transcriptPayload(bad));await assert.rejects(direct(bad));cases++;
 }
 for(const delta of [{report_sha256:'0'.repeat(64)},{source_refs:[input.source_refs[0],input.source_refs[0]]}]){
  const bad={...input,...delta};await assert.rejects(transcriptPayload(bad));await assert.rejects(direct(bad));cases++;
 }
 const wrongEnvelope={...input,source_refs:[{...input.source_refs[0],envelope_hash:'0'.repeat(64)}]};
 await transcriptPayload(wrongEnvelope);await assert.rejects(direct(wrongEnvelope),/transcript_source_binding_denied/);cases++;
 const wrongSource=JSON.stringify({...report,visual_provenance:{...visual,source_record_sha256:'0'.repeat(64)}});const mismatch={...input,report_json:wrongSource,report_sha256:await sha(wrongSource)};
 await transcriptPayload(mismatch);await assert.rejects(direct(mismatch),/transcript_source_binding_denied/);cases++;
 const changedText=report.segments.map(row=>({...row,text:row.text+'变'})),changed={...report,segments:changedText,text_sha256:await sha(changedText.map(r=>r.text).join('\n')),character_count:9};
 const changedRaw=JSON.stringify(changed);await assert.rejects(direct({...input,report_json:changedRaw,report_sha256:await sha(changedRaw)}),/transcript_conflict/);cases++;
 assert.equal((await call('transcript_put',input,true)).status,403);await assert.rejects(direct(input,'worker'),/principal_denied/);cases+=2;
 // Independent probes: decoded text gates and exact canonical bytes also apply to direct service RPC.
 async function withText(text,escape=false){
  const fresh=randomUUID(),rep={...report,job_id:fresh,segments:[{start:0,end:1,text}],segment_count:1,character_count:[...text].length,text_sha256:await sha(text)};
  let raw=JSON.stringify(rep);if(escape)raw=raw.replace('cookie=sample','cookie\\u003dsample');
  return {...input,local_job_id:fresh,idempotency_key:'transcript:'+fresh,report_json:raw,report_sha256:await sha(raw)};
 }
 const trimCharacters='\t\n\v\f\r '+String.fromCodePoint(160,5760,...Array.from({length:11},(_,i)=>8192+i),8232,8233,8239,8287,12288,65279);
 for(const text of ['\t',trimCharacters,'😀'.repeat(12001)]){
  const bad=await withText(text);await assert.rejects(transcriptPayload(bad),/invalid_transcript/);await assert.rejects(direct(bad),/invalid_transcript/);cases++;
 }
 for(const text of ['cookie=sample','cookie\t=sample','cookie\u00a0=sample','cookie\ufeff=sample']){
  const bad=await withText(text,true);await assert.rejects(transcriptPayload(bad),/sensitive_transcript|transcript_report_limit/);await assert.rejects(direct(bad),/sensitive_transcript/);cases++;
 }
 for(const text of ['😀'.repeat(12000),'line\tquote"\\\n终\u2028😀']){
  const goodInput=await withText(text),payload=await transcriptPayload(goodInput);
  assert.equal((await direct(goodInput)).rows[0].result.replayed,false);
  assert.equal((await good('transcript_put',goodInput)).replayed,true);
  assert.equal(payload.canonical_transcript,artifactCanonical(goodInput));cases++;
 }
 // Pretty report JSON has literal control characters in the envelope; preserve its exact report SHA.
 const formatted=await withText('formatted');formatted.report_json=JSON.stringify(JSON.parse(formatted.report_json),null,2);formatted.report_sha256=await sha(formatted.report_json);
 await transcriptPayload(formatted);assert.equal((await direct(formatted)).rows[0].result.replayed,false);assert.equal((await good('transcript_put',formatted)).replayed,true);cases++;
 for(const mutate of [value=>' '+value,value=>value+'\n',value=>value.replace('{','{ '),value=>value.replace('"child_id"','"\\u0063hild_id"')]){
  const candidate=await withText('canonical'),expected=artifactCanonical(candidate),canonical_transcript=mutate(expected);
  const altered={...candidate,canonical_transcript,artifact_hash:await sha('crowd-transcript-artifact-v1\n'+canonical_transcript)};
  await assert.rejects(db.query('select public.crowd_transcript_artifact_rpc($1,$2,$3,$4)', ['crowd-owner-main','owner','transcript_put',JSON.stringify(altered)]),/transcript_hash_conflict/);
  assert.equal((await direct(candidate)).rows[0].result.replayed,false);assert.equal((await good('transcript_put',candidate)).replayed,true);cases++;
 }
 const permissions=(await db.query("select has_function_privilege('anon','public.crowd_transcript_artifact_rpc(text,text,text,jsonb)','execute') calls,has_table_privilege('authenticated','crowd_machine.transcript_artifacts','select') reads,has_table_privilege('service_role','crowd_machine.transcript_artifacts','update') updates")).rows[0];assert.deepEqual(permissions,{calls:false,reads:false,updates:false});cases++;
 console.log(JSON.stringify({ok:true,cases,seven_platforms:true,edge_rpc_equivalence:true,source_calls:0,model_calls:0,production_writes:0,original_capture_budget_unchanged:true}));
}finally{await db.close();fs.rmSync(folder,{recursive:true,force:true});}
