import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {webcrypto,createHash} from 'node:crypto';
import {expression, validate, targetFor, safeFailure} from './participant_pro_rpc.mjs';
const binding={profile:'/private/original-profile',subject:'2fc8765e-700a-41c1-b325-a21c5faa22ce',installation_id:'3cde2858-39a5-42e1-b7ab-dd62053d2dac'};
function context(change={}) {
  const s={enabled:false,outbox:[]};let calls=0;
  const c={runtime:{owner:async()=>binding.subject},storage:{get:async key=>key==='agent'?s:key.startsWith('node-monitor:')?{installation_id:binding.installation_id}:key==='session'?{user:{id:binding.subject}}:null},agent:{active:null,recoveryUnsafe:()=>false,generationOwner:binding.subject},pendingCommands:0,api:{rpc:async(name,args)=>{calls++;return {name,args};}},...change};
  return {c,calls:()=>calls,s};
}
test('reject arbitrary actions, invalid scope and credential arguments',()=>{
  for(const action of ['submit','logout','admin','Runtime.evaluate'])assert.throws(()=>validate({...binding,action,params:{}}));
  assert.throws(()=>validate({...binding,subject:'bad',action:'scope',params:{}}));
  assert.throws(()=>validate({...binding,action:'pro_claim',params:{access_token:'secret'}}));
  assert.throws(()=>validate({...binding,profile:'relative',action:'scope',params:{}}));
});
test('scope reads identity without calling RPC or returning session',async()=>{
  const x=context(),r=await vm.runInNewContext(expression({...binding,action:'scope',params:{}}),x.c);
  assert.equal(r.subject,binding.subject);assert.equal(r.installation_id,binding.installation_id);assert.equal(x.calls(),0);assert.equal(JSON.stringify(r).includes('token'),false);
});
test('wrong owner, installation and active DOM writer cannot call RPC',async()=>{
  for(const change of [{runtime:{owner:async()=> 'another'}},{agent:{active:{},generationOwner:binding.subject,recoveryUnsafe:()=>false}},{storage:{get:async key=>key==='session'?{user:{id:binding.subject}}:key==='agent'?{outbox:[]}:null}}]) {
    const x=context(change);await assert.rejects(vm.runInNewContext(expression({...binding,action:'pro_claim',params:{p_task:19}}),x.c));assert.equal(x.calls(),0);
  }
});
test('RPC uses existing api and rejects owner changes after await',async()=>{
  const x=context();let owner=binding.subject;x.c.runtime.owner=async()=>owner;
  x.c.api.rpc=async()=>{owner='another';return {received:22};};
  await assert.rejects(vm.runInNewContext(expression({...binding,action:'pro_claim',params:{p_task:19}}),x.c),/participant_rpc_outcome_unknown/);
});
test('exact extension service worker and loopback endpoint only',()=>{
  const row={type:'service_worker',id:'ABC',url:'chrome-extension://licijehcpohikchlnkbpjdjdfkcocndg/src/background_v4_2_93.js',webSocketDebuggerUrl:'ws://127.0.0.1:53689/devtools/page/ABC'};
  assert.equal(targetFor([row],53689),row.webSocketDebuggerUrl);
  for(const rows of [[row,row],[{...row,type:'page'}],[{...row,webSocketDebuggerUrl:'ws://example.com:53689/devtools/page/ABC'}]])assert.throws(()=>targetFor(rows,53689));
});
test('Pro current account must match original extension binding without exporting it',async()=>{
  const uid='a'.repeat(24),expected=createHash('sha256').update(binding.subject+'\nxiaohongshu\n'+uid).digest('hex');
  const x=context({crypto:webcrypto,TextEncoder,platformHealth:{read:async()=>({xiaohongshu:{expected_ref:expected,status:'no_page'}})}});
  const r=await vm.runInNewContext(expression({...binding,action:'verify_platform_principal',params:{uid}}),x.c);
  assert.equal(r.matched,true);assert.equal(x.calls(),0);assert.equal(JSON.stringify(r).includes(uid),false);assert.equal(JSON.stringify(r).includes(expected),false);
  const other=await vm.runInNewContext(expression({...binding,action:'verify_platform_principal',params:{uid:'b'.repeat(24)}}),x.c);
  assert.equal(other.matched,false);
});
test('fresh outbox after identity awaits and participant recovery writer block before RPC',async()=>{
  for(const kind of ['outbox','session']){
    const x=context();const get=x.c.storage.get;let last=null;
    x.c.storage.get=async key=>{
      if(key.startsWith('node-monitor:')&&kind==='outbox')last={enabled:false,outbox:[{pending:true}]};
      if(key==='agent'&&last)return last;
      return get(key);
    };
    if(kind==='session')x.c.participantSession={active:{}};
    await assert.rejects(vm.runInNewContext(expression({...binding,action:'pro_claim',params:{p_task:19}}),x.c),/participant_writer_busy/);
    assert.equal(x.calls(),0);assert.equal(x.c.agent.maintenance||null,null);
  }
});
test('known preflight failures preserved, raw exceptions redacted',()=>{
  assert.equal(safeFailure(Error('participant_worker_missing')),'participant_worker_missing');
  assert.equal(safeFailure(Error('secret path/token')),'participant_rpc_outcome_unknown');
});
test('account binding changed during digest cannot approve old principal',async()=>{
  const uid='a'.repeat(24);let expected=createHash('sha256').update(binding.subject+'\nxiaohongshu\n'+uid).digest('hex');
  const x=context({TextEncoder,platformHealth:{read:async()=>({xiaohongshu:{expected_ref:expected}})},crypto:{subtle:{digest:async(...args)=>{const result=await webcrypto.subtle.digest(...args);expected='b'.repeat(64);return result;}}}});
  const r=await vm.runInNewContext(expression({...binding,action:'verify_platform_principal',params:{uid}}),x.c);
  assert.equal(r.matched,false);assert.equal(x.calls(),0);assert.equal(x.c.agent.maintenance,null);
});
test('owner switched during final health read cannot approve principal',async()=>{
  const uid='a'.repeat(24),expected=createHash('sha256').update(binding.subject+'\nxiaohongshu\n'+uid).digest('hex');let reads=0;
  const x=context({crypto:webcrypto,TextEncoder});x.c.platformHealth={read:async()=>{if(++reads===2)x.c.agent.generationOwner='another';return {xiaohongshu:{expected_ref:expected}};}};
  await assert.rejects(vm.runInNewContext(expression({...binding,action:'verify_platform_principal',params:{uid}}),x.c),/participant_scope_changed/);
  assert.equal(x.calls(),0);assert.equal(x.c.agent.maintenance,null);
});
