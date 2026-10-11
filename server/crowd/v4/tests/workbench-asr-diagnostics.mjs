import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const elements = new Map();
class Element {
  constructor(tag, text='') { this.tag=tag; this.textContent=text; this.children=[]; this.options=[]; this.events={}; }
  set id(value) { this._id=value; elements.set(value,this); }
  get id() { return this._id; }
  set innerHTML(value) { for(const match of value.matchAll(/id="([^"]+)"/g)){const child=new Element('element');child.id=match[1];} }
  append(...items) { this.children.push(...items);if(this.id==='media_content')this.options.push(...items); }
  replaceChildren() { this.children=[];this.options=[]; }
  setAttribute() {}
  addEventListener(name, callback) { this.events[name]=callback; }
  showModal() { this.open=true; }
  close() { this.open=false;this.events.close?.(); }
  get selectedOptions() { return this.options.filter(option=>option.value===this.value); }
}
let response;
const calls=[];
const api=async(route,{action,payload})=>{
  assert.equal(route,'/api/media-processing');calls.push({action,payload});
  if(action==='capabilities')return {asr:true,ocr:true,transcript:true,asr_model_name:'small',limits:{max_audio_seconds:3600,long_audio_seconds:7200}};
  if(action==='list')return {jobs:[]};
  if(action==='start'||action==='status')return response;
  throw Error('unexpected action');
};
const context=vm.createContext({api,document:{body:new Element('body')},node:(tag,text)=>new Element(tag,text),$:id=>elements.get(id),button:(text,callback)=>{const element=new Element('button',text);element.onclick=callback;return element;},Option:function(text,value){this.text=text;this.value=value;},guarded:async callback=>callback(),selectedRun:{run_id:'saved-run'},idOf:run=>run.run_id,resultData:{records:[{kind:'content',content_id:'123',title:'saved'}]},setTimeout:()=>1,clearTimeout:()=>{}});
vm.runInContext(fs.readFileSync(new URL('../multiplatform/media-ui.js',import.meta.url),'utf8'),context);
const view=vm.runInContext('mediaView',context);
elements.get('media_kind').options=[{value:'ocr'},{value:'asr'},{value:'transcript'}];
const text='<img src=x onerror=alert(1)> 原始文字';
const completed=quality=>({job_id:'A',state:'completed',result:[{evidence:{processor:'faster_whisper_local_segmented',raw_text:text,segments:[{start:53,end:55,text}],...(quality?{quality_diagnostics:quality}:{})}}]});
const entry={chunk_index:1,segment_index:0,start:53,end:54,text:'已去重残片',avg_logprob:-2.,compression_ratio:2.8,no_speech_prob:.9,flags:['low_logprob','high_compression','possible_no_speech']};
const quality={schema_version:1,status:'available',segments:[entry]};
async function show(value){response=value;await view.open({path:'output/video.mp4'});await elements.get('media_process_start').onclick();}

await show(completed(quality));
assert.equal(elements.get('media_process_result').textContent,'[53–55] '+text);
const rendered=elements.get('media_process_quality').textContent;
assert.match(rendered,/原始窗口片段，可能包含已去重/);
assert.match(rendered,/窗口 1 · 片段 0：已去重残片/);
assert.match(rendered,/平均对数概率偏低/);
assert.match(rendered,/不代表准确率/);
assert.match(elements.get('media_process_state').textContent,/待人工核对/);
assert.equal(elements.get('media_process_quality').hidden,false);

await show(completed());
assert.match(elements.get('media_process_quality').textContent,/未记录（unknown）/);
assert.equal(elements.get('media_process_result').textContent,'[53–55] '+text);
await show(completed({...quality,status:'partial',segments:[{...entry,avg_logprob:null,flags:[]}]}));
assert.match(elements.get('media_process_quality').textContent,/部分片段或数值未记录/);
assert.match(elements.get('media_process_quality').textContent,/avg_logprob=未记录/);
assert.match(elements.get('media_process_quality').textContent,/仍不代表识别正确/);
await show(completed({...quality,segments:Array.from({length:21},()=>entry)}));
assert.match(elements.get('media_process_quality').textContent,/仅显示前 20 条；其余 1 条保留/);

let resolve;
response=new Promise(done=>{resolve=done;});
await view.open({path:'output/old.mp4'});
const pending=elements.get('media_process_start').onclick();
await view.open({path:'output/new.mp4'});
resolve(completed(quality));await pending;
assert.equal(elements.get('media_process_quality').hidden,true);
assert.equal(elements.get('media_process_quality').textContent,'');

response=new Promise(done=>{resolve=done;});
await view.open({path:'output/old.mp4'});
const closed=elements.get('media_process_start').onclick();
elements.get('media_process_close').onclick();resolve(completed(quality));await closed;
assert.equal(elements.get('media_process_quality').textContent,'');
console.log(JSON.stringify({ok:true,diagnostic_cases:7,raw_text_preserved:true,late_and_closed_responses_ignored:true,source_requests:0,model_calls:0,environment:'Node VM DOM substitute'}));
