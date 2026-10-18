import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const source=fs.readFileSync(new URL('../multiplatform/results-ui.js',import.meta.url),'utf8');
const start=source.indexOf('  async function detail(row){'),end=source.indexOf("  $('library_search')",start);
assert(start>=0&&end>start);
const actual=source.slice(start,end);
async function probe(row,value){
  const elements=new Map(),nodes=[],buttons=[],calls=[];
  function node(tag,text){const element={tag,textContent:text||'',children:[],disabled:false,value:'',classList:{add(){},remove(){}},setAttribute(){},replaceChildren(...children){this.children=children;},append(...children){this.children.push(...children);this.lastChild=children.at(-1);}};nodes.push(element);return element;}
  const get=id=>{if(!elements.has(id))elements.set(id,node('div'));return elements.get(id);};
  const context=vm.createContext({generation:0,revision:7,dialog:{open:true},$:get,node,
    button:(label,action)=>{const item=node('button',label);item.onclick=action;buttons.push(item);return item;},
    Option:function(label,value){return {label,value};},load(){},
    call:async(action,payload)=>{calls.push({action,payload});return action==='detail'?value:{results_revision:8,value:payload.value,tags:payload.tags};}});
  vm.runInContext(actual,context);await vm.runInContext('detail('+JSON.stringify(row)+')',context);
  const save=buttons.find(item=>item.textContent==='保存业务评价');assert(save);
  return {calls,nodes,save};
}
const row={platform:'zhihu',content_id:'123',entity_ref:'zhihu:content:123:answer',title:'Selected answer'};
const data={content_identity_status:'observed',contents:[{content_type:'answer',owner_evaluations:[]}],versions:[{record:{body:'only answer'}}],comments:[],unassigned_comments:[{text:'unknown <img onerror=alert(1)>'}],unassigned_media:[{path:'output/zhihu/unknown.jpg'}]};
let result=await probe(row,data);
assert.equal(result.calls[0].payload.entity_ref,row.entity_ref);
assert.equal(result.save.disabled,false);await result.save.onclick();
assert.equal(result.calls[1].action,'evaluate');assert.equal(result.calls[1].payload.entity_ref,row.entity_ref);
assert.equal(result.calls[1].payload.content_id,'123');
assert(result.nodes.some(node=>node.textContent==='归属类型未确认的评论 · 1'));
assert(result.nodes.some(node=>node.textContent==='归属类型未确认的媒体 · 1'));
assert(result.nodes.some(node=>node.textContent==='unknown <img onerror=alert(1)>'));
assert(result.nodes.some(node=>node.textContent==='unknown.jpg'));
result=await probe({platform:'zhihu',content_id:'123'},{...data,content_identity_status:'ambiguous_types',contents:[{},{}]});
assert.equal(result.save.disabled,true);await result.save.onclick();assert.equal(result.calls.length,1);
assert(result.nodes.some(node=>node.textContent.includes('请返回列表选择具体回答或文章')));
result=await probe({platform:'xiaohongshu',content_id:'n1',entity_ref:'xiaohongshu:content:n1'},{...data,unassigned_comments:[],unassigned_media:[]});
assert.equal(result.save.disabled,false);await result.save.onclick();assert.equal(result.calls[1].payload.entity_ref,'xiaohongshu:content:n1');
console.log('PASS: actual detail/evaluate selector, ambiguous disabled, unknown visible, non-ZH compatibility');
