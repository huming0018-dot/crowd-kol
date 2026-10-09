// Offline contract only: callers authenticate, authorize and persist atomically.
const VERSION = 'crowd-capture-v1';
export const MAX_CAPTURE_BYTES = 262144;
const encoder = new TextEncoder();
const platforms = {
  xiaohongshu: ['www.xiaohongshu.com', 'xiaohongshu.com'],
  bilibili: ['www.bilibili.com', 'bilibili.com'],
  douyin: ['www.douyin.com', 'douyin.com'],
  kuaishou: ['www.kuaishou.com', 'kuaishou.com'],
  weibo: ['weibo.com', 'www.weibo.com'],
  zhihu: ['www.zhihu.com', 'zhihu.com'],
  tieba: ['tieba.baidu.com'],
};
const statuses = ['observed', 'not_visible', 'not_supported', 'not_requested', 'parse_failed'];
const sources = ['rendered_public_dom', 'platform_api', 'authorized_export'];
const bindingKeys = ['owner_scope', 'actor_ref', 'session_ref', 'task_ref', 'run_id', 'lease_epoch', 'credential_epoch', 'admission_id', 'target_ref', 'source_kind'];
const envelopeKeys = ['contract_version', 'capture_id', ...bindingKeys, 'captured_at', 'payload_schema', 'payload', 'completeness'];
const fail = code => { throw new Error(code); }; // Never include untrusted values in diagnostics.
const check = (condition, code = 'invalid_capture') => { if (!condition) fail(code); };

// Fixed v1 JSON encoding: sorted UTF-16 keys, JSON string escapes, safe integers only.
// Reject JS-only values before JSON.stringify can silently drop or coerce them.
export function canonicalJson(value) {
  let nodes = 0, stringBytes = 0;
  const ancestors = new Set();
  function encode(item, depth) {
    check(++nodes <= 5000 && depth <= 12, 'capture_too_complex');
    if (item === null || typeof item === 'boolean') return String(item);
    if (typeof item === 'number') {
      check(Number.isSafeInteger(item) && !Object.is(item, -0));
      return String(item);
    }
    if (typeof item === 'string') {
      check(item.length <= MAX_CAPTURE_BYTES, 'capture_too_large');
      stringBytes += encoder.encode(item).length;
      check(stringBytes <= MAX_CAPTURE_BYTES, 'capture_too_large');
      check(!/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(item));
      return JSON.stringify(item);
    }
    check(item && typeof item === 'object' && !ancestors.has(item));
    const array = Array.isArray(item);
    check(array ? Object.getPrototypeOf(item) === Array.prototype : [Object.prototype, null].includes(Object.getPrototypeOf(item)));
    const keys = Reflect.ownKeys(item);
    check(keys.length <= 5001, 'capture_too_complex');
    check(keys.every(key => typeof key === 'string'));
    const descriptors = Object.getOwnPropertyDescriptors(item);
    check(keys.every(key => 'value' in descriptors[key] && (descriptors[key].enumerable || (array && key === 'length'))));
    ancestors.add(item);
    let result;
    if (array) {
      check(item.length <= 5000 && keys.length === item.length + 1, 'invalid_capture');
      check(keys.every(key => key === 'length' || /^(0|[1-9]\d*)$/.test(key) && Number(key) < item.length));
      result = '[' + Array.from({length: item.length}, (_, index) => encode(descriptors[index].value, depth + 1)).join(',') + ']';
    } else {
      result = '{' + keys.sort().map(key => {
        check(!['__proto__', 'prototype', 'constructor'].includes(key));
        return encode(key, depth + 1) + ':' + encode(descriptors[key].value, depth + 1);
      }).join(',') + '}';
    }
    ancestors.delete(item);
    return result;
  }
  const result = encode(value, 0);
  check(encoder.encode(result).length <= MAX_CAPTURE_BYTES, 'capture_too_large');
  return result;
}

function shape(value, required, optional = []) {
  check(value && typeof value === 'object' && !Array.isArray(value));
  check(required.every(key => Object.hasOwn(value, key)));
  check(Object.keys(value).every(key => required.includes(key) || optional.includes(key)));
}
function text(value, max, empty = false) {
  check(typeof value === 'string' && value.length <= max && (empty || value.length > 0));
  check(!/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/u.test(value));
}
function ref(value) { check(typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(value)); }
function opaqueId(value) {
  text(value, 256);
  check(!/[\s/?#%&=\\]/u.test(value));
}
function uuid(value) { check(typeof value === 'string' && /^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/.test(value)); }
function epoch(value) { check(Number.isSafeInteger(value) && value >= 1); }
function timestamp(value) {
  check(typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(value));
  const date = new Date(value);
  check(Number.isFinite(date.getTime()) && date.toISOString() === value);
}
function taskRef(value) {
  shape(value, ['namespace'], ['legacy_task_id', 'id']);
  if (value.namespace === 'legacy_v4') {
    shape(value, ['namespace', 'legacy_task_id']);
    check(typeof value.legacy_task_id === 'string' && /^[1-9]\d{0,18}$/.test(value.legacy_task_id));
    check(BigInt(value.legacy_task_id) <= 9223372036854775807n);
  } else {
    check(value.namespace === 'capture_v1');
    shape(value, ['namespace', 'id']); uuid(value.id);
  }
}
function targetRef(value) {
  shape(value, ['platform', 'kind', 'id']);
  check(Object.hasOwn(platforms, value.platform));
  check(['content', 'creator', 'search'].includes(value.kind)); opaqueId(value.id);
}
function validateBinding(value) {
  for (const key of ['owner_scope', 'actor_ref', 'session_ref']) ref(value[key]);
  taskRef(value.task_ref); uuid(value.run_id); uuid(value.admission_id);
  epoch(value.lease_epoch); epoch(value.credential_epoch); targetRef(value.target_ref);
  check(sources.includes(value.source_kind), 'invalid_source_kind');
}
function canonicalUrl(value, platform) {
  text(value, 2048);
  let url; try { url = new URL(value); } catch { fail('invalid_canonical_url'); }
  check(url.protocol === 'https:' && platforms[platform].includes(url.hostname), 'invalid_canonical_url');
  check(!url.username && !url.password && !url.port && !url.search && !url.hash && url.href === value, 'unsafe_canonical_url');
  // No query, fragments or encoded locators: access tokens stay outside this contract.
  check(!value.includes('%') && !value.includes('?') && !value.includes('#'), 'unsafe_canonical_url');
}
function rejectCredentialMaterial(value) {
  // This is a diagnostic tripwire, not a guarantee that arbitrary prose contains no secrets.
  const secretAssignment = /(?:cookie|authorization|access[_-]?token|refresh[_-]?token|xsec[_-]?token|token|api[_-]?key|password)\s*[=:]|\bBearer\s+[A-Za-z0-9._~+\/-]{8,}|-----BEGIN [A-Z ]*PRIVATE KEY-----/i;
  check(!secretAssignment.test(value), 'credential_material');
  for (const match of value.matchAll(/https?:\/\/[^\s<>"']+/gi)) {
    let url; try { url = new URL(match[0]); } catch { fail('unsafe_embedded_url'); }
    check(!url.username && !url.password, 'unsafe_embedded_url');
    // Inspect decoded parameters without changing public links or the source text.
    for (const part of [url.search, url.hash]) {
      let decoded; try { decoded = decodeURIComponent(part.replace(/\+/g, ' ')); } catch { fail('unsafe_embedded_url'); }
      check(!secretAssignment.test(decoded), 'credential_material');
    }
  }
}
function field(value, validateValue) {
  shape(value, ['value', 'status']);
  check(statuses.includes(value.status));
  if (value.status === 'observed') { check(value.value !== null); validateValue(value.value); }
  else check(value.value === null, 'unobserved_value');
}
function metric(value) {
  shape(value, ['value', 'status', 'precision', 'raw_display']);
  check(statuses.includes(value.status));
  if (value.status === 'observed') {
    check(Number.isSafeInteger(value.value) && value.value >= 0);
    check(['exact', 'approximate'].includes(value.precision));
    if (value.raw_display !== null) text(value.raw_display, 64);
    if (value.precision === 'approximate') check(value.raw_display !== null);
  } else check(value.value === null && value.precision === null && value.raw_display === null, 'unobserved_value');
}

export async function normalizeCapture(input) {
  // Snapshot first; subsequent async hashing cannot race a caller mutating input.
  const value = JSON.parse(canonicalJson(input));
  shape(value, envelopeKeys, ['envelope_hash']);
  check(value.contract_version === 1 && value.payload_schema === 'content.v1', 'unsupported_contract');
  uuid(value.capture_id); validateBinding(value); timestamp(value.captured_at);
  const payload = value.payload;
  shape(payload, ['platform', 'content_id', 'creator_id', 'canonical_url', 'content_type', 'title', 'title_origin', 'body', 'published_at', 'metrics']);
  check(Object.hasOwn(platforms, payload.platform) && payload.platform === value.target_ref.platform, 'target_mismatch');
  opaqueId(payload.content_id);
  if (payload.creator_id !== null) opaqueId(payload.creator_id);
  if (value.target_ref.kind === 'content') check(payload.content_id === value.target_ref.id, 'target_mismatch');
  if (value.target_ref.kind === 'creator') check(payload.creator_id === value.target_ref.id, 'target_mismatch');
  canonicalUrl(payload.canonical_url, payload.platform);
  check(['note', 'video', 'article', 'answer', 'post'].includes(payload.content_type));
  field(payload.title, val => text(val, 2048, true));
  check(payload.title.status === 'observed' ? ['original', 'generated_excerpt'].includes(payload.title_origin) : payload.title_origin === null);
  field(payload.body, val => text(val, 100000, true));
  field(payload.published_at, timestamp);
  shape(payload.metrics, ['likes', 'collects', 'comments', 'shares', 'views']);
  for (const entry of Object.values(payload.metrics)) metric(entry);
  shape(value.completeness, ['status', 'scope', 'reason']);
  check(value.completeness.scope === 'single_content');
  if (value.completeness.status === 'complete') {
    check(value.completeness.reason === null);
    check([payload.title, payload.body, payload.published_at, ...Object.values(payload.metrics)]
      .every(entry => ['observed', 'not_requested'].includes(entry.status)), 'incomplete_capture');
  } else {
    check(value.completeness.status === 'partial' && ['field_unavailable', 'content_truncated'].includes(value.completeness.reason));
  }
  // Inspect every string, including IDs and display labels, without logging content.
  function scan(item) {
    if (typeof item === 'string') rejectCredentialMaterial(item);
    else if (item && typeof item === 'object') Object.values(item).forEach(scan);
  }
  scan(value);
  const suppliedHash = value.envelope_hash; delete value.envelope_hash;
  const canonical = canonicalJson(value);
  const bytes = await crypto.subtle.digest('SHA-256', encoder.encode(VERSION + '\n' + canonical));
  const envelope_hash = [...new Uint8Array(bytes)].map(x => x.toString(16).padStart(2, '0')).join('');
  if (suppliedHash !== undefined) check(suppliedHash === envelope_hash, 'envelope_hash_mismatch');
  const result = { ...value, envelope_hash };
  canonicalJson(result); // The persisted envelope, including its hash, obeys the same limit.
  return result;
}

// expected must come from authenticated task/run/admission records, never request JSON.
// Matching is not authorization: the caller still checks consent, revocation and timing.
export async function verifyCaptureBinding(input, expected) {
  const capture = await normalizeCapture(input);
  const binding = JSON.parse(canonicalJson(expected));
  shape(binding, bindingKeys); validateBinding(binding);
  for (const key of bindingKeys) check(canonicalJson(capture[key]) === canonicalJson(binding[key]), 'capture_binding_mismatch');
  return capture;
}

// Pure comparison only, NOT a receipt or a database reservation. Caller owns uniqueness.
export async function classifyCaptureReplay(input, storedBinding = null) {
  const capture = await normalizeCapture(input);
  if (storedBinding === null) return { kind: 'new', capture };
  const prior = JSON.parse(canonicalJson(storedBinding));
  shape(prior, ['owner_scope', 'capture_id', 'envelope_hash']);
  ref(prior.owner_scope); uuid(prior.capture_id);
  check(typeof prior.envelope_hash === 'string' && /^[a-f0-9]{64}$/.test(prior.envelope_hash));
  check(prior.owner_scope === capture.owner_scope && prior.capture_id === capture.capture_id, 'capture_key_mismatch');
  return { kind: prior.envelope_hash === capture.envelope_hash ? 'duplicate' : 'request_reused', capture };
}
