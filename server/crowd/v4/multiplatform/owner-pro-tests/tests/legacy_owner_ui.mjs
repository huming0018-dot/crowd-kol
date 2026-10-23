import {fixture,source}from'./ui-fixture.mjs';
import assert from'node:assert/strict';
const dispatchId='00000000-0000-4000-8000-000000000001';
let f=await fixture();await f.view.open();assert.equal(f.$('owner_dialog').open,true,'cloud Owner can create without local runner');
await f.$('owner_preview_button').onclick();assert.match(f.$('owner_request_limit_label').textContent,/机器接口尝试上限/);assert.ok(f.calls.some(c=>c.action==='unified_preview'));assert.ok(!f.calls.some(c=>c.action==='preview'));
assert.ok(f.$('owner_preview').children.some(c=>c.textContent.includes('参与者终端自动领取')));
assert.ok(f.$('owner_preview').children.some(c=>c.textContent.includes('采集机器自动领取')));assert.ok(f.$('owner_preview').children.some(c=>c.textContent.includes('本轮试验策略控制')));
await f.submit();assert.equal(f.calls.filter(c=>c.action==='unified_create').length,1);assert.equal(f.saved.size,0);assert.equal(f.$('owner_dialog').open,false);
f=await fixture();f.responses.unified_create=new Error('cloud_outcome_unknown');await f.view.open();await f.$('owner_preview_button').onclick();await f.submit();
const key=f.saved.get('crowd_unified_pending_dispatch');assert.ok(key);assert.equal(f.$('owner_request').disabled,true);assert.equal(f.$('owner_create').disabled,true);
await f.$('owner_preview_button').onclick();await f.submit();assert.equal(f.calls.filter(c=>c.action==='unified_create').length,1);
f.$('owner_dialog').close();await f.view.open();assert.equal(f.$('owner_request').disabled,true);
await f.$('owner_reconcile').onclick();assert.equal(f.calls.at(-1).action,'unified_dispatches');assert.equal(f.calls.at(-1).payload.idempotency_key,key);assert.equal(f.saved.get('crowd_unified_pending_dispatch'),key);
f.responses.unified_dispatches={available:true,schema:'crowd-unified-dispatch-list-v1',dispatches:[{idempotency_key:key,dispatch_id:dispatchId,created:true}]};await f.$('owner_reconcile').onclick();assert.equal(f.saved.size,0);assert.equal(f.calls.filter(c=>c.action==='unified_create').length,1);
const reopened=await fixture({persistedKey:key});await reopened.view.open();assert.equal(reopened.$('owner_request').disabled,true);await reopened.$('owner_reconcile').onclick();assert.equal(reopened.calls.at(-1).payload.idempotency_key,key);assert.ok(!reopened.calls.some(c=>c.action==='unified_create'));
f=await fixture();f.responses.unified_preview={available:true,schema:'crowd-unified-dispatch-v1',ready:false,created:false,reason:'participant_budget_unavailable',routes:[]};await f.view.open();await f.$('owner_preview_button').onclick();assert.equal(f.$('owner_create').disabled,true);await f.submit();assert.ok(!f.calls.some(c=>c.action==='unified_create'));
f=await fixture();f.responses.unified_create={available:true,schema:'crowd-unified-dispatch-v1',ready:false,created:false,reason:'participant_budget_unavailable',routes:[]};await f.view.open();await f.$('owner_preview_button').onclick();await f.submit();assert.equal(f.saved.size,0);assert.equal(f.$('owner_create').disabled,true);
f=await fixture({storageFailure:true});await f.view.open();await f.$('owner_preview_button').onclick();await f.submit();assert.ok(!f.calls.some(c=>c.action==='unified_create'));
f=await fixture({cloud:false,configured:true});await f.view.open();assert.equal(f.$('owner_request_limit_label').textContent,'所有平台合计接口尝试上限');await f.$('owner_preview_button').onclick();await f.submit();assert.ok(f.calls.some(c=>c.action==='create'));assert.ok(!f.calls.some(c=>c.action==='unified_create'));
f=await fixture();f.responses.unified_preview={available:false,reason:'upgrade_or_access_required'};await f.view.open();await f.$('owner_preview_button').onclick();await f.submit();assert.ok(!f.calls.some(c=>['create','unified_create'].includes(c.action)));
console.log('PASS unified Owner UI: automatic routes, cloud-only Owner, explicit unavailable, write-before-send identity, unknown read-only reconcile, no duplicate create, local legacy retained');

// G07: existing controls retain authoritative options; no new execution selector.
f=await fixture();await f.view.open();f.$('owner_comments').checked=true;f.$('owner_replies').checked=true;f.$('owner_comment_limit').value='0';f.$('owner_total').value='1';f.$('owner_requests').value='8';await f.$('owner_preview_button').onclick();const g07=f.calls.find(c=>c.action==='unified_preview').payload;assert.equal(g07.comments,true);assert.equal(g07.replies,true);assert.equal(g07.max_comments,0);assert.equal(g07.desired_items,1);assert.equal(g07.max_api_requests,8);assert.equal(Object.hasOwn(g07,'execution_target'),false);assert(!source.includes('id="owner_comment_limit" type="number" min="0" max="200"'));console.log('PASS G07 existing Owner controls, auto route and unlimited root-comment semantics');

// Newly supported native dimensions cannot be advertised as a legacy Owner fallback.
f=await fixture();f.responses.unified_preview={available:true,schema:'crowd-unified-dispatch-v1',ready:false,created:false,reason:'owner_pro_comment_options_unavailable',routes:[]};await f.view.open();await f.$('owner_preview_button').onclick();assert.equal(f.$('owner_create').disabled,true);assert.ok(f.$('owner_preview').children.some(x=>x.textContent.includes('尚不支持本次评论上限')));await f.submit();assert.ok(!f.calls.some(x=>x.action==='unified_create'));
