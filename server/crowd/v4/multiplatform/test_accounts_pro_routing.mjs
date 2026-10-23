import fs from 'node:fs';import vm from 'node:vm';import assert from 'node:assert/strict';
const src=fs.readFileSync(new URL('./accounts-ui.js',import.meta.url),'utf8');
const task='22222222-2222-4222-8222-222222222222',child='33333333-3333-4333-8333-333333333333';
async function fixture(recovery,diagnostic,paused=true,connection,state='check_failed'){
const elements=new Map(),calls=[];const session={pro_connection:connection,login_recovery:recovery,session_id:'11111111-1111-4111-8111-111111111111',platform:'bili',state,login_in_progress:false,login_flow:'pro_bound_official_self',login_error_code:'pro_login_verification_failed',login_wait_reason:'bridge_unavailable',login_diagnostic:diagnostic};
function node(tag,text=''){return {tag,textContent:text,children:[],listeners:{},append(...x){this.children.push(...x)},setAttribute(){},before(){},set id(v){elements.set(v,this)},set innerHTML(v){for(const m of v.matchAll(/id="([^"]+)"/g))if(!elements.has(m[1]))elements.set(m[1],node('div'))},addEventListener(k,f){this.listeners[k]=f},replaceChildren(...x){this.children=x},showModal(){this.open=true},close(){this.open=false;this.listeners.close?.()}}}
const $=k=>{if(!elements.has(k))elements.set(k,node('div'));return elements.get(k)};const context=vm.createContext({node,$,button:(text,onclick)=>Object.assign(node('button',text),{onclick}),document:{body:node('body')},platformNames:{bili:'B站'},setTimeout(){return 1},clearTimeout(){},guarded:fn=>fn(),api:async(path,body)=>{calls.push({path,...body});return body.action==='list'?{sessions:[session]}:{ok:true}},console});vm.runInContext(src,context);await vm.runInContext('accountView.open()',context);function walk(n){return [n,...n.children.flatMap(x=>x&&typeof x==='object'?walk(x):[])]};const rows=walk($('accounts_list')),text=rows.map(x=>x.textContent).join('|');return {rows,text,calls,ctx:context};}

const d={method:'pro_official_self',phase:'failed',bridge_requests:1,official_self_requests:0,bridge_http_status:200,bridge_business_code:101};
const cloud=await fixture({kind:'cloud_pro',task_id:task,child_id:child},d);assert.ok(cloud.text.includes('未取得本平台登录凭据（101）'));assert.ok(cloud.text.includes('平台官方核验：尚未请求'));assert.ok(cloud.text.includes('HTTP 200'));assert.equal(cloud.rows.some(x=>x.textContent==='打开原会话登录'),false);assert.equal(cloud.rows.some(x=>x.textContent==='使用已登录浏览器'),false);await cloud.rows.find(x=>x.textContent==='复用原账号后台核验').onclick();const c=cloud.calls.find(x=>x.action==='recover_cloud_login');assert.deepEqual(JSON.parse(JSON.stringify(c.payload)),{task_id:task,child_id:child});assert.equal(cloud.calls.some(x=>x.action==='open_login'||x.action==='resume'),false);
const legacy=await fixture(undefined,undefined);assert.ok(legacy.rows.find(x=>x.textContent==='打开原会话登录'));await legacy.rows.find(x=>x.textContent==='打开原会话登录').onclick();assert.equal(legacy.calls.filter(x=>x.action==='open_login').length,1);
const blocked=await fixture({kind:'blocked',reason:'secret-raw-untrusted'},d);assert.equal(blocked.rows.some(x=>x.textContent==='打开原会话登录'||x.textContent==='复用原账号后台核验'||x.textContent==='使用已登录浏览器'),false);assert.equal(blocked.text.includes('secret-raw-untrusted'),false);
const bad=await fixture(undefined,{...d,phase:'<SECRET>',bridge_requests:true,bridge_http_status:'<SECRET>',bridge_business_code:'<SECRET>'});assert.equal(bad.text.includes('<SECRET>'),false);assert.ok(bad.text.includes('请求次数未知'));
console.log('PASS diagnostics4 / exact cloud recovery payload / no MC fallback UI / legacy behavior / blocked scope / unsafe diagnostics');
for(const [status,text] of [['configuration_required','重复扫码不能修复'],['identity_required','仍缺原账号的核验记录'],['connected_unverified','开始采集时仍会核验原账号'],['SECRET','']]){
  const value=await fixture(undefined,undefined,true,{status,missing:['SECRET'],raw_error:'SECRET'});
  if(text)assert.ok(value.text.includes(text));
  assert.equal(value.text.includes('SECRET'),false);
  assert.deepEqual(value.calls.map(x=>x.action),['list']);
}
console.log('PASS connection4 / finite copy / read-only list / no raw errors');
const saved=await fixture(undefined,undefined,true,{status:'connected_unverified'},'authenticated');
assert.ok(saved.text.includes('已保存登录核验记录'));assert.equal(saved.text.includes('登录已核验'),false);assert.deepEqual(saved.calls.map(x=>x.action),['list']);
console.log('PASS saved login record is historical / no source or verification action');
