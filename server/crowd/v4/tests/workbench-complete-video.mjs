import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const elements=new Map(),calls=[],downloads=[],blobs=new Map(),revoked=[],globalMessages=[];
class Element {
  constructor(tag,text=''){this.tag=tag;this.textContent=text;this.children=[];this.events={};this.options=[];}
  set id(value){this._id=value;elements.set(value,this);}get id(){return this._id;}
  set innerHTML(value){for(const match of value.matchAll(/id="([^"]+)"/g)){const el=new Element('element');el.id=match[1];}}
  append(...items){for(const item of items){this.children.push(item);item.parent=this;}}
  replaceChildren(){this.children=[];}setAttribute(){}removeAttribute(){}pause(){}load(){}
  addEventListener(name,fn){this.events[name]=fn;}showModal(){this.open=true;}close(){this.open=false;this.events.close?.();}
  click(){downloads.push({name:this.download,blob:blobs.get(this.href)});}
}
const hash='a'.repeat(64),ref='b'.repeat(64),run='original-local-run',job='00000000-0000-4000-8000-000000000001';
const state={job_id:job,state:'completed',kind:'complete_video',asset_sha256:hash,result:[{evidence:{duration_seconds:12.3}}]};
let pendingPreview=null,pendingStatus=null,pendingBlob=null,pendingList=null,savedJobs=[];
const context=vm.createContext({Blob,token:'synthetic-csrf',selectedRun:{run_id:run},idOf:value=>value.run_id,resultData:{},Option:class{},document:{body:new Element('body')},node:(tag,text)=>new Element(tag,text),$:(id)=>elements.get(id),button:(text,fn)=>{const b=new Element('button',text);b.onclick=fn;return b;},guarded:async fn=>{try{return await fn();}catch(error){globalMessages.push(error.message);}},download:()=>{throw Error('not used');},clearTimeout:()=>{},setTimeout:()=>1,
  URL:{createObjectURL(blob){const key='blob:test'+blobs.size;blobs.set(key,blob);return key;},revokeObjectURL(key){revoked.push(key);}},
  api:async(path,body)=>{calls.push(body);if(body.action==='video_preview')return pendingPreview?await pendingPreview:{reference_sha256:ref};if(body.action==='list')return pendingList?await pendingList:{jobs:savedJobs};if(body.action==='video_start')return state;if(body.action==='status')return pendingStatus?await pendingStatus:state;if(body.action==='cancel')return {...state,state:'cancelled'};throw Error('unexpected action');},
  fetch:async(path,options)=>{calls.push(JSON.parse(options.body));assert.equal(options.headers['X-Crowd-CSRF'],'synthetic-csrf');return {ok:true,headers:{get:()=>hash},blob:async()=>pendingBlob?await pendingBlob:new Blob(['full-video'])};}
});
vm.runInContext(fs.readFileSync('crowd-kol/server/crowd/v4/multiplatform/media-ui.js','utf8'),context);
await vm.runInContext("mediaView.openVideo({platform:'douyin',content_id:'123',kind:'content'})",context);
assert.deepEqual(JSON.parse(JSON.stringify(calls)),[{action:'video_preview',payload:{run_id:run,content_id:'123'}},{action:'list',payload:{run_id:run}}]);
assert.equal(elements.get('complete_video_start').disabled,false);assert.equal(downloads.length,0);
await elements.get('complete_video_start').onclick();
assert.deepEqual(JSON.parse(JSON.stringify(calls.find(x=>x.action==='video_start').payload)),{run_id:run,content_id:'123',reference_sha256:ref,allow_download:true});
assert.equal(calls.filter(x=>x.action==='video_start').length,1);assert.equal(elements.get('complete_video_download').hidden,false);
assert.match(elements.get('complete_video_state').textContent,/12.3 秒/);
await elements.get('complete_video_download').onclick();assert.equal(await downloads[0].blob.text(),'full-video');assert.match(downloads[0].name,/\.mp4$/);
let resolve;pendingBlob=new Promise(r=>resolve=r);const delayed=elements.get('complete_video_download').onclick();await Promise.resolve();elements.get('complete_video_close').onclick();resolve(new Blob(['old']));await delayed;pendingBlob=null;assert.equal(downloads.length,1);
pendingPreview=new Promise(r=>resolve=r);const stalePreview=vm.runInContext("mediaView.openVideo({content_id:'456'})",context);elements.get('complete_video_close').onclick();resolve({reference_sha256:'c'.repeat(64)});await stalePreview;pendingPreview=null;assert.equal(elements.get('complete_video_start').disabled,true);
await vm.runInContext("mediaView.openVideo({content_id:'789'})",context);pendingStatus=new Promise(r=>resolve=r);const oldStatus=elements.get('complete_video_start').onclick();await new Promise(r=>setImmediate(r));const previous=elements.get('complete_video_state').textContent;elements.get('complete_video_close').onclick();resolve({...state,state:'failed',reason:'late-wrong-status'});await oldStatus;pendingStatus=null;assert.equal(elements.get('complete_video_state').textContent,previous);
assert.equal(calls.filter(x=>x.action==='video_start').length,2);assert.equal(downloads.length,1);
await vm.runInContext("mediaView.openVideo({content_id:'123'})",context);await elements.get('complete_video_start').onclick();
let reject;pendingBlob=new Promise((_,r)=>reject=r);const oldFailure=elements.get('complete_video_download').onclick();await new Promise(r=>setImmediate(r));elements.get('complete_video_close').onclick();const closedText=elements.get('complete_video_state').textContent;reject(Error('old-video-failed'));await oldFailure;assert.equal(globalMessages.length,0);assert.equal(elements.get('complete_video_state').textContent,closedText);pendingBlob=null;
await vm.runInContext("mediaView.openVideo({content_id:'123'})",context);await elements.get('complete_video_start').onclick();pendingBlob=new Promise((_,r)=>reject=r);const currentFailure=elements.get('complete_video_download').onclick();await new Promise(r=>setImmediate(r));reject(Error('current-video-failed'));await currentFailure;assert.equal(globalMessages.length,0);assert.match(elements.get('complete_video_state').textContent,/current-video-failed/);pendingBlob=null;


const existing={...state,run_id:run,content_id:'123',source_reference_sha256:ref};
const opens=()=>vm.runInContext("mediaView.openVideo({content_id:'123'})",context);
const initialStarts=calls.filter(x=>x.action==='video_start').length;
savedJobs=[existing];await opens();assert.equal(elements.get('complete_video_start').disabled,true);assert.equal(elements.get('complete_video_download').hidden,false);assert.match(elements.get('complete_video_state').textContent,/完整视频已保存/);await elements.get('complete_video_download').onclick();assert.equal(downloads.length,2);
for(const terminal of ['failed','cancelled','interrupted_unknown']){savedJobs=[{...existing,state:terminal}];await opens();assert.equal(elements.get('complete_video_start').disabled,true);assert.equal(elements.get('complete_video_download').hidden,true);assert.equal(elements.get('complete_video_cancel').disabled,true);}
savedJobs=[{...existing,state:'running'}];await opens();assert.equal(elements.get('complete_video_start').disabled,true);assert.equal(calls.at(-1).action,'status');
savedJobs=[existing,{...existing,job_id:'second-job'}];await opens();assert.equal(elements.get('complete_video_start').disabled,true);assert.match(elements.get('complete_video_state').textContent,/complete_video_saved_task_ambiguous/);
savedJobs=[{...existing,run_id:'other-run'},{...existing,content_id:'other-content'},{...existing,source_reference_sha256:'other-ref'},{...existing,kind:'asr'}];await opens();assert.equal(elements.get('complete_video_start').disabled,false);assert.equal(elements.get('complete_video_download').hidden,true);
pendingList=new Promise(r=>resolve=r);const delayedList=opens();await new Promise(r=>setImmediate(r));elements.get('complete_video_close').onclick();resolve({jobs:[existing]});await delayedList;pendingList=null;assert.equal(elements.get('complete_video_start').disabled,true);assert.equal(elements.get('complete_video_download').hidden,true);
pendingList=new Promise((_,r)=>reject=r);const failedList=opens();await new Promise(r=>setImmediate(r));elements.get('complete_video_close').onclick();const textBefore=elements.get('complete_video_state').textContent;reject(Error('OLD_LIST_ERROR'));await failedList;pendingList=null;assert.equal(elements.get('complete_video_state').textContent,textBefore);assert.equal(globalMessages.length,0);
pendingList=new Promise(r=>resolve=r);const switchedList=opens();await new Promise(r=>setImmediate(r));pendingList=null;savedJobs=[];await vm.runInContext("mediaView.openVideo({content_id:'456'})",context);resolve({jobs:[existing]});await switchedList;assert.equal(elements.get('complete_video_download').hidden,true);assert.equal(elements.get('complete_video_start').disabled,false);
pendingList=Promise.resolve({jobs:null});await opens();pendingList=null;assert.equal(elements.get('complete_video_start').disabled,true);assert.match(elements.get('complete_video_state').textContent,/complete_video_saved_tasks_unavailable/);
assert.equal(calls.filter(x=>x.action==='video_start').length,initialStarts);

console.log(JSON.stringify({ok:true,cases:16,existing_complete_video_readonly_lookup:true,failed_unknown_not_restarted:true,exact_reference_binding:true,duplicate_matches_refused:true,late_list_success_and_failure_ignored:true,late_failure_no_global_broadcast:true,current_failure_visible:true,explicit_download_only:true,server_reference_and_csrf:true,whole_video_blob_identity:true,closed_late_preview_status_download_blocked:true,source_requests:0,model_calls:0}));
