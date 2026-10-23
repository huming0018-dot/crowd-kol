import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { canonicalJson, normalizeCapture, verifyCaptureBinding, classifyCaptureReplay, MAX_CAPTURE_BYTES } from '../capture-contract.mjs';

const id = '12345678-1234-4234-8234-123456789abc';
const missing = status => ({ value: null, status });
const count = value => ({ value, status: 'observed', precision: 'exact', raw_display: null });
function fixture() {
  return {
    contract_version: 1, capture_id: id, owner_scope: 'owner-1', actor_ref: 'worker-1', session_ref: 'session-1',
    task_ref: { namespace: 'legacy_v4', legacy_task_id: '9007199254740993' }, run_id: id,
    lease_epoch: 1, credential_epoch: 1, admission_id: id,
    target_ref: { platform: 'xiaohongshu', kind: 'content', id: 'opaque-content-1' },
    source_kind: 'platform_api', captured_at: '2026-10-09T00:00:00.000Z', payload_schema: 'content.v1',
    payload: {
      platform: 'xiaohongshu', content_id: 'opaque-content-1', creator_id: 'author-1',
      canonical_url: 'https://www.xiaohongshu.com/explore/opaque-content-1', content_type: 'note',
      title: { value: '原始标题', status: 'observed' }, title_origin: 'original',
      body: { value: '正文\n第二行 🍣', status: 'observed' }, published_at: missing('not_visible'),
      metrics: { likes: count(0), collects: count(12), comments: count(2), shares: { ...missing('not_visible'), precision: null, raw_display: null }, views: { ...missing('not_requested'), precision: null, raw_display: null } },
    },
    completeness: { status: 'partial', scope: 'single_content', reason: 'field_unavailable' },
  };
}
function reverseKeys(value) {
  if (!value || typeof value !== 'object') return value;
  if (Array.isArray(value)) return value.map(reverseKeys);
  return Object.fromEntries(Object.entries(value).reverse().map(([key, val]) => [key, reverseKeys(val)]));
}
let cases = 0;
async function reject(change, reason = /invalid_capture/) {
  const value = fixture(); change(value);
  await assert.rejects(normalizeCapture(value), reason); cases++;
}

const base = fixture(), capture = await normalizeCapture(base);
assert.equal(capture.task_ref.legacy_task_id, '9007199254740993');
assert.equal(capture.payload.metrics.shares.value, null);
assert.equal(capture.payload.metrics.likes.value, 0);
assert.equal(Object.hasOwn(base, 'envelope_hash'), false);
assert.deepEqual(await normalizeCapture(reverseKeys(base)), capture);
assert.deepEqual(await normalizeCapture(capture), capture);
assert.equal(capture.envelope_hash, createHash('sha256').update('crowd-capture-v1\n' + canonicalJson(base)).digest('hex'));
assert.equal(canonicalJson({ z: 3, a: { '2': 2, '10': 1 } }), '{"a":{"10":1,"2":2},"z":3}');
cases += 8;

const native = fixture(); native.task_ref = { namespace: 'capture_v1', id };
assert.equal((await normalizeCapture(native)).task_ref.id, id); cases++;
const maxLegacy = fixture(); maxLegacy.task_ref.legacy_task_id = '9223372036854775807';
assert.equal((await normalizeCapture(maxLegacy)).task_ref.legacy_task_id, maxLegacy.task_ref.legacy_task_id); cases++;
for (const bad of [9007199254740993, '0', '-1', '01', '9223372036854775808', '9'.repeat(100)]) {
  await reject(value => { value.task_ref.legacy_task_id = bad; });
}
await reject(value => { value.task_ref.id = id; });
await reject(value => { value.task_ref.namespace = 'legacy'; });

const secondPlatform = fixture();
secondPlatform.payload.platform = secondPlatform.target_ref.platform = 'bilibili';
secondPlatform.payload.canonical_url = 'https://www.bilibili.com/video/opaque-content-1';
assert.notEqual((await normalizeCapture(secondPlatform)).envelope_hash, capture.envelope_hash);
assert.equal((await normalizeCapture(secondPlatform)).payload.content_id, capture.payload.content_id); cases += 2;
await reject(value => { value.payload.platform = 'unknown'; }, /target_mismatch/);
await reject(value => { value.payload.content_id = 'other'; }, /target_mismatch/);
const creatorTarget = fixture(); creatorTarget.target_ref = { platform: 'xiaohongshu', kind: 'creator', id: 'author-1' };
assert.equal((await normalizeCapture(creatorTarget)).target_ref.kind, 'creator'); cases++;
await reject(value => { value.target_ref.kind = 'creator'; value.target_ref.id = 'different-author'; }, /target_mismatch/);

for (const url of [
  'https://www.xiaohongshu.com/explore/opaque-content-1?xsec_token=secret',
  'https://www.xiaohongshu.com/explore/opaque-content-1#access_token=secret',
  'https://person:secret@www.xiaohongshu.com/explore/opaque-content-1',
  'https://www.xiaohongshu.com/explore/%73ecret',
  'https://www.xiaohongshu.com/explore/opaque-content-1?',
  'https://www.xiaohongshu.com:443/explore/opaque-content-1',
  'https://www.xiaohongshu.com.evil.example/explore/opaque-content-1',
  'http://www.xiaohongshu.com/explore/opaque-content-1',
  'https://127.0.0.1/explore/opaque-content-1',
]) await reject(value => { value.payload.canonical_url = url; }, /canonical_url/);
for (const prose of [
  'https://example.com/a?token=secret',
  'https://example.com/a?AcCeSs_ToKeN=secret',
  'https://example.com/a?%78sec%5ftoken=secret',
  'https://example.com/a?%41PI%5fKEY=secret',
  'https://example.com/a#ToKeN=secret',
  'https://example.com/a#route?%72efresh_token=secret',
  'https://example.com/a#%41uthorization%3ABearer%20abcdefghijkl',
  'https://person:secret@example.com/a', 'authorization: Bearer abcdefghijkl',
  'xsec_token=abcdefg', '-----BEGIN PRIVATE KEY-----',
]) await reject(value => { value.payload.body.value = prose; }, /credential_material|unsafe_embedded_url/);
const publicLinks = fixture();
publicLinks.payload.body.value = '公开链接 https://example.com/article?page=2&sort=new#section-3\n搜索 https://example.com/search?q=%E9%A4%90%E5%8E%85#results';
const preservedLinks = await normalizeCapture(publicLinks);
assert.equal(preservedLinks.payload.body.value, publicLinks.payload.body.value);
assert.equal(preservedLinks.envelope_hash, createHash('sha256').update('crowd-capture-v1\n' + canonicalJson(publicLinks)).digest('hex'));
assert.deepEqual(await normalizeCapture(preservedLinks), preservedLinks);
assert.notEqual(preservedLinks.envelope_hash, capture.envelope_hash); cases += 4;
await reject(value => { value.payload.cookie = 'secret'; });
await reject(value => { value.access_token = 'secret'; });

const bindingKeys = ['owner_scope', 'actor_ref', 'session_ref', 'task_ref', 'run_id', 'lease_epoch', 'credential_epoch', 'admission_id', 'target_ref', 'source_kind'];
const binding = Object.fromEntries(bindingKeys.map(key => [key, structuredClone(base[key])]));
assert.deepEqual(await verifyCaptureBinding(base, binding), capture); cases++;
for (const key of bindingKeys) {
  const wrong = structuredClone(binding);
  if (key === 'task_ref') wrong[key].legacy_task_id = '7';
  else if (key === 'target_ref') wrong[key].id = 'other';
  else if (key.endsWith('epoch')) wrong[key]++;
  else if (key === 'run_id' || key === 'admission_id') wrong[key] = '87654321-1234-4234-8234-123456789abc';
  else if (key === 'source_kind') wrong[key] = 'rendered_public_dom';
  else wrong[key] += '-other';
  await assert.rejects(verifyCaptureBinding(base, wrong), /capture_binding_mismatch/); cases++;
}
await assert.rejects(verifyCaptureBinding(base, null), /invalid_capture/); cases++;
await reject(value => { value.source_kind = 'dom'; }, /invalid_source_kind/);

const stored = { owner_scope: capture.owner_scope, capture_id: capture.capture_id, envelope_hash: capture.envelope_hash };
assert.equal((await classifyCaptureReplay(base)).kind, 'new');
assert.equal((await classifyCaptureReplay(reverseKeys(base), stored)).kind, 'duplicate');
const changed = fixture(); changed.payload.body.value = '不同正文';
assert.equal((await classifyCaptureReplay(changed, stored)).kind, 'request_reused');
changed.source_kind = 'rendered_public_dom';
assert.equal((await classifyCaptureReplay(changed, stored)).kind, 'request_reused');
await assert.rejects(classifyCaptureReplay(base, { ...stored, owner_scope: 'other-owner' }), /capture_key_mismatch/);
await reject(value => { value.envelope_hash = 'a'.repeat(64); }, /envelope_hash_mismatch/);
cases += 5;

await reject(value => { value.captured_at = '2026-02-30T00:00:00.000Z'; });
await reject(value => { value.captured_at = '2026-10-09T08:00:00+08:00'; });
await reject(value => { value.lease_epoch = 0; });
await reject(value => { value.credential_epoch = Number.MAX_SAFE_INTEGER + 1; });
await reject(value => { value.payload.metrics.shares.value = 0; }, /unobserved_value/);
await reject(value => { value.payload.metrics.likes.value = -1; });
await reject(value => { value.payload.metrics.likes.value = 1.5; });
await reject(value => { value.payload.metrics.likes.precision = 'approximate'; });
await reject(value => { value.payload.published_at.value = '2026-10-09T00:00:00.000Z'; }, /unobserved_value/);
await reject(value => { value.completeness = { status: 'complete', scope: 'single_content', reason: null }; }, /incomplete_capture/);
await reject(value => { value.payload.body.value = 'a'.repeat(100001); });
await reject(value => { value.payload.title.value = '\ud800'; });
await reject(value => { value.payload.body.value = 'a'.repeat(MAX_CAPTURE_BYTES + 1); }, /capture_too_large/);
await reject(value => { value.payload.body.value = '中'.repeat(100000); }, /capture_too_large/);
await reject(value => { value.payload.metrics.likes.value = NaN; });
await reject(value => { value.payload.body.value = undefined; });
await reject(value => { value.payload.body.value = new Date(); });
await reject(value => { value.payload.body.value = 1n; });
await reject(value => { value.payload.body.value = () => ''; });
await reject(value => { value.payload.body.value = value; });
await reject(value => { value.payload.body.value = Array(2); });
await reject(value => { value.payload.body.value = Array(5001).fill(null); }, /capture_too_complex|invalid_capture/);
await reject(value => { value.payload.body.value = Object.create({ inherited: true }); });
await reject(value => { Object.defineProperty(value, 'secret', { value: 1 }); });
await reject(value => { value[Symbol('secret')] = 1; });
let getterCalled = false;
await reject(value => { Object.defineProperty(value, 'payload', { enumerable: true, get() { getterCalled = true; return {}; } }); });
assert.equal(getterCalled, false); cases++;
await reject(value => { value.payload.body.value = JSON.parse('{"__proto__":{"polluted":true}}'); });
await reject(value => { let nested = {}; for (let i = 0; i < 20; i++) nested = { nested }; value.payload.body.value = nested; }, /capture_too_complex/);

console.log(`PASS capture contract: ${cases} assertions/cases; no network, no database, no production receipts`);
