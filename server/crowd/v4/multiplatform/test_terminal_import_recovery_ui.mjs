import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('./fleet-ui.js',import.meta.url),'utf8');
const valid=()=>({ok:true,available:true,schema:'crowd-terminal-import-recovery-v1',state_hash:'a'.repeat(64),source_outcome:'unknown',api_attempts:null,quota_charge:30,released_requests:0,cloud_revision:2,can_park:true,can_reconcile:false,can_verify:false});
async function page(info=valid()){
 const nodes=[],calls=[],timers=[];const state={info,onwrite:null,onread:null};
 const node=(tag,text='')=>{const n={tag,textContent:text,children:[],append(...c){this.children.push(...c)},after(){},replaceChildren(...c){this.children=[...c]}};nodes.push(n);return n};
 const api=async(path,request)=>{calls.push({path,...request});if(path==='/api/tasks'){
  assert.equal(request.action,'reconcile');if(request.payload.recovery_action==='status'){if(state.onread)return state.onread();if(state.info instanceof Error)throw state.info;return state.info}
  if(state.onwrite)return state.onwrite(request.payload);state.info={...valid(),can_park:false,state:'parked'};return {ok:true};
 }return request.action==='workflow_events'?{coverage:'not_connected'}:{available:false,reason:'not_connected'}};
 vm.runInNewContext(source,{node,$:()=>({after(){}}),api,document:{hidden:false},setInterval:f=>timers.push(f),Date,Map,Set,Number,Object,Promise});
 const settle=async()=>{for(let i=0;i<5;i++)await new Promise(setImmediate)};await settle();
 const panel=nodes.find(n=>n.tag==='h3'&&n.textContent==='终止未知请求账务');
 const buttons=()=>nodes.filter(n=>n.tag==='button'&&typeof n.onclick==='function');
 return {state,nodes,calls,timers,settle,panel,buttons,mutations:()=>calls.filter(x=>x.path==='/api/tasks'&&x.payload.recovery_action!=='status')};
}
let n=0;
let p=await page({ok:true,available:false});assert.equal(p.mutations().length,0);assert.equal(p.buttons().length,0);n++;
p=await page();assert(p.nodes.some(x=>x.textContent.includes('实际来源请求次数未知')));assert(p.nodes.some(x=>x.textContent.includes('30 次全额计入，不回收额度')));assert(!p.nodes.some(x=>x.textContent.includes('实际来源请求次数 0')));assert.equal(p.mutations().length,0);n++;
p=await page();let release;p.state.onwrite=()=>new Promise(r=>release=r);const b=p.buttons().at(-1);const first=b.onclick();await p.settle();await b.onclick();await p.timers[3]();assert.equal(p.mutations().length,1);assert.equal(b.disabled,true);p.state.info={...valid(),can_park:false,state:'parked'};release({ok:true});await first;assert.deepEqual(Object.keys(p.mutations()[0].payload).sort(),['expected_revision','expected_state_hash','recovery_action']);n++;
p=await page({...valid(),can_park:false,can_reconcile:true,state:'parked'});p.state.onwrite=async payload=>{if(payload.recovery_action==='reconcile'){p.state.info={...valid(),can_park:false,can_verify:true,state:'unknown'};throw Error('outcome_unknown')}p.state.info={ok:true,available:false};return {ok:true}};await p.buttons().at(-1).onclick();assert.equal(p.mutations().length,1);assert.equal(p.buttons().at(-1).textContent,'只读核对上次云账务，核验后解除停机');await p.buttons().at(-1).onclick();assert.deepEqual(p.mutations().map(x=>x.payload.recovery_action),['reconcile','verify']);n++;
p=await page(new Error('read failed'));assert(p.nodes.some(x=>x.textContent.includes('状态查询失败')));assert.equal(p.mutations().length,0);n++;
p=await page({...valid(),state_hash:'invalid'});assert(p.nodes.some(x=>x.textContent.includes('状态查询失败')));assert.equal(p.buttons().length,0);n++;
p=await page({...valid(),can_park:false,can_reconcile:true,state:'parked'});let oldread;const old={...p.state.info};p.state.onread=()=>{p.state.onread=null;return new Promise(r=>oldread=r)};const poll=p.timers[3]();await p.settle();p.state.onwrite=async()=>{p.state.info={...valid(),can_park:false,can_verify:true,state:'unknown'};throw Error('unknown')};await p.buttons().at(-1).onclick();oldread(old);await poll;await p.settle();assert.equal(p.buttons().at(-1).textContent,'只读核对上次云账务，核验后解除停机');assert.equal(p.mutations().length,1);n++;
assert(p.calls.every(x=>x.path==='/api/cloud'||x.path==='/api/tasks'));assert(p.calls.every(x=>!['start','create','claim','finish'].includes(x.action)));assert(!source.includes('innerHTML'));n++;
console.log(JSON.stringify({status:'PASS_RECOVERY_UI',cases:n,actual_source:false}));
