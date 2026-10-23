import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('./fleet-ui.js',import.meta.url),'utf8');
const now=new Date().toISOString();
const installation='00000000-0000-4000-8000-000000000001';
async function render(overrides={}){
  const nodes=[],intervals=[],calls=[];
  const node=(tag,text='')=>{const item={tag,textContent:text,children:[],append(...children){this.children.push(...children);},after(){},replaceChildren(...children){this.children=[...children];}};nodes.push(item);return item;};
  const responses={unified_status:{available:true,schema:'crowd-unified-status-v1',checked_at:now,tasks:[{logical_task_id:'participant:31',execution_kind:'participant_extension',platforms:['xhs'],state:'completed',received:2,comments:0}],nodes:[{node_id:installation,installation_id:installation,diagnostics_enabled:true,version:'4.2.60',enabled:false,login_state:'ready',stale:false,updated_at:now}]},node_events:{available:true,schema:'crowd-node-events-v1',checked_at:now,cursor:1,events:[{id:1,node_seq:1,installation_id:installation,logical_task_id:'participant:31',step:'receipt',status:'completed',occurred_at:now}]},workflow_events:{coverage:'machine_lifecycle_phases',event_count:1,events:[{at:Date.now()/1000,phase:'login_resumed',task_id:installation,platform:'bili'}]},...overrides};
  const api=async(_path,request)=>{calls.push(request);const value=responses[request.action];if(value instanceof Error)throw value;return typeof value==='function'?value(request):value;};
  vm.runInNewContext(source,{node,$:()=>node('div'),api,document:{hidden:false},Date,setInterval(callback){intervals.push(callback);}});
  const settle=()=>new Promise(resolve=>setTimeout(resolve,0));await settle();
  return {nodes,intervals,calls,responses,settle,text:()=>nodes.map(row=>row.textContent).join('\n')};
}
const timelineNodes=page=>page.nodes[page.nodes.findIndex(n=>n.tag==='summary'&&n.textContent.startsWith('采集步骤'))+1].children;
let page=await render();
assert.match(page.text(),/云端任务 1 个 · 终端 1 个 · 0 个终端需处理/);
assert.match(page.text(),/正文已收 2/);
assert.match(page.text(),/本轮已结束/);
assert.match(page.text(),/原账号核验通过，等待重新领取/);
assert.match(page.text(),/机器控制阶段与Pro已保存分页同步云端/);
page.responses.node_events={available:true,schema:'crowd-node-events-v1',checked_at:now,cursor:2,events:[{id:2,node_seq:3,installation_id:installation,step:'comments_page',status:'failed',error_code:'Cookie SECRET'}]};
await page.intervals[1]();await page.settle();assert.match(page.text(),/序号曾有跳跃/);assert.ok(!page.text().includes('SECRET'));assert.equal(page.calls.at(-1).payload.after_id,1);
page.responses.node_events=new Error('Authorization SECRET');await page.intervals[1]();await page.settle();assert.match(page.text(),/已显示记录可能过期/);assert.ok(!page.text().includes('SECRET'));
page=await render({unified_status:{available:false,reason:'upgrade_required'},node_events:{available:false,reason:'upgrade_required'}});assert.match(page.text(),/云端接口待升级/);assert.doesNotMatch(page.text(),/已接通/);
page=await render({unified_status:new Error('Cookie SECRET'),workflow_events:new Error('Cookie SECRET')});assert.match(page.text(),/状态待核对/);assert.ok(!page.text().includes('SECRET'));
page=await render({node_events:{available:true,schema:'crowd-node-events-v1',checked_at:now,cursor:9,events:[]}});assert.match(page.text(),/查询失败/);assert.ok(!page.text().includes('读取至 9'));
page=await render({node_events:{available:true,schema:'crowd-node-events-v1',checked_at:now,cursor:0,events:[]}});assert.match(page.text(),/尚未收到步骤记录/);
page=await render();
page.responses.unified_status.nodes=[{node_id:installation,execution_kind:'machine_worker',stale:null,updated_at:null}];
await page.intervals[0]();await page.settle();assert.ok(page.nodes[2].children.some(n=>n.textContent.includes('上报状态待核验')));
assert.ok(!page.nodes[2].children.some(n=>n.textContent.includes('最近有上报')));
for(const state of ['open','leased','complete','exhausted','closed']){
  page.responses.unified_status.tasks[0].state=state;page.responses.unified_status.tasks[0].title='Shanghai sushi';
  await page.intervals[0]();await page.settle();const task=page.nodes[2].children.find(n=>n.tag==='div').children.find(n=>n.tag==='p');
  assert.ok(!task.textContent.includes('状态待核对'),state);assert.ok(task.textContent.includes('Shanghai sushi'));assert.notEqual(task.className,'error',state);
}
page=await render();
assert.ok(timelineNodes(page).some(n=>n.textContent.includes('核对回执')));
page.responses.unified_status.nodes[0].diagnostics_enabled=false;
await page.intervals[0]();await page.settle();assert.ok(!timelineNodes(page).some(n=>n.textContent.includes('核对回执')),'opt-out removes cached events');
page.responses.node_events={available:true,schema:'crowd-node-events-v1',checked_at:now,cursor:2,events:[{id:2,node_seq:2,installation_id:installation,step:'detail',status:'completed'}]};
await page.intervals[1]();await page.settle();assert.ok(!timelineNodes(page).some(n=>n.textContent.includes('读取正文')),'in-flight stale response cannot restore opted-out events');
page=await render();
page.responses.node_events={available:true,schema:'crowd-node-events-v1',checked_at:now,cursor:3,events:[{id:2,node_seq:2,installation_id:installation,step:'session',status:'waiting'},{id:3,node_seq:3,installation_id:installation,step:'telemetry_gap',status:'skipped'}]};
await page.intervals[1]();await page.settle();assert.ok(timelineNodes(page).some(n=>n.textContent.includes('核验登录与执行会话')));assert.ok(timelineNodes(page).some(n=>n.textContent.includes('步骤记录存在缺口')));
for(const [error_code,label] of [['session_rest','等待下一轮'],['action_gap','等待下次来源访问'],['global_pause','系统暂停，等待恢复']]){
  page=await render({node_events:{available:true,schema:'crowd-node-events-v1',checked_at:now,cursor:1,events:[{id:1,node_seq:1,installation_id:installation,step:'session',status:'waiting',error_code}]}});
  assert.ok(timelineNodes(page).some(n=>n.textContent.includes(label)),error_code);
  assert.ok(!timelineNodes(page).some(n=>n.textContent.includes('异常代码待核对')),error_code);
}
console.log('PASS fleet UI: unified tasks/nodes, waiting vs issues, durable phases, safe errors, cursor/gap/read failures, unavailable backend');

page=await render({node_events:{available:true,schema:'crowd-node-events-v1',checked_at:now,cursor:0,events:[],machine_events:[{id:1,worker_id:installation,run_id:installation,task_id:installation,lease_epoch:2,received_at:now,event:{phase:'comments_page',scope:'reply',checkpoint_committed:false,page_index:3,saved_rows:8,cookie:'SECRET'}}]}});
assert.match(page.text(),/回复页/);assert.match(page.text(),/分页记录观测数 8/);assert.match(page.text(),/epoch 2/);assert.ok(!page.text().includes('SECRET'));
page.responses.node_events.machine_events_error='machine_steps_read_failed';await page.intervals[1]();await page.settle();assert.match(page.text(),/机器步骤查询失败/);
