import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const elements=new Map(),buttons=[],downloads=[],blobs=new Map(),revoked=[],timers=[];let requestCount=0,pendingStatus=null;
class Element{
  constructor(tag,text=''){this.tag=tag;this.textContent=text;this.children=[];this.options=[];this.events={};}
  set id(value){this._id=value;elements.set(value,this);}get id(){return this._id;}
  set innerHTML(value){for(const m of value.matchAll(/id="([^"]+)"/g)){const e=new Element('element');e.id=m[1];}}
  append(...items){for(const x of items){x.parent=this;this.children.push(x);if(this.id==='media_content')this.options.push(x);}}
  replaceChildren(){this.children=[];this.options=[];}get lastChild(){return this.children.at(-1);}
  remove(){this.parent.children=this.parent.children.filter(x=>x!==this);}setAttribute(){}removeAttribute(){}
  addEventListener(k,fn){this.events[k]=fn;}showModal(){this.open=true;}close(){this.open=false;this.events.close?.();}
  get selectedOptions(){return this.options.filter(x=>x.value===this.value);}pause(){}load(){}
  click(){downloads.push({name:this.download,blob:blobs.get(this.href)});}
}
const hash='a'.repeat(64),input='b'.repeat(64),jobA='bafd5336-42d1-4fd9-a05b-5e464df4706f';
function makeState(id=jobA){return {job_id:id,run_id:'saved-run',state:'completed',kind:'asr',platform:'bilibili',content_id:'117410296235621',asset_sha256:hash,input_hash:input,result_sha256:'c'.repeat(64),model_manifest_sha256:'d'.repeat(64),processor_files:{'local_asr.py':'e'.repeat(64)},created_at:1700000000,model:'/private/not-exported',result:[{platform:'bilibili',content_id:'117410296235621',kind:'transcript',evidence:{asset_sha256:hash,raw_text:'截断预览',truncated:true,segments:Array.from({length:1110},(_,i)=>({start:i,end:i+.5,text:i===1109?'最后中文 <script>保留原文</script>':'第 '+i+' 段'})),quality_diagnostics:{status:'partial',segments:[{start:1109,end:1109.5,text:'原文',avg_logprob:-1.2}]},native_alignment_windows:[{chunk_index:92,status:'recorded',receipt:{semantic_status:'not_reviewed'}}]}}]};}
let state=makeState();const context=vm.createContext({Blob,token:'fake-CSRF',URL:{createObjectURL(blob){const url='blob:fixture-'+(blobs.size+1);blobs.set(url,blob);return url;},revokeObjectURL:url=>revoked.push(url)},fetch:()=>{throw Error('export must not fetch');},api:async(route,{action})=>{requestCount++;assert.equal(route,'/api/media-processing');if(action==='capabilities')return {asr:true,ocr:true,transcript:true};if(action==='list')return {jobs:[{job_id:state.job_id,kind:state.kind,state:state.state,content_id:state.content_id}]};if(action==='status')return pendingStatus||state;throw Error('unexpected action '+action);},document:{body:new Element('body')},node:(tag,text)=>new Element(tag,text),$:id=>elements.get(id),button:(text,onclick)=>{const b=new Element('button',text);b.onclick=onclick;buttons.push(b);return b;},Option:function(text,value){this.text=text;this.value=value;},guarded:fn=>fn(),selectedRun:{run_id:'saved-run'},idOf:r=>r.run_id,resultData:{records:[{kind:'content',content_id:'117410296235621'}]},setTimeout:fn=>{timers.push(fn);return timers.length;},clearTimeout:()=>{}});
const dashboard=fs.readFileSync(new URL('../multiplatform/dashboard.html',import.meta.url),'utf8');
vm.runInContext(dashboard.match(/^function download\(name,value\).*$/m)[0],context);
vm.runInContext(fs.readFileSync(new URL('../multiplatform/media-ui.js',import.meta.url),'utf8'),context);
const view=vm.runInContext('mediaView',context);elements.get('media_kind').options=[{value:'asr'},{value:'ocr'},{value:'transcript'}];
const last=text=>buttons.findLast(b=>b.textContent===text);
async function show(){await view.open({path:'output/bili/media/BV1popx6zEe1/audio.m4a'});await last('查看此任务').onclick();}
const original=JSON.stringify(state);await show();assert.equal(downloads.length,0);assert.equal(elements.get('media_process_exports').hidden,false);
const beforeRequests=requestCount;last('导出完整转写 JSON').onclick();const json=JSON.parse(await downloads.at(-1).blob.text());assert.equal(json.result[0].evidence.segments.length,1110);assert.equal(json.result[0].evidence.segments.at(-1).text,state.result[0].evidence.segments.at(-1).text);assert.equal(json.job.job_id,jobA);assert.equal(json.job.asset_sha256,hash);assert.equal(json.job.input_hash,input);assert.equal(json.semantic_review,'not_reviewed');assert.equal(json.result[0].evidence.native_alignment_windows[0].chunk_index,92);assert.equal('model' in json.job,false);assert.match(downloads.at(-1).blob.type,/application\/json/);
last('导出完整转写 TXT').onclick();const txt=await downloads.at(-1).blob.text();assert.match(txt,/\[1109–1109.5\] 最后中文 <script>保留原文<\/script>/);assert.match(txt,/not_reviewed/);assert.match(txt,/avg_logprob/);assert.match(txt,new RegExp(input));assert.equal(downloads.at(-1).blob.type,'text/plain;charset=utf-8');assert.equal(requestCount,beforeRequests);assert.equal(JSON.stringify(state),original);
const stale=last('导出完整转写 JSON');elements.get('media_process_close').onclick();stale.onclick();assert.equal(downloads.length,2);
state=makeState('different-job');await show();stale.onclick();assert.equal(downloads.length,2);
const old=last('导出完整转写 TXT');let resolve;pendingStatus=new Promise(r=>resolve=r);const switchJob=last('查看此任务').onclick();assert.equal(elements.get('media_process_exports').hidden,true);old.onclick();assert.equal(downloads.length,2);resolve(state);await switchJob;pendingStatus=null;
for(const change of [{state:'running'},{kind:'ocr'},{state:'failed'},{result:[]},{asset_sha256:'f'.repeat(64)},{input_hash:'invalid'}]){state={...makeState(),...change};await show();assert.equal(elements.get('media_process_exports').hidden,true);}
state=makeState();state.result[0].platform='weibo';await show();assert.equal(elements.get('media_process_exports').hidden,true);
state=makeState();state.result[0].content_id='OTHER';await show();assert.equal(elements.get('media_process_exports').hidden,true);
state=makeState();delete state.result[0].evidence.quality_diagnostics;delete state.result[0].evidence.native_alignment_windows;await show();last('导出完整转写 TXT').onclick();assert.match(await downloads.at(-1).blob.text(),/"quality_diagnostics": null/);
for(const fn of timers)fn();assert.equal(revoked.length,downloads.length);
console.log(JSON.stringify({ok:true,cases:7,actual_ui_and_shared_json_download_helper:true,full_1110_segments_not_truncated_preview:true,utf8_identity_and_diagnostics_preserved:true,stale_closed_and_pending_job_exports_blocked:true,completed_asr_only:true,source_requests:0,model_calls:0}));
