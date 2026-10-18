import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('./cloud-ui.js',import.meta.url),'utf8');
const ids=['10000000-0000-4000-8000-000000000001','10000000-0000-4000-8000-000000000002'];
const group={run_id:'20000000-0000-4000-8000-000000000001',task_id:'30000000-0000-4000-8000-000000000001',platform:'bili',pending:2,acknowledged:3,quarantined:2,deferred:0,next_retry_at:null,errors:['invalid_capture_record'],quarantined_capture_ids:ids,retry_allowed:true,reason:null};
const response=groups=>({schema:'crowd-delivery-status-v1',available:true,storage_scope:'cloud',groups});
const settle=()=>new Promise(resolve=>setImmediate(resolve));
async function render(initial){
  const nodes=[],calls=[],intervals=[];let value=initial,retryResult={schema:'crowd-delivery-retry-v1',accepted:true,state:'queued',requeued_capture_ids:ids},readFailure=false,retryHook=null;
  const node=(tag,text='')=>{const item={tag,textContent:text,children:[],disabled:false,hidden:false,setAttribute(){},after(){},before(){},append(...children){this.children.push(...children);},replaceChildren(...children){this.children=children;}};nodes.push(item);return item;};
  const byId=new Map();
  vm.runInNewContext(source,{node,$:id=>{if(!byId.has(id))byId.set(id,node('div'));return byId.get(id);},document:{hidden:false},Date,setInterval(fn){intervals.push(fn);},api:async(path,body)=>{
    calls.push({path,...JSON.parse(JSON.stringify(body))});
    if(body.action==='delivery_status'){if(readFailure)throw Error('Cookie=SECRET');return value;}
    if(body.action==='retry_delivery'){if(retryHook)return retryHook();if(retryResult instanceof Error)throw retryResult;return retryResult;}
    if(path==='/api/health')return {storage_scope:'local'};
    if(body.action==='participant_health')return {storage_scope:'local'};
    return {storage_scope:'cloud',phase:'delivering',outbox:{pending:2,acknowledged:3}};
  }});
  await settle();
  return {nodes,calls,intervals,read(v){value=v;},failRead(){readFailure=true;},retry(v){retryResult=v;},hook(fn){retryHook=fn;},text(){return nodes.map(n=>n.textContent).join('\n');},button(){return nodes.findLast(n=>n.tag==='button'&&n.textContent.startsWith('重试这'));},async refresh(){await nodes.find(n=>n.textContent==='刷新回传状态').onclick();await settle();}};
}
let ui=await render(response([group]));
assert.ok(ui.text().includes('待回传 2 条 · 需处理 2 条'));
assert.ok(ui.text().includes('记录字段未通过云端检查'));
assert.equal(ui.button().disabled,false);
await ui.button().onclick();
assert.deepEqual(ui.calls.filter(c=>c.action==='retry_delivery'),[{path:'/api/cloud',action:'retry_delivery',payload:{capture_ids:ids}}]);
assert.ok(ui.text().includes('原记录已重新排队，等待云端回执'));
assert.equal(ui.calls.filter(c=>c.action==='delivery_status').length,2);

ui=await render(response([{...group,retry_allowed:false,reason:'task_paused'}]));
assert.equal(ui.button().disabled,true);assert.ok(ui.text().includes('原任务已暂停，请先在任务列表继续'));
await ui.button().onclick();assert.equal(ui.calls.filter(c=>c.action==='retry_delivery').length,0);

ui=await render(response([{...group,quarantined:0,quarantined_capture_ids:[],deferred:2,next_retry_at:Date.now()/1000+60,retry_allowed:false,errors:[]}]));
assert.ok(ui.text().includes('2 条等待自动重试'));assert.equal(ui.button(),undefined);

ui=await render({storage_scope:'cloud',available:false,reason:'upgrade_required'});
assert.ok(ui.text().includes('回传恢复入口待升级'));assert.equal(ui.button(),undefined);
ui=await render(response([]));assert.ok(ui.text().includes('当前没有需要处理的回传记录'));

ui=await render(response([{...group,errors:['Cookie=SECRET','toString']} ]));
assert.ok(!ui.text().includes('SECRET'));assert.ok(ui.text().includes('回传状态需要核对'));
ui.retry(Error('cloud_outcome_unknown'));await ui.button().onclick();
assert.ok(ui.text().includes('上次操作结果待核对'));assert.equal(ui.calls.filter(c=>c.action==='retry_delivery').length,1);
await ui.refresh();assert.equal(ui.calls.filter(c=>c.action==='retry_delivery').length,1);
ui.failRead();await ui.refresh();assert.ok(ui.text().includes('待回传状态暂不可读'));assert.ok(!ui.text().includes('SECRET'));

ui=await render(response([group]));let release;
ui.hook(()=>new Promise(resolve=>{release=resolve;}));const button=ui.button();const first=button.onclick();
assert.equal(button.disabled,true);await button.onclick();assert.equal(ui.calls.filter(c=>c.action==='retry_delivery').length,1);
release({schema:'crowd-delivery-retry-v1',accepted:true,state:'queued',requeued_capture_ids:[]});await first;

ui=await render(response([{...group,quarantined_capture_ids:['bad']} ]));
assert.ok(ui.nodes.some(n=>n.textContent==='暂不能重试'&&n.disabled));
ui=await render(response([{...group,run_id:'second-run',quarantined_capture_ids:[ids[1]]},{...group,quarantined_capture_ids:[ids[0]]}]));
await ui.button().onclick();assert.deepEqual(ui.calls.find(c=>c.action==='retry_delivery').payload,{capture_ids:[ids[0]]});
assert.equal(ui.calls.filter(c=>c.action==='retry_delivery').length,1);
console.log('PASS Owner recovery UI: counts, reason, same IDs, pause, deferred, old backend, unknown lookup, single-flight, raw error exclusion');
