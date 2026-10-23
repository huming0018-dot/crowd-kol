import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const html=fs.readFileSync(new URL('../multiplatform/dashboard.html',import.meta.url),'utf8');
const owner=fs.readFileSync(new URL('../multiplatform/owner-ui.js',import.meta.url),'utf8');
const line=start=>{const found=html.split('\n').find(s=>s.startsWith(start));assert.ok(found,start);return found;};
class Element{
 constructor(tag,text=''){this.tag=tag;this.own=String(text);this.children=[];this.style={};this.dataset={};this.open=false;}
 append(...values){this.children.push(...values);}replaceChildren(...values){this.children=values;}
 get textContent(){return this.own+this.children.map(n=>n.textContent).join('');}set textContent(v){this.own=String(v);this.children=[];}
 get lastChild(){return this.children.at(-1);}setAttribute(){}focus(){}
 querySelectorAll(tag){return this.children.flatMap(n=>[...(n.tag===tag?[n]:[]),...n.querySelectorAll(tag)]);}
}
const node=(tag,text)=>new Element(tag,text),button=(text,onclick)=>Object.assign(node('button',text),{onclick});
const proof={status:'native_success',source:'native_bilibili_client',dash_present:false,audio_list_present:false,audio_entries:0,durl_present:true};
const base={run_id:'saved-bili',platform:'bili',state:'completed',media_status:'unavailable',media_reason:'dash_audio_unavailable'};
const saved={records:[{kind:'content',title:'原正文',body:'正文未改'},...Array.from({length:7},(_,i)=>({kind:'comment',text:'原评论'+i}))],media:[],summary:{contents:1,comments:7,media_files:0}};
const task={task_id:'original-task',state:'completed',storage_scope:'cloud',mode:'detail',children:[{platform:'bili',state:'completed',local_run_id:base.run_id,received_captures:9,contents:1,comments:7,supplemental_available:false}]};
function card(run){const section=node('section'),seen=[];
 const context=vm.createContext({node,button,section,document:{activeElement:null},items:[task],watches:[],filter:'all',platformNames:{bili:'B站'},modeNames:{detail:'指定内容'},labels:{},runs:run?[run]:[],idOf:r=>r.run_id,terminal:new Set(['completed','failed']),renderRuns:()=>{},dateText:()=>'',show:r=>seen.push(r),call:async()=>{throw Error('mutation forbidden');},reload:async()=>{},message:()=>{},guarded:fn=>fn(),receipts:()=>{}});
 const names=owner.split('\n').find(x=>x.trimStart().startsWith('const names =')),reasons=owner.split('\n').find(x=>x.trimStart().startsWith('const reasons ='));
 vm.runInContext(line('function mediaNotice(')+'\n'+names+'\n'+reasons+'\n'+owner.slice(owner.indexOf('  function render()'),owner.indexOf('  async function reload()'))+'\nrender();',context);
 return {section,seen};
}
async function detail(run){const els={},$=id=>els[id]??=node('div');
 const context=vm.createContext({node,button,$,document:{activeElement:null},platformNames:{bili:'B站'},action:async(action,payload)=>{assert.equal(action,'import');assert.equal(payload.run_id,run.run_id);return saved;},idOf:r=>r.run_id,analysisView:{reset:()=>{},open:()=>{}},openDialog:id=>$(id).open=true,download:()=>{},resultsView:{ingest:async()=>{}},mediaView:{open:()=>{}},loadingResult:0,selectedRun:null,resultData:null,resultKind:'content',kindOf:r=>r.kind,errorNames:{},token:'offline',fetch:async()=>{throw Error('source forbidden');}});
 vm.runInContext([line('function mediaNotice('),line('function renderResults('),line('async function show(')].join('\n'),context);await context.show(run);return {$,context};
}
let cases=0;
for(const [run,expected] of [
 [base,/旧播放诊断不足，原因待核对/],
 [{...base,media_play_response:proof},/本次播放响应无可用音轨/],
 [{...base,media_status:'failed',media_reason:'audio_play_request_failed',media_play_response:{status:'request_failed',source:'native_bilibili_client'}},/播放接口请求失败/],
 [{...base,media_status:'failed',media_reason:'audio_play_response_invalid'},/响应格式异常，音轨情况待核对/],
]){
 const ownerCard=card(run);assert.match(ownerCard.section.textContent,expected);assert.match(ownerCard.section.textContent,/正文 1 \/ 评论 7/);
 const show=ownerCard.section.querySelectorAll('button').find(b=>b.textContent==='查看结果');assert.equal(show.disabled,false);await show.onclick();assert.equal(ownerCard.seen[0],run);
 assert.equal(ownerCard.section.querySelectorAll('button').some(b=>b.textContent.includes('补采评论')),false);
 const result=await detail(run);assert.match(result.$('summary').textContent,expected);assert.match(result.$('summary').textContent,/内容 1 篇 · 评论 7 条 · 媒体 0 个/);assert.match(result.$('records').textContent,/原正文正文未改/);result.context.resultKind='comment';result.context.renderResults();assert.equal(result.$('records').querySelectorAll('article').length,7);cases++;
}
for(const invalid of [undefined,{status:'native_success'}, {...proof,status:'request_failed'}, {...proof,source:'other'}, {...proof,audio_entries:-1}, {...proof,audio_entries:1001}, {...proof,dash_present:'false'}]){
 const run={...base,media_play_response:invalid};assert.match(card(run).section.textContent,/旧播放诊断不足/);assert.match((await detail(run)).$('summary').textContent,/旧播放诊断不足/);cases++;
}
for(const status of ['downloaded','not_requested','unknown',undefined]){
 const run={...base,media_status:status,media_play_response:proof};assert.doesNotMatch(card(run).section.textContent,/媒体未取得/);assert.doesNotMatch((await detail(run)).$('summary').textContent,/媒体未取得/);cases++;
}
assert.doesNotMatch(card(null).section.textContent,/媒体未取得/);cases++;
console.log(JSON.stringify({ok:true,cases,actual_owner_render:true,actual_result_show:true,source_requests:0,model_requests:0,production_actions:0}));
