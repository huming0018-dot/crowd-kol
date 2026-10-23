import { canonicalJson, normalizeCapture, verifyCaptureBinding } from './capture-contract.mjs';

class Rejected extends Error {}
const requireValue = (condition, code) => { if (!condition) throw new Rejected(code); };
const error = code => ({ receipt: null, error: { code } });
const contractCodes = new Set(['invalid_capture', 'capture_too_complex', 'capture_too_large', 'unsupported_contract', 'invalid_source_kind', 'invalid_canonical_url', 'unsafe_canonical_url', 'unsafe_embedded_url', 'credential_material', 'unobserved_value', 'target_mismatch', 'incomplete_capture', 'envelope_hash_mismatch', 'capture_binding_mismatch']);
const fieldPaths = ['title', 'body', 'published_at', 'metrics.likes', 'metrics.collects', 'metrics.comments', 'metrics.shares', 'metrics.views'];

function readPrincipal(input) {
  // Supplied only by an authenticated server caller; no HTTP handler exists here.
  const principal = JSON.parse(canonicalJson(input));
  requireValue(principal && typeof principal === 'object' && !Array.isArray(principal)
    && Object.keys(principal).length === 2
    && ['owner_scope', 'actor_ref'].every(key => typeof principal[key] === 'string' && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(principal[key])), 'principal_required');
  return principal;
}

function validateFields(capture, requested) {
  requireValue(Array.isArray(requested) && requested.length > 0
    && new Set(requested).size === requested.length && requested.every(key => fieldPaths.includes(key)), 'invalid_admission');
  for (const path of fieldPaths) {
    const field = path.split('.').reduce((value, key) => value[key], capture.payload);
    requireValue(requested.includes(path) ? field.status !== 'not_requested' : field.status === 'not_requested', 'requested_fields_mismatch');
  }
}

// Offline prototype: db must provide query() and transaction(callback) (PGlite API).
// principal must NEVER be taken from input or a user-editable claim. Its authentication
// is outside this module; the database actor registry supplies a second authorization gate.
export async function receiveCapture(db, authenticatedPrincipal, input) {
  try {
    const principal = readPrincipal(authenticatedPrincipal);
    const capture = await normalizeCapture(input);
    requireValue(capture.owner_scope === principal.owner_scope && capture.actor_ref === principal.actor_ref, 'principal_mismatch');
    return await db.transaction(async tx => {
      // Serializes each actor and its revocation. Cross-actor capture collisions still
      // use database uniqueness and ON CONFLICT; no in-memory idempotency cache.
      const actor = (await tx.query('select enabled from capture_receiver.actors where owner_scope=$1 and actor_ref=$2 for update', [principal.owner_scope, principal.actor_ref])).rows[0];
      requireValue(actor?.enabled === true, 'actor_not_authorized');
      const findCapture = async () => (await tx.query('select actor_ref, admission_id, envelope_hash, receipt from capture_receiver.captures where owner_scope=$1 and capture_id=$2', [principal.owner_scope, capture.capture_id])).rows[0];
      const replay = async stored => {
        requireValue(stored.actor_ref === principal.actor_ref, 'principal_mismatch');
        requireValue(stored.envelope_hash === capture.envelope_hash, 'request_reused');
        // Expired/revoked admission cannot undo an ACK. Only the still-enabled,
        // authenticated original actor receives this metadata-only historical receipt.
        return { receipt: stored.receipt, error: null };
      };
      const stored = await findCapture();
      if (stored) return await replay(stored);

      const admission = (await tx.query(`select binding, parser_version, normalization_version, requested_fields,
        revoked, issued_at, accept_until from capture_receiver.admissions
        where owner_scope=$1 and admission_id=$2 and actor_ref=$3 for update`, [principal.owner_scope, capture.admission_id, principal.actor_ref])).rows[0];
      requireValue(admission, 'admission_missing');
      requireValue(!admission.revoked, 'admission_revoked');
      await verifyCaptureBinding(capture, admission.binding);
      validateFields(capture, admission.requested_fields);
      requireValue(admission.normalization_version === 'capture-v1', 'invalid_admission');
      const window = (await tx.query(`select clock_timestamp() between issued_at and accept_until as open,
        $3::timestamptz between issued_at and clock_timestamp() as plausible_capture_time
        from capture_receiver.admissions where owner_scope=$1 and admission_id=$2`, [principal.owner_scope, capture.admission_id, capture.captured_at])).rows[0];
      requireValue(window.open, 'admission_expired');
      // Client timestamps can reject inconsistent evidence, but cannot extend admission.
      requireValue(window.plausible_capture_time, 'capture_time_invalid');
      const used = (await tx.query('select capture_id from capture_receiver.captures where owner_scope=$1 and admission_id=$2', [principal.owner_scope, capture.admission_id])).rows[0];
      requireValue(!used, 'admission_used');
      const result = await tx.query(`with stamp as (select date_trunc('milliseconds',clock_timestamp()) as at)
        insert into capture_receiver.captures(owner_scope,capture_id,actor_ref,admission_id,run_id,lease_epoch,credential_epoch,
          envelope_hash,envelope,parser_version,normalization_version,requested_fields,received_at,receipt)
        select $1,$2::uuid,$3,$4::uuid,$5::uuid,$6::bigint,$7::bigint,$8,$9::jsonb,a.parser_version,a.normalization_version,a.requested_fields,stamp.at,
          jsonb_build_object('capture_id',$2::text,'status','received','verdict','stored_unreviewed',
            'received_at',to_char(stamp.at at time zone 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'),
            'envelope_hash',$8::text,'run_id',$5::text,'lease_epoch',$6::bigint,'credential_epoch',$7::bigint,'admission_id',$4::text)
        from capture_receiver.admissions a cross join stamp
        where a.owner_scope=$1 and a.admission_id=$4::uuid and not a.revoked
          and clock_timestamp() between a.issued_at and a.accept_until
        on conflict do nothing returning receipt`, [principal.owner_scope, capture.capture_id, principal.actor_ref,
        capture.admission_id, capture.run_id, capture.lease_epoch, capture.credential_epoch, capture.envelope_hash, canonicalJson(capture)]);
      if (result.rows[0]) return { receipt: result.rows[0].receipt, error: null };
      // A different actor may have won the same owner/capture key. Never expose its ACK.
      const winner = await findCapture();
      if (winner) return await replay(winner);
      throw new Rejected('admission_expired');
    });
  } catch (failure) {
    if (failure instanceof Rejected || contractCodes.has(failure?.message)) return error(failure.message);
    // Database errors can contain payloads or SQL details: callers receive a fixed code.
    return error('receiver_unavailable');
  }
}
