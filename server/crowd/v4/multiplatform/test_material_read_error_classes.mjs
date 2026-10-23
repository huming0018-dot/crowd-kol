// Actual existing api/token-refresh contract in VM; zero actual requests or UI.
import fs from 'node:fs';import path from 'node:path';import vm from 'node:vm';import assert from 'node:assert/strict';import {fileURLToPath} from 'node:url';
const here=path.dirname(fileURLToPath(import.meta.url)),root=process.env.CROWD_MULTIPLATFORM_DIR||here;
if(!fs.existsSync(path.join(root,'dashboard.html')))throw Error('CROWD_MULTIPLATFORM_DIR required; no skip');
const text=fs.readFileSync(path.join(root,'dashboard.html'),'utf8'),start=text.indexOf('let workbenchRefresh=null;'),end=text.indexOf('const action=',start);assert(start>=0&&end>start);
function fixture(fetch){const ctx={token:'a'.repeat(48),URL,location:{origin:'http://127.0.0.1:1'},fetch,notice:0};vm.createContext(ctx);vm.runInContext(text.slice(start,end)+"\nworkbenchUpdatedNotice=()=>{notice++;};globalThis.call=api;",ctx);return ctx;}
let cases=0;
for(const action of ['material_versions','material_feedback_preview']){
 let calls=0;const c=fixture(async()=>{calls++;return{status:403,ok:false,json:async()=>({error:'workbench_page_updated'})};});
 await assert.rejects(c.call('/api/cloud',{action,payload:{pro_key:'pro-'+'a'.repeat(64)}}),/工作台已更新/);assert.equal(calls,1);assert.equal(c.notice,1);cases++;
}
{let calls=0;const c=fixture(async()=>{calls++;return{status:400,ok:false,json:async()=>({error:'knowledge_read_unavailable'})};});await assert.rejects(c.call('/api/cloud',{action:'material_versions',payload:{}}),/knowledge_read_unavailable/);assert.equal(calls,1);cases++;}
{let calls=0;const c=fixture(async()=>{calls++;return{status:200,ok:true,json:async()=>{throw new SyntaxError('synthetic_json');}};});await assert.rejects(c.call('/api/cloud',{action:'material_versions',payload:{}}),/synthetic_json/);assert.equal(calls,1);cases++;}
{let calls=0;const c=fixture(async()=>{calls++;throw new TypeError('synthetic_transport');});await assert.rejects(c.call('/api/cloud',{action:'material_feedback_preview',payload:{}}),/synthetic_transport/);assert.equal(calls,1);cases++;}
{const requests=[];const c=fixture(async(url,options)=>{requests.push({url,method:options.method});if(url==='/')return{ok:true,url:'http://127.0.0.1:1/',headers:{get:()=> 'text/html; charset=utf-8'},text:async()=>"let token='"+'b'.repeat(48)+"'"};return requests.length===1?{status:403,ok:false,json:async()=>({error:'workbench_page_updated'})}:{status:200,ok:true,json:async()=>({ok:true,state:'read'})};});const out=await c.call('/api/cloud',{action:'status',payload:{}});assert.equal(out.state,'read');assert.equal(requests.length,3);assert.equal(requests.filter(x=>x.method==='GET').length,1);cases++;}
console.log(JSON.stringify({status:'PASS',cases,scope:'existing read failure classes reproduced; no historical G40 cause assigned',actual_requests:0,product_UI_changes:0}));
