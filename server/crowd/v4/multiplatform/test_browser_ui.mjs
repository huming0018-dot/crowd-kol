import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

function environment(api){
  const ids=new Map();const elements=[];
  class Element{
    constructor(tag,text=''){this.tagName=tag;this.textContent=text;this.children=[];this.open=false;this.events={};elements.push(this);}
    set id(value){this._id=value;ids.set(value,this);}get id(){return this._id;}
    setAttribute(){} before(){} append(...values){this.children.push(...values);} replaceChildren(...values){this.children=values;}
    addEventListener(name,callback){this.events[name]=callback;}
    showModal(){this.open=true;}close(){if(this.open){this.open=false;this.events.close?.();}}
    set innerHTML(value){for(const match of value.matchAll(/id="([^"]+)"/g)){const child=new Element('div');child.id=match[1];this.children.push(child);}}
  }
  const settings=new Element('div');settings.id='open_settings';
  const node=(tag,text='')=>new Element(tag,text);
  const ctx={node,$:id=>ids.get(id),button:(text,fn)=>{const b=node('button',text);b.onclick=fn;return b;},
    document:{body:new Element('body')},platformNames:{bili:'B站'},api,guarded:fn=>Promise.resolve().then(fn),setTimeout:()=>1,clearTimeout(){}};
  vm.createContext(ctx);vm.runInContext(fs.readFileSync(new URL('./accounts-ui.js',import.meta.url),'utf8')+'\nglobalThis.view=accountView;',ctx);
  const buttons=parent=>parent.children.flatMap(x=>x.tagName==='button'?[x]:buttons(x));
  return {ctx,ids,buttons,elements};
}
const session={session_id:'00000000-0000-4000-8000-000000000001',platform:'bili',state:'authenticated',generation:1};
const choices={port:9222,browser_fingerprint:'f'.repeat(64),targets:[{target_id:'a'.repeat(32),page_number:1}]};
const deferred=()=>{let resolve;const promise=new Promise(r=>{resolve=r;});return {promise,resolve};};
const flush=()=>new Promise(r=>setImmediate(r));

{
  const calls=[];const e=environment(async(_path,{action,payload})=>{calls.push({action,payload});return action==='list'?{sessions:[session]}:action==='browser_candidates'?choices:{ok:true,session_id:'new-selected-session'};});
  await e.ctx.view.open();await e.buttons(e.ids.get('accounts_list')).find(x=>x.textContent==='使用已登录浏览器').onclick();
  const picker=e.ids.get('accounts_browser_dialog');
  assert(picker.open);await e.buttons(picker).find(x=>x.textContent==='B站页面 1').onclick();
  assert.deepEqual(calls.filter(x=>x.action!=='list').map(x=>x.action),['browser_candidates','create_browser_session','open_login']);
  assert.equal(calls.find(x=>x.action==='create_browser_session').payload.platform,'bili');
  assert.equal(calls.find(x=>x.action==='open_login').payload.session_id,'new-selected-session');
  assert.equal(picker.open,false);
}
{
  const pending=deferred();let probe=0;const calls=[];
  const e=environment(async(_path,{action})=>{calls.push(action);if(action==='list')return {sessions:[session]};if(action==='browser_candidates')return ++probe===1?pending.promise:{...choices,targets:[{target_id:'b'.repeat(32),page_number:2}]};return {ok:true};});
  await e.ctx.view.open();const reuse=e.buttons(e.ids.get('accounts_list')).find(x=>x.textContent==='使用已登录浏览器');
  const first=reuse.onclick();await flush();const picker=e.ids.get('accounts_browser_dialog');picker.close();await reuse.onclick();
  pending.resolve(choices);await first;
  assert.deepEqual(e.buttons(picker).map(x=>x.textContent),['取消','B站页面 2']);
  assert.equal(calls.filter(x=>x==='create_browser_session').length,0);
}
{
  const pending=deferred();const calls=[];
  const e=environment(async(_path,{action})=>{calls.push(action);if(action==='list')return {sessions:[session]};if(action==='browser_candidates')return choices;if(action==='create_browser_session')return pending.promise;return {ok:true};});
  await e.ctx.view.open();await e.buttons(e.ids.get('accounts_list')).find(x=>x.textContent==='使用已登录浏览器').onclick();
  const picker=e.ids.get('accounts_browser_dialog');const select=e.buttons(picker).find(x=>x.textContent==='B站页面 1');
  const first=select.onclick();await flush();const second=select.onclick();await flush();
  picker.close();pending.resolve({ok:true});await Promise.all([first,second]);
  assert.equal(calls.filter(x=>x==='create_browser_session').length,1);
  assert.equal(calls.filter(x=>x==='open_login').length,0);
}
for(const active of [true,false]){
  const e=environment(async()=>({sessions:[{...session,state:active?'checking':'authenticated',login_wait_reason:'verification_paused',login_in_progress:active}]}));
  await e.ctx.view.open();const list=e.ids.get('accounts_list');
  const texts=parent=>[parent.textContent,...parent.children.flatMap(texts)];
  assert.equal(texts(list).some(text=>text.includes('核验已暂停，原登录窗口保留')),active);
  assert.equal(e.buttons(list).some(button=>button.textContent==='我已登录，继续核验'),active);
  assert.equal(e.buttons(list).find(button=>button.textContent==='打开原会话登录').disabled,active);
  if(!active)assert(texts(list).includes('登录已核验'));
}
console.log('5 actual accounts UI browser-selection, late-response and active/ended verification checks PASS');
