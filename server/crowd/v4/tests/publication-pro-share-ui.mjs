import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
const source=fs.readFileSync(process.argv[2],'utf8');
const start=source.indexOf('  function attachPublicationShare('),end=source.indexOf('  attachPublicationShare(domainExports,dialog);',start);
assert(start>=0&&end>start);
const key='pro-'+'a'.repeat(64), other='pro-'+'b'.repeat(64), hash='c'.repeat(64),project='confirmed-pro-'+'d'.repeat(24);
const verified={ok:true,schema:'crowd-owner-pro-publication-v1',status:'verified',verified:true,pro_key:key,report_hash:hash,project_id:project,items:2,formats:{json:{},html:{},jsonl:{},csv:{}},media_bytes_included:false};
const linked={ok:true,schema:'crowd-owner-publication-share-v1',project_id:project,report_hash:hash,expires_at:new Date(Date.now()+899000).toISOString(),page_url:'https://app-lyart-eta-22.vercel.app/materials#publication=YWJj'};
function harness(pro=true,respond=async p=>p.operation==='links'?linked:verified){
 const parent={children:[],append(...x){this.children.push(...x);}},events={},calls=[];let selected={pro_key:key,items:2},copied=null;
 const dialog={open:true,addEventListener(k,f){events[k]=f;}};
 const ctx={node:(tag,text)=>({tag,textContent:text,disabled:false,hidden:false,setAttribute(){}}),crypto:{randomUUID},Date,Number,Map,Error,Object,RegExp,clearTimeout(){},setTimeout(){return 1;},navigator:{clipboard:{async writeText(x){copied=x;}}},api:async(url,data)=>{calls.push(data.payload);return respond(data.payload);}};
 vm.createContext(ctx);vm.runInContext(source.slice(start,end)+'\nthis.attach=attachPublicationShare;',ctx);
 const controller=ctx.attach(parent,dialog,pro?()=>selected:null);
 return {parent,dialog,calls,controller,get selected(){return selected;},set selected(x){selected=x;},get copied(){return copied;},generate:parent.children[0],copy:parent.children[1],verify:parent.children.find(x=>x.textContent==='核对云保存'),status:parent.children.find(x=>x.tag==='p'),close(){dialog.open=false;events.close();}};
}
let passed=0;
async function test(name,fn){await fn();++passed;console.log('PASS',name);}
await test('legacy exact one call',async()=>{const h=harness(false,async()=>linked);await h.generate.onclick();assert.equal(h.calls.length,1);assert.deepEqual(Object.keys(h.calls[0]),['request_id']);assert.equal(h.copy.disabled,false);});
await test('pro publish then links and copy',async()=>{const h=harness();await h.generate.onclick();assert.deepEqual(h.calls.map(x=>x.operation),['publish','links']);assert.notEqual(h.calls[0].request_id,h.calls[1].request_id);assert(h.calls.every(x=>x.pro_key===key));await h.copy.onclick();assert.equal(h.copied,linked.page_url);});
await test('close while publish pending never issues links',async()=>{let done;const h=harness(true,()=>new Promise(r=>done=r));const promise=h.generate.onclick();h.close();done(verified);await promise;assert.equal(h.calls.length,1);assert.equal(h.copy.disabled,true);});
await test('scope change cancels follow-on issue',async()=>{let done;const h=harness(true,()=>new Promise(r=>done=r));const promise=h.generate.onclick();h.selected={pro_key:other,items:2};h.controller.selectionChanged();done(verified);await promise;assert.equal(h.calls.length,1);assert.equal(h.copy.disabled,true);});
await test('unknown put uses explicit verify then links only',async()=>{let unknown=true;const h=harness(true,async p=>{if(p.operation==='publish'&&unknown)throw Error('publication_pro_publish_unknown_no_retry');return p.operation==='links'?linked:verified;});await h.generate.onclick();assert(h.verify&&!h.verify.hidden);await h.generate.onclick();assert.equal(h.calls.length,1);unknown=false;await h.verify.onclick();assert.deepEqual(h.calls.map(x=>x.operation),['publish','verify']);await h.generate.onclick();assert.deepEqual(h.calls.map(x=>x.operation),['publish','verify','links']);});
await test('duplicate click cannot duplicate put',async()=>{let done;const h=harness(true,p=>p.operation==='publish'?new Promise(r=>done=r):Promise.resolve(linked));const promise=h.generate.onclick();await h.generate.onclick();assert.equal(h.calls.length,1);done(verified);await promise;assert.equal(h.calls.length,2);});
await test('mixed scope publish refused before links',async()=>{const h=harness(true,async()=>({...verified,pro_key:other}));await h.generate.onclick();assert.equal(h.calls.length,1);assert(h.copy.disabled);});
await test('mixed scope link refused',async()=>{const h=harness(true,async p=>p.operation==='links'?{...linked,project_id:'confirmed-pro-'+'e'.repeat(24)}:verified);await h.generate.onclick();assert(h.copy.disabled);});
await test('no scope no network',async()=>{const h=harness();h.selected=null;await h.generate.onclick();assert.equal(h.calls.length,0);});
await test('scope disclosure survives selection/status changes',async()=>{const h=harness();const disclosure=h.parent.children.find(x=>x.tag==='p'&&x.textContent.includes('正文、来源引用和跟踪编号'));assert(disclosure);h.controller.selectionChanged();assert(disclosure.textContent.includes('私有云'));assert(disclosure.textContent.includes('不含媒体文件'));await h.generate.onclick();assert(disclosure.textContent.includes('15分钟'));});
console.log(JSON.stringify({passed,source:process.argv[2]}));
