import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import crypto from 'node:crypto';
const source=fs.readFileSync(new URL('./owner-ui.js',import.meta.url),'utf8');
const dispatchId='00000000-0000-4000-8000-000000000001';
async function fixture({cloud=true,configured=false,storageFailure=false,persistedKey=null}={}){
  const elements=new Map(),calls=[],messages=[],saved=new Map(persistedKey?[['crowd_unified_pending_dispatch',persistedKey]]:[]);let responses={};
  const node=(tag,text='')=>({tag,textContent:text,children:[],disabled:false,hidden:false,value:'',checked:false,dataset:{},style:{},listeners:{},
    get lastChild(){return this.children.at(-1);},set id(value){elements.set(value,this);},setAttribute(){},append(...children){this.children.push(...children);for(const child of children)if(child&&typeof child==='object')child.parentElement=this;},after(){},before(){},focus(){},replaceChildren(...children){this.children=children;},addEventListener(name,handler){this.listeners[name]=handler;},showModal(){this.open=true;},close(){this.open=false;this.listeners.close?.();},closest(){return null;},
    set innerHTML(value){for(const match of value.matchAll(/<([a-z]+)[^>]*\bid="([^"]+)"[^>]*>/g))if(!elements.has(match[2]))elements.set(match[2],node(match[1]));},
    querySelectorAll(selector){const values=[];function walk(item){for(const child of item.children||[]){if(child?.tag==='input'&&(!selector.includes(':checked')||child.checked))values.push(child);if(child?.children)walk(child);}}walk(this);return selector.includes('input')?values:[];},querySelector(selector){return this.querySelectorAll(selector).find(x=>!x.disabled)||null;}});
  const $=id=>{if(!elements.has(id))elements.set(id,node('div'));return elements.get(id);};
  const button=(text,onclick)=>Object.assign(node('button',text),{onclick});
  const normal=async(path,{action,payload})=>{
    if(action==='status')return {storage_scope:cloud?'cloud':'local'};
    if(action==='unified_preview')return {available:true,schema:'crowd-unified-dispatch-v1',ready:true,created:false,routes:[{platform:'xhs',execution_kind:'participant_extension',item_quota:20,state:'queued'},{platform:'bili',execution_kind:'machine_worker',item_quota:20,state:'queued'}]};
    if(action==='unified_create'){assert.equal(saved.get('crowd_unified_pending_dispatch'),payload.idempotency_key,'save operation identity before remote write');return {available:true,schema:'crowd-unified-dispatch-v1',ready:true,created:true,dispatch_id:dispatchId,routes:[]};}
    if(action==='unified_dispatches')return {available:true,schema:'crowd-unified-dispatch-list-v1',dispatches:[]};
    if(action==='list')return {tasks:[],watchlists:[]};
    if(action==='preview')return {children:[{platform:'xhs',state:'queued'}]};
    return {ok:true};
  };
  const ctx=vm.createContext({node,$,button,crypto,api:async(path,body)=>{calls.push({path,...body});const response=responses[body.action];if(response instanceof Error)throw response;return response===undefined?normal(path,body):typeof response==='function'?response(body):response;},document:{body:node('body'),activeElement:null,hidden:false,createTextNode:text=>text},localStorage:{getItem:key=>saved.get(key)||null,setItem:(key,value)=>{if(storageFailure)throw Error('storage unavailable');saved.set(key,value);},removeItem:key=>saved.delete(key)},MutationObserver:class{observe(){}},platformNames:{xhs:'小红书',bili:'B站'},modeNames:{},labels:{},errorNames:{},configured,runs:[],groupedRunIds:new Set(),ownerTaskCounts:{},filter:'all',renderRuns(){},setInterval(){},guarded:fn=>fn().catch(()=>{}),refresh:async()=>{},message:value=>messages.push(value),openDialog:value=>messages.push(value),terminal:new Set(),dateText:x=>x});
  vm.runInContext(source,ctx);
  for(const [key,value]of Object.entries({owner_mode:'search',owner_total:'40',owner_requests:'60',owner_comment_limit:'20',owner_targets:'上海美食',purpose:'noncommercial_research'}))$(key).value=value;
  const settle=()=>new Promise(resolve=>setTimeout(resolve,0));await settle();
  return {$,calls,messages,saved,responses,view:vm.runInContext('ownerView',ctx),settle,submit:()=>$('owner_form').onsubmit({preventDefault(){}})};
}

const f=await fixture();const task={task_id:dispatchId,storage_scope:'cloud',state:'paused',children:[{child_id:'00000000-0000-4000-8000-000000000002',platform:'bili',state:'waiting',reason_code:'login_required'}]};
f.responses.list={tasks:[task]};await f.view.reload();
function walk(n){return [n,...(n.children||[]).flatMap(x=>x&&typeof x==='object'?walk(x):[])];}
let buttons=walk(f.$('owner_tasks')).filter(x=>x.tag==='button');let b=buttons.find(x=>x.textContent==='核验原账号以恢复此任务');assert.ok(b);await b.onclick();
const recovery=f.calls.filter(x=>x.action==='recover_cloud_login');assert.equal(recovery.length,1);assert.equal(recovery[0].path,'/api/accounts');assert.deepEqual(JSON.parse(JSON.stringify(recovery[0].payload)),{task_id:task.task_id,child_id:task.children[0].child_id});assert.equal(f.calls.some(x=>x.action==='resume'),false);
task.storage_scope='local';await f.view.reload();assert.equal(walk(f.$('owner_tasks')).some(x=>x.textContent==='核验原账号以恢复此任务'),false);
console.log('Owner recovery DOM2 passed');
