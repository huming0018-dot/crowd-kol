import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('./node-capabilities-ui.js',import.meta.url),'utf8');
const id='00000000-0000-4000-8000-000000000001';
const row={worker_id:id,name:'原节点',platforms:['xhs'],enabled:true,host_os:'darwin',host_arch:'arm64',engine:'mediacrawler_pro',protocol:'vox-acquisition-v1',source_commit:'a'.repeat(40),scopes:['xhs_detail_body_comments_v1'],status:'assignable',reason:null,reported_at:'2026-10-22T04:00:00Z',expires_at:'2026-10-22T04:02:00Z',sequence:1,identity_basis:'cached_authenticated_self_id',identity_verified_at_ms:1792555200000};
const page=(nodes=[row],extra={})=>({available:true,schema:'crowd-worker-capabilities-page-v1',nodes,total:nodes.length,counts:{assignable:nodes.length,needs_attention:0,not_reported:0},next_cursor:null,server_time:'2026-10-22T04:01:00Z',...extra});
async function fixture(response=page()){
 const all=[],calls=[],timers=[];
 function node(tag,text=''){const n={tag,textContent:text,children:[],hidden:false,disabled:false,append(...v){this.children.push(...v);},replaceChildren(...v){this.children=v;},after(...v){all.push(...v);},setAttribute(){}};all.push(n);return n;}
 const ctx=vm.createContext({node,$:()=>node('div'),document:{hidden:false},setInterval:f=>timers.push(f),api:async(path,body)=>{calls.push({path,...body});if(response instanceof Error)throw response;return typeof response==='function'?response(body):response;}});
 vm.runInContext(source,ctx);const settle=()=>new Promise(resolve=>setTimeout(resolve,0));await settle();
 const text=()=>all.filter(x=>x.tag==='details').map(x=>{function walk(n){return[n.textContent||'',...(n.children||[]).map(walk)].join(' ');}return walk(x);}).join(' ');
 return{all,calls,timers,text,settle};
}
let f=await fixture();assert.match(f.text(),/可分配 1/);assert.match(f.text(),/原节点/);assert.match(f.text(),/本地预检/);assert.match(f.text(),/缓存身份/);assert.equal(f.calls[0].action,'worker_capabilities');
assert.match(f.text(),/小红书单篇正文与评论（不含媒体）/);
f=await fixture(page([{...row,scopes:['unrecognized_scope']}]));assert.match(f.text(),/未识别的采集范围/);assert.doesNotMatch(f.text(),/小红书单篇正文与评论/);
f=await fixture(page([],{total:0}));assert.match(f.text(),/尚无机器节点/);
f=await fixture(page([{...row,status:'not_reported',identity_basis:null}],{counts:{assignable:0,needs_attention:0,not_reported:1}}));assert.match(f.text(),/尚未上报/);assert.doesNotMatch(f.text(),/本地预检通过/);
f=await fixture(page([{...row,status:'needs_attention',reason:'capability_expired'}],{counts:{assignable:0,needs_attention:1,not_reported:0}}));assert.match(f.text(),/上报已过期/);
f=await fixture({available:false,reason:'upgrade_required'});assert.match(f.text(),/尚未接通/);
f=await fixture(new Error('Cookie PRIVATE'));assert.match(f.text(),/查询失败/);assert.doesNotMatch(f.text(),/PRIVATE/);
f=await fixture(page([{...row,name:'<img src=x onerror=alert(1)>'}]));assert.match(f.text(),/<img/);assert.ok(!f.all.some(n=>n.tag==='img'),'render names with textContent only');
f=await fixture(page([row],{next_cursor:id,total:300,counts:{assignable:150,needs_attention:100,not_reported:50}}));
const more=f.all.find(n=>n.tag==='button'&&n.textContent==='下一页');assert.ok(more);await more.onclick();await f.settle();assert.equal(f.calls.at(-1).payload.after_worker_id,id);assert.match(f.text(),/300/);
f=await fixture(page([row],{counts:{assignable:1,needs_attention:0,not_reported:0},next_cursor:'invalid'}));assert.match(f.text(),/查询失败/);
assert.ok(!f.calls.some(c=>c.action==='claim'||c.action==='worker_capability_report'),'Owner panel stays read only');
console.log('PASS node capability UI: 10 cases');
