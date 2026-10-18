import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import crypto from 'node:crypto';
const source=fs.readFileSync(new URL('./owner-ui.js',import.meta.url),'utf8');
const dispatchId='00000000-0000-4000-8000-000000000001';
async function fixture({cloud=true,configured=false,storageFailure=false,persistedKey=null}={}){
  const elements=new Map(),calls=[],messages=[],saved=new Map(persistedKey?[['crowd_unified_pending_dispatch',persistedKey]]:[]);let responses={};
  const node=(tag,text='')=>({tag,textContent:text,children:[],disabled:false,hidden:false,value:'',checked:false,dataset:{},style:{},listeners:{},
    set id(value){elements.set(value,this);},setAttribute(){},append(...children){this.children.push(...children);for(const child of children)if(child&&typeof child==='object')child.parentElement=this;},after(){},before(){},focus(){},replaceChildren(...children){this.children=children;},addEventListener(name,handler){this.listeners[name]=handler;},showModal(){this.open=true;},close(){this.open=false;this.listeners.close?.();},closest(){return null;},
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
let f=await fixture();await f.view.open();assert.equal(f.$('owner_dialog').open,true,'cloud Owner can create without local runner');
await f.$('owner_preview_button').onclick();assert.match(f.$('owner_request_limit_label').textContent,/机器接口尝试上限/);assert.ok(f.calls.some(c=>c.action==='unified_preview'));assert.ok(!f.calls.some(c=>c.action==='preview'));
assert.ok(f.$('owner_preview').children.some(c=>c.textContent.includes('参与者终端自动领取')));
assert.ok(f.$('owner_preview').children.some(c=>c.textContent.includes('采集机器自动领取')));assert.ok(f.$('owner_preview').children.some(c=>c.textContent.includes('本轮试验策略控制')));
await f.submit();assert.equal(f.calls.filter(c=>c.action==='unified_create').length,1);assert.equal(f.saved.size,0);assert.equal(f.$('owner_dialog').open,false);
f=await fixture();f.responses.unified_create=new Error('cloud_outcome_unknown');await f.view.open();await f.$('owner_preview_button').onclick();await f.submit();
const key=f.saved.get('crowd_unified_pending_dispatch');assert.ok(key);assert.equal(f.$('owner_request').disabled,true);assert.equal(f.$('owner_create').disabled,true);
await f.$('owner_preview_button').onclick();await f.submit();assert.equal(f.calls.filter(c=>c.action==='unified_create').length,1);
f.$('owner_dialog').close();await f.view.open();assert.equal(f.$('owner_request').disabled,true);
await f.$('owner_reconcile').onclick();assert.equal(f.calls.at(-1).action,'unified_dispatches');assert.equal(f.calls.at(-1).payload.idempotency_key,key);assert.equal(f.saved.get('crowd_unified_pending_dispatch'),key);
f.responses.unified_dispatches={available:true,schema:'crowd-unified-dispatch-list-v1',dispatches:[{idempotency_key:key,dispatch_id:dispatchId,created:true}]};await f.$('owner_reconcile').onclick();assert.equal(f.saved.size,0);assert.equal(f.calls.filter(c=>c.action==='unified_create').length,1);
const reopened=await fixture({persistedKey:key});await reopened.view.open();assert.equal(reopened.$('owner_request').disabled,true);await reopened.$('owner_reconcile').onclick();assert.equal(reopened.calls.at(-1).payload.idempotency_key,key);assert.ok(!reopened.calls.some(c=>c.action==='unified_create'));
f=await fixture();f.responses.unified_preview={available:true,schema:'crowd-unified-dispatch-v1',ready:false,created:false,reason:'participant_budget_unavailable',routes:[]};await f.view.open();await f.$('owner_preview_button').onclick();assert.equal(f.$('owner_create').disabled,true);await f.submit();assert.ok(!f.calls.some(c=>c.action==='unified_create'));
f=await fixture();f.responses.unified_create={available:true,schema:'crowd-unified-dispatch-v1',ready:false,created:false,reason:'participant_budget_unavailable',routes:[]};await f.view.open();await f.$('owner_preview_button').onclick();await f.submit();assert.equal(f.saved.size,0);assert.equal(f.$('owner_create').disabled,true);
f=await fixture({storageFailure:true});await f.view.open();await f.$('owner_preview_button').onclick();await f.submit();assert.ok(!f.calls.some(c=>c.action==='unified_create'));
f=await fixture({cloud:false,configured:true});await f.view.open();assert.equal(f.$('owner_request_limit_label').textContent,'所有平台合计接口尝试上限');await f.$('owner_preview_button').onclick();await f.submit();assert.ok(f.calls.some(c=>c.action==='create'));assert.ok(!f.calls.some(c=>c.action==='unified_create'));
f=await fixture();f.responses.unified_preview={available:false,reason:'upgrade_or_access_required'};await f.view.open();await f.$('owner_preview_button').onclick();await f.submit();assert.ok(!f.calls.some(c=>['create','unified_create'].includes(c.action)));
console.log('PASS unified Owner UI: automatic routes, cloud-only Owner, explicit unavailable, write-before-send identity, unknown read-only reconcile, no duplicate create, local legacy retained');
