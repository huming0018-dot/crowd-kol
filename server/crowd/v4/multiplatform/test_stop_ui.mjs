import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const html=fs.readFileSync(new URL('./dashboard.html',import.meta.url),'utf8');
const owner=fs.readFileSync(new URL('./owner-ui.js',import.meta.url),'utf8');
const labels=vm.runInNewContext('('+html.match(/const labels=(\{[^\n]+\});/)[1]+')');
const reasons=vm.runInNewContext('('+owner.match(/const reasons = (\{[^\n]+\});/)[1]+')');
for(const reason of ['cloud_controller_error','cloud_dispatch_denied','cloud_worker_shutdown','worker_shutdown']) {
  assert.match(labels[reason],/系统停止/);assert.doesNotMatch(labels[reason],/本人/);
  assert.ok(reasons[reason]);assert.doesNotMatch(reasons[reason],/本人/);
}
assert.match(labels.legacy_stop_requested,/不能确认/);assert.match(reasons.legacy_stop_requested,/不能确认/);
assert.match(labels.user_stop,/本人/);assert.match(labels.owner_stop_requested,/Owner/);
const selector=owner.match(/reasons\[(c\.local_stop_reason\|\|c\.local_failure_reason\|\|c\.reason_code\|\|c\.reason)\]/)[1];
const select=vm.runInNewContext('(c=>'+selector+')');
assert.equal(select({local_stop_reason:'legacy_stop_requested',reason_code:'user_stop'}),'legacy_stop_requested');
assert.equal(select({local_stop_reason:'cloud_controller_error',reason:'user_stop'}),'cloud_controller_error');
assert.equal(select({local_failure_reason:'discovery_empty_or_unavailable',reason_code:'user_stop'}),'discovery_empty_or_unavailable');
assert.equal(select({state:'completed'}),undefined);
assert.equal((owner.match(/reasons\[c\.local_stop_reason\|\|c\.local_failure_reason\|\|c\.reason_code\|\|c\.reason\]/g)||[]).length,2);
console.log('PASS stop UI: system/Owner/legacy labels and matching child precedence; no source or browser actions');
