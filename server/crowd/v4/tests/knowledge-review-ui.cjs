'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class Element {
  constructor(tag,text=''){Object.assign(this,{tag,textContent:text,children:[],open:false,value:'',disabled:false,events:{}});}
  append(...items){this.children.push(...items);} replaceChildren(...items){this.children=[...items];}
  setAttribute(){} addEventListener(name,fn){this.events[name]=fn;}
  showModal(){this.open=true;} close(){this.open=false;this.events.close?.();} focus(){}
}
const body=new Element('body'),calls=[];
const id='11111111-1111-4111-8111-111111111111';
const preview={notice:'原决定结果待核对',added_unknowns:{address:6},files:[],observed_gap:{},evidence_refs:[],quotes_preserved:25,
  source_versions_preserved:3,proposal_id:'prop:test',candidate_hash:'a'.repeat(64),role_state:{},human_uid:null,
  principal_kind:'central_owner_service',decision_available:false,actions:{approved:{enabled:false},request_changes:{enabled:false},rejected:{enabled:false}},unresolved_decisions:[id]};
const context=vm.createContext({document:{body},node:(tag,text)=>new Element(tag,text),button:(text,fn)=>{const e=new Element('button',text);e.onclick=fn;return e;},
  localStorage:{getItem:()=>null,setItem:()=>{throw Error('must not write a new intent');}},crypto:{randomUUID:()=>{throw Error('must not create intent');}},
  api:async(path,request)=>{calls.push({path,request});if(request.action==='preview')return preview;
    if(request.action==='publication_preview')return {message:'尚未批准',accepted:false,actions:{}};
    if(request.action==='status')return {state:'outcome_unknown',message:'原决定仍待核对'};
    throw Error('unexpected write '+request.action);}});
vm.runInContext(fs.readFileSync(process.env.CROWD_KNOWLEDGE_UI,'utf8'),context);
function flatten(e){return [e,...e.children.flatMap(x=>x instanceof Element?flatten(x):[])];}
(async()=>{
  await vm.runInContext('knowledgeView.show()',context);
  let elements=flatten(body);
  for(const text of ['采用','退回修改','不采用'])assert.equal(elements.find(x=>x.tag==='button'&&x.textContent===text).disabled,true);
  assert.equal(calls.filter(x=>x.request.action==='status').length,0);
  await elements.find(x=>x.tag==='button'&&x.textContent==='核对原审核决定').onclick();
  const checks=calls.filter(x=>x.request.action==='status');assert.equal(checks.length,1);
  assert.equal(JSON.stringify(checks[0].request.payload),JSON.stringify({intent_id:id}));
  assert(flatten(body).some(x=>x.textContent==='原决定仍待核对'));
  assert.equal(calls.filter(x=>!['preview','publication_preview','status'].includes(x.request.action)).length,0);
  body.children[0].close();preview.unresolved_decisions=[];await vm.runInContext('knowledgeView.show()',context);
  assert(!flatten(body).some(x=>x.tag==='button'&&x.textContent==='核对原审核决定'));
  console.log(JSON.stringify({disabled_unknown_decisions:true,status_explicit_original_only:true,no_auto_write_or_new_intent:true,no_stale_unknown_button:true}));
})().catch(e=>{console.error(e);process.exitCode=1;});
