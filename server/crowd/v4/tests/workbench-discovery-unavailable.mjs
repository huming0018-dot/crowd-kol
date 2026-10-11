import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const html=fs.readFileSync(new URL('../multiplatform/dashboard.html',import.meta.url),'utf8');
const owner=fs.readFileSync(new URL('../multiplatform/owner-ui.js',import.meta.url),'utf8');
class Element{
 constructor(tag,text=''){this.tag=tag;this.own=String(text??'');this.children=[];this.style={};this.dataset={};}
 append(...values){this.children.push(...values);}replaceChildren(){this.children=[];}
 get textContent(){return this.own+this.children.map(n=>n.textContent).join('');}get lastChild(){return this.children.at(-1);}
 querySelectorAll(tag){return this.children.flatMap(n=>[...(n.tag===tag?[n]:[]),...n.querySelectorAll(tag)]);}
}
const node=(tag,text)=>new Element(tag,text),button=(text,onclick)=>Object.assign(node('button',text),{onclick});
function render(reason,local){
 const section=node('section');const child={platform:'dy',state:'failed',reason_code:reason,local_failure_reason:local};
 const context=vm.createContext({node,button,section,document:{activeElement:null},items:[{task_id:'existing',state:'failed',storage_scope:'cloud',children:[child]}],watches:[],filter:'all',platformNames:{dy:'抖音'},modeNames:{},labels:{},runs:[],idOf:r=>r.run_id,terminal:new Set(['failed']),renderRuns:()=>{},dateText:()=>'',show:()=>{},call:()=>{throw Error('no mutation');},reload:()=>{},message:()=>{},guarded:fn=>fn(),receipts:()=>{},mediaNotice:()=>''});
 const lines=['const names =','const reasons ='].map(start=>owner.split('\n').find(s=>s.trimStart().startsWith(start)));
 vm.runInContext(lines.join('\n')+'\n'+owner.slice(owner.indexOf('  function render()'),owner.indexOf('  async function reload()'))+'\nrender();',context);
 return section.textContent;
}
assert.match(render('discovery_empty_or_unavailable'),/首页尚未取得可采候选/);
assert.match(render('no_content_observed','discovery_empty_or_unavailable'),/首页尚未取得可采候选/);
const old=render('no_content_observed');assert.match(old,/本轮没有取得可展示内容；原因见任务详情/);assert.doesNotMatch(old,/检查登录/);
assert.match(render('login_required'),/需要本人重新登录/);
assert.match(render('private_secret_error'),/原因待核对/);
const labels=html.split('\n').find(s=>s.startsWith('const labels='));const ctx=vm.createContext({});vm.runInContext(labels,ctx);assert.equal(vm.runInContext('labels.discovery_empty_or_unavailable',ctx),'首页尚未取得可采候选');
console.log(JSON.stringify({ok:true,cases:6,actual_owner_render:true,old_history_view_neutral:true,login_reason_preserved:true,source_requests:0,model_calls:0,mutations:0}));
