import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const elements=new Map();
class Element{
  constructor(tag,text=''){this.tag=tag;this.textContent=text;this.children=[];this.events={};this.style={};this.value='';this.classList={add:()=>{},remove:()=>{}};}
  set id(value){this._id=value;elements.set(value,this);}get id(){return this._id;}
  set innerHTML(value){this.html=value;for(const match of value.matchAll(/id="([^"]+)"/g)){const child=new Element('element');child.id=match[1];}}
  append(...values){this.children.push(...values);}replaceChildren(...values){this.children=[...values];}
  get lastChild(){return this.children.at(-1);}querySelector(tag){return this.children.find(child=>child.tag===tag);}
  setAttribute(){}addEventListener(name,callback){this.events[name]=callback;}before(){}after(){}focus(){}
  showModal(){this.open=true;}close(){this.open=false;this.events.close?.();}
}
let responder;
const body=new Element('body');
const context=vm.createContext({api:(route,{action,payload})=>responder(route,action,payload),document:{body},node:(tag,text)=>new Element(tag,text),$:id=>{if(!elements.has(id))elements.set(id,new Element('element'));return elements.get(id);},button:(text,callback)=>{const b=new Element('button',text);b.onclick=callback;return b;},Option:function(text,value){this.text=text;this.value=value;},platformNames:{bili:'B站'},dateText:x=>x,errorNames:{},guarded:callback=>callback(),setTimeout:()=>1});
const ownerSource=fs.readFileSync(new URL('../multiplatform/owner-ui.js',import.meta.url),'utf8');
// Exercise the original receipt function and its DOM, omitting unrelated create-form setup.
vm.runInContext(ownerSource.slice(0,ownerSource.indexOf('  const names ='))+'return {receipts};})();',context);
const owner=vm.runInContext('ownerView',context),receiptDialog=body.children[0],receiptBody=receiptDialog.children[1];
const labels=['关键词搜索','指定详情','作者内容','首页推荐页面采样','热门页面采样'];
const kinds=['search','detail','creator','homefeed','trending'];
const records=[...kinds.map((discovery_kind,i)=>({platform:'bilibili',kind:'content',content_id:String(i),body:'原正文',discovery_kind})),{platform:'bilibili',kind:'content',content_id:'old',body:'旧正文'},{platform:'bilibili',kind:'content',content_id:'bad',discovery_kind:'constructor'},{platform:'bilibili',kind:'comment',content_id:'safe',text:'<img src=x onerror=alert(1)>',discovery_kind:'following'}];
responder=async(route,action)=>{assert.equal(route,'/api/cloud');assert.equal(action,'results');return {items:records.map(record=>({record,receipt:{status:'received'}}))};};
await owner.receipts({task_id:'synthetic'});
const flatten=element=>[String(element.textContent||''),...(element.children||[]).flatMap(flatten)].join('\n');
for(const label of labels)assert.match(flatten(receiptBody),new RegExp('采集入口：'+label));
assert.equal(receiptBody.children.filter(c=>c.tag==='article').filter(c=>flatten(c).includes('采集入口：未记录（unknown）')).length,3);
assert.match(flatten(receiptBody),/<img src=x onerror=alert\(1\)>/);
let resolve;responder=()=>new Promise(done=>{resolve=done;});const stale=owner.receipts({task_id:'old'});receiptDialog.close();resolve({items:[]});await stale;assert.match(flatten(receiptBody),/正在读取/);

vm.runInContext(fs.readFileSync(new URL('../multiplatform/results-ui.js',import.meta.url),'utf8'),context);
const library=vm.runInContext('resultsView',context);
responder=async(route,action)=>{assert.equal(route,'/api/results');if(action==='list')return {records,revision:'r1',total:records.length};if(action==='detail')return {contents:[{}],versions:[{record:records[0]},{record:records[5]}],comments:[{...records[4],kind:'comment',text:'评论自有入口'},{...records[5],kind:'comment',text:'旧评论'}]};throw Error('unexpected action');};
await library.open();const container=elements.get('library_records');
for(const label of labels)assert.match(flatten(container),new RegExp('采集入口：'+label));
assert.equal(container.children.filter(c=>c.tag==='article').filter(c=>flatten(c).includes('采集入口：未记录（unknown）')).length,3);
await container.children[0].children.find(c=>c.textContent==='查看版本、评论与评价').onclick();
assert.match(flatten(container),/正文版本/);assert.match(flatten(container),/采集入口：关键词搜索/);assert.match(flatten(container),/采集入口：热门页面采样/);assert.equal(container.children.filter(c=>c.tag==='article').filter(c=>flatten(c).includes('采集入口：未记录（unknown）')).length,2);
assert.match(flatten(container),/旧正文/);assert.match(flatten(container),/旧评论/);
console.log(JSON.stringify({ok:true,cases:5,cloud_receipts_and_local_list_detail:true,old_entries_unknown:true,source_requests:0,model_requests:0,environment:'Node VM original UI functions with DOM substitute'}));
