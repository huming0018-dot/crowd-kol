import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('./cloud-ui.js',import.meta.url),'utf8');
async function render(healthValue, fail=false, participantValue=null, participantFailure=false){
  const nodes=[];
  const node=(tag,text='')=>{const item={tag,textContent:text,children:[],setAttribute(){},after(){},append(...children){this.children.push(...children);},replaceChildren(){this.children=[];}};nodes.push(item);return item;};
  const byId=new Map();
  vm.runInNewContext(source,{node,$:id=>{if(!byId.has(id))byId.set(id,node('div'));return byId.get(id);},document:{hidden:false},Date,setInterval(){},api:async (path,body)=>{
    if(path==='/api/health'){if(fail)throw Error('Cookie=SECRET');return healthValue;}
    if(body.action==='participant_health'){if(participantFailure)throw Error('Bearer=SECRET');return participantValue||{storage_scope:'local'};}
    return {storage_scope:'cloud',phase:'idle',outbox:{pending:0}};
  }});
  await new Promise(resolve=>setTimeout(resolve,0));return nodes;
}
const now=Date.now()/1000;
let nodes=await render({storage_scope:'cloud',monitor_alive:true,observed_at:now,max_events:1000,incident_count:1,current:{scheduler_started:true,scheduler_alive:false,health_error:'scheduler_dead',last_tick_at:now,pending:2},incidents:[{at:now,health_error:'scheduler_dead',phase:'running',pending:2}]});
assert.ok(nodes.some(node=>node.textContent.includes('需要处理：调度线程已停止')));
assert.ok(nodes.some(node=>node.textContent.includes('待回传 2')));
nodes=await render({storage_scope:'cloud',monitor_alive:true,observed_at:now-30,current:{scheduler_alive:true,scheduler_started:true}});
assert.ok(nodes.some(node=>node.textContent.includes('无法读取调度健康')));
nodes=await render({},true);assert.ok(nodes.some(node=>node.textContent==='需要处理：运行监控暂不可用。'));assert.ok(nodes.every(node=>!node.textContent.includes('SECRET')));
nodes=await render({},false,{storage_scope:'cloud',checked_at:new Date().toISOString(),participants:[{user_id:'00000000-0000-4000-8000-000000000001',diagnostics_enabled:true,stale:true,version:'4.2.16',enabled:true,queued:2,update_state:'error',ota_poll_error:'ota_manifest_unavailable'},{user_id:'00000000-0000-4000-8000-000000000002',diagnostics_enabled:false}],events:[]});
assert.ok(nodes.some(node=>node.textContent==='参与者监控 · 2 人 · 1 人待处理'));
assert.ok(nodes.some(node=>node.textContent.includes('离线待核对')&&node.textContent.includes('更新异常')));
assert.ok(nodes.some(node=>node.textContent.includes('监控未开启')));
const completed={user_id:'7033ff0c-65d7-4963-b65c-a4ac9e31f03a',diagnostics_enabled:true,stale:false,version:'4.2.52',enabled:false,queued:0,error:'test_completed',update_state:'current'};
const stale={user_id:'00000000-0000-4000-8000-000000000002',diagnostics_enabled:true,stale:true,enabled:false,queued:0,update_state:'current'};
nodes=await render({},false,{storage_scope:'cloud',participants:[completed,stale],events:[{...completed,at:new Date().toISOString()}]});
assert.ok(nodes.some(node=>node.textContent==='参与者监控 · 2 人 · 1 人待处理'));
assert.ok(nodes.some(node=>node.textContent.includes('状态：本轮采集已完成')));
assert.ok(!nodes.some(node=>node.textContent.includes('需要处理：本轮采集已完成')));
assert.ok(!nodes.some(node=>node.tag==='h4'&&node.textContent==='最近参与者异常'));
for(const reason of ['user_stopped','daily_quota','session_rest','action_budget','action_gap','known_note','note_busy','test_quota','test_no_task','no_task']){
  nodes=await render({},false,{storage_scope:'cloud',participants:[{...completed,error:reason}],events:[{...completed,error:reason,at:new Date().toISOString()}]});
  assert.ok(nodes.some(node=>node.textContent==='参与者监控 · 1 人 · 0 人待处理'),reason);
  assert.ok(!nodes.some(node=>node.tag==='h4'&&node.textContent==='最近参与者异常'),reason);
}
for(const issue of [{error:'rate_limit'},{error:'captcha'},{error:'test_partial'},{error:'test_comments_partial'},{error:null,update_state:'helper_unavailable'},{error:null,ota_poll_query_error:'helper_unavailable'}]){
  nodes=await render({},false,{storage_scope:'cloud',participants:[{...completed,...issue}],events:[{...completed,...issue,at:new Date().toISOString()}]});
  assert.ok(nodes.some(node=>node.textContent==='参与者监控 · 1 人 · 1 人待处理'),JSON.stringify(issue));
  assert.ok(nodes.some(node=>node.tag==='h4'&&node.textContent==='最近参与者异常'),JSON.stringify(issue));
}
nodes=await render({},false,null,true);assert.ok(nodes.some(node=>node.textContent==='参与者监控 · 查询失败，需处理'));assert.ok(nodes.every(node=>!node.textContent.includes('SECRET')));
const owner=fs.readFileSync(new URL('./owner-ui.js',import.meta.url),'utf8');
assert.ok(owner.includes('platform_options_by_platform'));
assert.ok(owner.includes("input.type = 'checkbox'"));
console.log('PASS health UI: dead/stale/failure and participant/OTA issues visible, raw errors excluded, multi-platform contract retained');
