import {fixture,source} from './ui-fixture.mjs';
import assert from 'node:assert/strict';
let f=await fixture();await f.view.open();await f.$('owner_preview_button').onclick();
const p=f.calls.find(c=>c.action==='unified_preview').payload;
assert.equal(p.source_executor,'pro','normal new Owner preview must explicitly select Pro');
await f.submit();assert.equal(f.calls.find(c=>c.action==='unified_create').payload.source_executor,'pro');
f=await fixture();await f.view.open();f.$('owner_executor').value='mc';await f.$('owner_preview_button').onclick();assert.equal(f.calls.find(c=>c.action==='unified_preview').payload.source_executor,'mc');
assert(source.includes('value="pro"')&&source.includes('value="mc"'),'both explicit engines remain visible');
console.log('PASS normal preview/create explicit Pro and explicit MC retained');

f=await fixture();await f.view.open();await f.$('owner_preview_button').onclick();assert(f.calls.some(c=>c.action==='capabilities'),'normal Pro preview obtains code capability before remote preview');
f=await fixture();await f.view.open();f.responses.capabilities={schema:'crowd-owner-pro-capabilities-v1',default_new_owner_executor:'pro',account_verified:false,source_actions_started:0,platforms:[{id:'xhs',adapter_state:'not_adapted',modes:[]}]};await f.$('owner_preview_button').onclick();await f.submit();assert(!f.calls.some(c=>['unified_preview','unified_create'].includes(c.action)));assert.match(f.$('owner_error').textContent,/Pro/);
f=await fixture();await f.view.open();f.responses.capabilities={};await f.$('owner_preview_button').onclick();assert(!f.calls.some(c=>c.action==='unified_preview'));
console.log('PASS capability-before-preview, not-adapted and missing capability reject before create');

f=await fixture();await f.view.open();f.$('owner_mode').value='dy_pro_trending';f.$('owner_executor').value='mc';await f.$('owner_preview_button').onclick();assert(!f.calls.some(c=>c.action==='unified_preview'));assert.match(f.$('owner_error').textContent,/Pro/);
f=await fixture();await f.view.open();f.responses.unified_preview=Error('pro_media_pipeline_unavailable');await f.$('owner_preview_button').onclick();await f.submit();assert(!f.calls.some(c=>c.action==='unified_create'));assert.match(f.$('owner_error').textContent,/未创建任务/);
console.log('PASS explicit MC never overwritten by named Pro mode; exact unsupported dimensions do not create');
