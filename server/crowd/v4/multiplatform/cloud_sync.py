"""Scoped cloud task adapter and durable machine delivery. No participant rewards."""
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import fcntl
import hashlib
import json
import logging
import socket
import ssl
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import uuid

import mc_runner

SCHEMA = 'crowd-machine-capture-v1'
DELIVERY_RENEW_SECONDS = 20
HEX = re.compile(r'[a-f0-9]{64}\Z')
WORKER_ERRORS = mc_runner.STOP_ERRORS | {'source_outcome_unknown','invalid_cloud_ack','invalid_imported_records',
    'invalid_machine_provenance','invalid_capture_record','existing_saved_reader_missing','existing_saved_selection_mismatch',
    'existing_saved_target_mismatch','existing_saved_target_unverified',
    'invalid_results_revision','results_version_not_found','invalid_results_version','existing_saved_selection_unavailable',
    'capture_size_limit','cloud_response_size_limit','invalid_cloud_response','cloud_redirect_denied','unacknowledged_capture',
    'supplemental_account_binding_denied','invalid_cloud_reconciliation','invalid_encoding','integer_required',
    'duplicate_json_key','invalid_unicode','encoding_limit','unsafe_cloud_file','unsafe_cloud_root','cloud_outcome_unknown',
    'runner_status_unavailable','cloud_delivery_lease_unavailable','cloud_delivery_lease_denied',
    'invalid_cloud_delivery','invalid_delivery_manifest','delivery_manifest_conflict','delivery_defer_denied','delivery_resume_denied'}
RECORD_FIELDS = {'platform','content_id','kind','source_kind','reward_eligible','coverage','origin','discovery_kind',
 'comment_id','parent_comment_id','text','reported_reply_count','title','body','content_type',
 'canonical_id_scheme','platform_fields','author','author_id','author_id_scheme','author_id_status',
 'title_status','title_truncated','metrics','upstream_transport','parent_status',
 'reply_count_semantics','published_at_reported','entity_key','text_status','text_truncated',
 'text_completeness','upstream_truncation_risk','record_hash','media','url','sha256','size_bytes'}


class CloudError(ValueError):
    pass


class DeliveryLeaseError(CloudError):
    """Delivery must stop before a remote write when this exact lease cannot renew."""
    pass


def canonical(value, depth=0, budget=None):
    """crowd-json-int-v1: codepoint keys, integer numbers, explicit control escapes."""
    budget = [0, 5000] if budget is None else budget
    budget[0] += 1
    if depth > 12 or budget[0] > budget[1]:
        raise CloudError('encoding_limit')
    if value is None:
        return 'null'
    if type(value) is bool:
        return 'true' if value else 'false'
    if type(value) in (int, float, Decimal):
        try:
            integer = int(value)
            valid = value == integer and abs(integer) <= 9007199254740991
        except (ValueError, OverflowError):
            valid = False
        if not valid:
            raise CloudError('integer_required')
        return str(integer)
    if isinstance(value, str):
        output = []
        for character in value:
            number = ord(character)
            if 0xd800 <= number <= 0xdfff:
                raise CloudError('invalid_unicode')
            output.append('\\"' if character == '"' else '\\\\' if character == '\\' else
                          '\\u%04x' % number if number < 32 else character)
        return '"' + ''.join(output) + '"'
    if isinstance(value, list):
        return '[' + ','.join(canonical(v, depth + 1, budget) for v in value) + ']'
    if isinstance(value, dict) and all(isinstance(k, str) for k in value):
        return '{' + ','.join(canonical(k, depth + 1, budget) + ':' + canonical(value[k], depth + 1, budget)
                              for k in sorted(value)) + '}'
    raise CloudError('invalid_encoding')


def _hash(domain, value):
    return hashlib.sha256((domain + '\n' + canonical(value)).encode('utf8')).hexdigest()


def _strict_json(data, max_nodes=5000):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise CloudError('duplicate_json_key')
            result[key] = value
        return result
    try:
        value = json.loads(data, object_pairs_hook=pairs, parse_float=Decimal,
                           parse_constant=lambda _: (_ for _ in ()).throw(CloudError('invalid_encoding')))
        canonical(value, budget=[0, max_nodes])
        return value
    except (UnicodeError, json.JSONDecodeError):
        raise CloudError('invalid_cloud_response') from None


def _private_root(root, name):
    base = Path(root).expanduser()
    if base.is_symlink():
        raise CloudError('unsafe_cloud_root')
    path = base.resolve() / name
    if path.is_symlink():
        raise CloudError('unsafe_cloud_root')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    return path


def _private_file(path):
    if path.is_symlink():
        raise CloudError('unsafe_cloud_file')
    if not path.exists():
        os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
    os.chmod(path, 0o600)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise CloudError('cloud_redirect_denied')


def _log_publication_read_failure(stage, error):
    # Fixed metadata only: exception text can contain credentials, URLs or body.
    cause = error
    for _ in range(8):
        if isinstance(cause, urllib.error.URLError) and isinstance(cause.reason, BaseException):
            cause = cause.reason
        else:
            break
    if isinstance(error, urllib.error.HTTPError):
        classification = 'http_error'
    elif isinstance(cause, socket.gaierror):
        classification = 'dns_resolution_failed'
    elif isinstance(cause, ssl.SSLCertVerificationError):
        classification = 'tls_certificate_verification_failed'
    elif isinstance(cause, ssl.SSLError):
        classification = 'tls_failed'
    elif isinstance(cause, (TimeoutError, socket.timeout)):
        classification = 'timeout'
    elif isinstance(cause, ConnectionRefusedError):
        classification = 'connection_refused'
    elif isinstance(cause, ConnectionResetError):
        classification = 'connection_reset'
    else:
        classification = 'transport_other'
    status = error.code if isinstance(error, urllib.error.HTTPError) and type(error.code) is int and 100 <= error.code <= 599 else None
    try:
        logging.getLogger(__name__).warning('cloud_read_diagnostic action=publication_get stage=%s classification=%s http_status=%s', stage, classification, status)
    except Exception:
        pass  # A logging handler must not change the existing request outcome.


class CloudClient:
    def __init__(self, config_path, role='owner', allow_test_loopback=False):
        path = Path(config_path)
        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
            raise CloudError('cloud_config_requires_0600')
        self.config = _strict_json(path.read_bytes())
        self.role = role
        if role not in ('owner', 'worker'):
            raise CloudError('invalid_cloud_role')
        self.endpoint = self.config.get('endpoint', '')
        url = urlsplit(self.endpoint)
        production = url.scheme == 'https' and url.hostname and url.hostname.endswith('.supabase.co') and not url.port
        testing = allow_test_loopback and url.scheme == 'http' and url.hostname in ('127.0.0.1', 'localhost')
        if not (production or testing) or url.username or url.password or url.query or url.fragment or not url.path.endswith('/functions/v1/crowd-machine'):
            raise CloudError('invalid_cloud_endpoint')
        key = self.config.get(role + '_key', '')
        if not isinstance(key, str) or not HEX.fullmatch(key):
            raise CloudError('cloud_role_key_missing')
        project_key = self.config.get('project_key')
        if not isinstance(project_key, str) or not project_key.startswith('sb_publishable_'):
            raise CloudError('active_project_publishable_key_required')
        self.headers = {'Content-Type': 'application/json', 'apikey': project_key,
                        'X-Crowd-' + role.title() + '-Key': key}
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def call(self, action, payload=None):
        body = canonical({'action': action, 'payload': payload or {}}).encode('utf8')
        if len(body) > 300000:
            raise CloudError('capture_size_limit')
        request = urllib.request.Request(self.endpoint, body, self.headers, method='POST')
        attempts = 2 if self.role == 'owner' and action == 'transcript_get' else 1
        pro_feed = self.role == 'owner' and action == 'participant_pro_receipts'
        response_limit = 8 * 1024 * 1024 + 128 if pro_feed else 2000000
        for attempt in range(attempts):
            http_response = False
            read_stage = 'connection'
            try:
                try:
                    response = self.opener.open(request, timeout=15)
                except urllib.error.HTTPError as error:
                    if self.role == 'owner' and action == 'publication_get':
                        _log_publication_read_failure('http_response', error)
                    response = error
                    http_response = True
                with response:
                    read_stage = 'body_read'
                    raw = response.read(response_limit + 1)
                    if len(raw) > response_limit:
                        raise CloudError('cloud_response_size_limit')
                    result = _strict_json(raw, max_nodes=1000000 if pro_feed else 100000)
                if not isinstance(result, dict) or result.get('ok') is not True or not isinstance(result.get('result'), dict):
                    code = result.get('error') if isinstance(result, dict) else None
                    raise CloudError(code if isinstance(code, str) and re.fullmatch(r'[a-z_]{1,80}', code) else 'invalid_cloud_response')
                return result['result']
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                if self.role == 'owner' and action == 'publication_get':
                    _log_publication_read_failure(read_stage, error)
                if (attempt + 1 < attempts and not http_response
                        and isinstance(error, (urllib.error.URLError, TimeoutError))):
                    continue
                code = 'cloud_read_unavailable' if self.role == 'owner' and action in ('participant_pro_receipts', 'task_list', 'task_status', 'continue_failed_source_preview', 'transcript_get', 'participant_health', 'unified_status', 'node_events', 'machine_events', 'unified_preview', 'unified_dispatches') else 'cloud_outcome_unknown'
                raise CloudError(code) from None


class CloudOwnerAdapter:
    """OwnerTasks-compatible UI/watch adapter. Cloud alone owns dispatch."""
    def __init__(self, client, existing_validator=None):
        self.client = client
        self.existing_validator = existing_validator

    def _validate_existing(self, payload):
        if payload.get('source_executor')=='pro' and payload.get('mode')=='trending':
            if self.existing_validator is None:raise CloudError('pro_dy_scope_unsupported')
            self.existing_validator(payload)
        if (payload.get('delivery_basis') == 'existing_saved' and payload.get('mode') == 'detail'
                and 'bili' in (payload.get('platforms') or [])):
            if self.existing_validator is None:
                raise CloudError('existing_saved_target_unverified')
            self.existing_validator(payload)

    def preview(self, payload):
        self._validate_existing(payload)
        return {'ok': True, **self.client.call('task_preview', payload)}

    def create(self, payload):
        self._validate_existing(payload)
        return {'ok': True, **self.client.call('task_create', payload)}

    def list(self):
        return {'ok': True, **self.client.call('task_list')}

    def status(self, task_id):
        return {'ok': True, **self.client.call('task_status', {'task_id': task_id})}

    def _control(self, task_id, desired):
        current = self.status(task_id)['task']
        return {'ok': True, **self.client.call('task_control', {'task_id': task_id,
            'desired_state': desired, 'expected_revision': current['revision']})}

    def stop(self, task_id):
        return self._control(task_id, 'stopped')

    def resume(self, task_id):
        return self._control(task_id, 'running')

    def retry_supplemental(self, payload):
        return {'ok': True, **self.client.call('retry_supplemental', payload)}

    def continuation_preview(self, payload):
        return self.client.call('continue_failed_source_preview', payload)

    def continue_failed_source(self, payload):
        return {'ok': True, **self.client.call('continue_failed_source', payload)}

    def reconcile(self, payload):
        return {'ok': True, **self.client.call('task_reconcile', payload)}

    def start_scheduler(self):
        pass

    def close(self):
        pass


class CloudOutbox:
    MAX_DELIVERY_ATTEMPTS = 5
    PERMANENT_DELIVERY_ERRORS = frozenset({'invalid_capture', 'invalid_capture_record',
        'invalid_machine_provenance', 'capture_hash_conflict', 'capture_size_limit',
        'sensitive_capture', 'invalid_local_capture'})

    def __init__(self, root, client):
        self.root = _private_root(root, 'cloud-outbox')
        self.path = self.root / 'outbox.sqlite3'
        _private_file(self.path)
        self.client = client
        with self._db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS captures(id TEXT PRIMARY KEY, run_id TEXT NOT NULL, envelope TEXT NOT NULL, digest TEXT NOT NULL, state TEXT NOT NULL, receipt TEXT, error TEXT)')
            # Keep the original seven-column table and immutable envelope/ACK bytes intact.
            db.execute('CREATE TABLE IF NOT EXISTS capture_delivery(id TEXT PRIMARY KEY, attempts INTEGER NOT NULL DEFAULT 0, total_attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at REAL NOT NULL DEFAULT 0, last_attempt_at REAL NOT NULL DEFAULT 0, quarantined INTEGER NOT NULL DEFAULT 0, requeues INTEGER NOT NULL DEFAULT 0, last_error TEXT, attempt_token TEXT)')
            # Only a new stage transaction may mint this proof; retries never restore it.
            db.execute('CREATE TABLE IF NOT EXISTS capture_first_delivery(id TEXT PRIMARY KEY, digest TEXT NOT NULL, pristine INTEGER NOT NULL CHECK(pristine IN (0,1)))')

    @contextmanager
    def _db(self):
        if self.path.is_symlink():
            raise CloudError('unsafe_cloud_file')
        db = sqlite3.connect(self.path, timeout=15)
        db.execute('PRAGMA synchronous=FULL')
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def stage_imported(self, records, lease):
        if isinstance(records, dict):
            records = records.get('records')
        if not isinstance(records, list) or len(records) > 2000:
            raise CloudError('invalid_imported_records')
        for key in ('run_id', 'task_id', 'child_id'):
            mc_runner.uid(lease.get(key))
        if type(lease.get('lease_epoch')) is not int or not 1 <= lease['lease_epoch'] <= 2147483647:
            raise CloudError('invalid_capture_record')
        platform = mc_runner.PLATFORMS[lease['platform']]
        ids = []
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            for value in records:
                if not isinstance(value, dict):
                    raise CloudError('invalid_imported_records')
                # ResultsStore.detail returns a wrapper; transport only the original normalized row.
                original = value.get('record', value)
                record = {k: v for k, v in original.items() if k in RECORD_FIELDS}
                if record.get('platform') != platform or record.get('source_kind') != 'mediacrawler_api' or record.get('reward_eligible') is not False:
                    raise CloudError('invalid_machine_provenance')
                if record.get('kind') not in ('content', 'dynamic', 'comment', 'author', 'media') or not isinstance(record.get('content_id'), str):
                    raise CloudError('invalid_capture_record')
                if 'discovery_kind' in record:
                    entry = record['discovery_kind']
                    if not isinstance(entry, str) or entry not in mc_runner.DISCOVERY_KINDS or entry == 'trending' and platform != 'bilibili' and not (platform=='douyin' and __import__('dy_task_scope').supports(lease.get('request',{}))):
                        raise CloudError('invalid_capture_record')
                from results_store import _safe
                _safe(record)
                capture_id = str(uuid.uuid5(uuid.UUID(lease['run_id']), canonical(record)))
                def reuse(candidate_id, expected_record):
                    old = db.execute('SELECT run_id,envelope,digest FROM captures WHERE id=?', (candidate_id,)).fetchone()
                    if old is None:
                        return False
                    try:
                        saved = json.loads(old[1])
                        expected = {'schema':SCHEMA,'capture_id':candidate_id,'task_id':lease['task_id'],
                            'child_id':lease['child_id'],'run_id':lease['run_id'],'lease_epoch':lease['lease_epoch'],
                            'platform':platform,'delivery_basis':lease['delivery_basis'],'source_kind':'machine_api',
                            'adapter_version':'cloud-machine-v1','normalizer_version':'mc-normalized-v2'}
                        valid = (old[0] == lease['run_id'] and type(saved.get('lease_epoch')) is int
                            and set(saved) == set(expected) | {'record','packaged_at'} and canonical(saved) == old[1]
                            and all(saved.get(k) == v for k,v in expected.items())
                            and canonical(saved.get('record')) == canonical(expected_record)
                            and old[2] == _hash(SCHEMA, saved))
                    except (TypeError, ValueError):
                        valid = False
                    if not valid:
                        raise CloudError('capture_hash_conflict')
                    ids.append(candidate_id)
                    return True
                if reuse(capture_id, record):
                    continue  # Persisted timestamp/bytes stay identical after a crash or repeated import.
                if 'discovery_kind' in record:
                    legacy = {k:v for k,v in record.items() if k != 'discovery_kind'}
                    legacy_id = str(uuid.uuid5(uuid.UUID(lease['run_id']), canonical(legacy)))
                    if reuse(legacy_id, legacy):
                        continue  # Never rewrite an old ACK or invent its missing entry tag.
                ids.append(capture_id)
                envelope = {'schema': SCHEMA, 'capture_id': capture_id, 'task_id': lease['task_id'],
                    'child_id': lease['child_id'], 'run_id': lease['run_id'], 'lease_epoch': lease['lease_epoch'],
                    'platform': platform, 'delivery_basis': lease['delivery_basis'], 'source_kind': 'machine_api',
                    'record': record, 'adapter_version': 'cloud-machine-v1', 'normalizer_version': 'mc-normalized-v2',
                    'packaged_at': datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')}
                encoded = canonical(envelope)
                if len(encoded.encode('utf8')) > 262144:
                    raise CloudError('capture_size_limit')
                db.execute('INSERT INTO captures VALUES(?,?,?,?,?,?,?)',
                    (capture_id, lease['run_id'], encoded, _hash(SCHEMA, envelope), 'pending', None, None))
                db.execute('INSERT INTO capture_delivery(id) VALUES(?)', (capture_id,))
                db.execute('INSERT INTO capture_first_delivery VALUES(?,?,1)', (capture_id, _hash(SCHEMA, envelope)))
        return list(dict.fromkeys(ids))

    def flush(self, run_id=None, limit=2000, before_send=None):
        if type(limit) is not int or not 1 <= limit <= 2000:
            raise CloudError('invalid_imported_records')
        with self._db() as db:
            rows = db.execute('SELECT c.id,c.envelope,c.digest,c.run_id FROM captures c LEFT JOIN capture_delivery d ON d.id=c.id WHERE c.state=? AND coalesce(d.quarantined,0)=0 AND coalesce(d.next_attempt_at,0)<=?' +
                (' AND c.run_id=?' if run_id else '') + ' ORDER BY coalesce(d.total_attempts,0),coalesce(d.last_attempt_at,0),c.rowid LIMIT ?',
                ('pending', time.time(), run_id, limit) if run_id else ('pending', time.time(), limit)).fetchall()
        for capture_id, encoded, digest, saved_run_id in rows:
            attempt = None
            attempt_token = None
            first_delivery = False
            try:
                if before_send:
                    before_send()
                # Suppress overlap for 90s; later overlap still uses the same cloud idempotency ID.
                with self._db() as db:
                    db.execute('BEGIN IMMEDIATE')
                    state = db.execute('SELECT state,digest,receipt,error FROM captures WHERE id=?', (capture_id,)).fetchone()
                    history_existed = db.execute('SELECT 1 FROM capture_delivery WHERE id=?', (capture_id,)).fetchone() is not None
                    db.execute('INSERT OR IGNORE INTO capture_delivery(id) VALUES(?)', (capture_id,))
                    retry = db.execute('SELECT attempts,next_attempt_at,quarantined,total_attempts,last_attempt_at,requeues,last_error,attempt_token FROM capture_delivery WHERE id=?', (capture_id,)).fetchone()
                    now = time.time()
                    if state is None or state[:2] != ('pending', digest) or retry[2] or retry[1] > now:
                        continue
                    if retry[0] >= self.MAX_DELIVERY_ATTEMPTS:
                        db.execute('UPDATE capture_delivery SET quarantined=1 WHERE id=?', (capture_id,))
                        db.execute('UPDATE captures SET error=coalesce(error,?) WHERE id=?', ('delivery_attempt_limit', capture_id))
                        continue
                    proof = db.execute('SELECT digest,pristine FROM capture_first_delivery WHERE id=?', (capture_id,)).fetchone()
                    first_delivery = (history_existed and proof == (digest, 1) and state[2:] == (None, None)
                        and retry == (0, 0, 0, 0, 0, 0, None, None))
                    # Consume before IO, even if the outcome is later unknown.
                    db.execute('UPDATE capture_first_delivery SET pristine=0 WHERE id=?', (capture_id,))
                    attempt = retry[0] + 1
                    attempt_token = str(uuid.uuid4())
                    db.execute('UPDATE capture_delivery SET attempts=?,total_attempts=total_attempts+1,last_attempt_at=?,next_attempt_at=?,attempt_token=? WHERE id=?',
                               (attempt, now, now + 90, attempt_token, capture_id))
                try:
                    envelope = json.loads(encoded)
                    if (not isinstance(envelope, dict) or envelope.get('capture_id') != capture_id
                            or envelope.get('run_id') != saved_run_id or type(envelope.get('lease_epoch')) is not int
                            or not 1 <= envelope['lease_epoch'] <= 2147483647
                            or not all(mc_runner.uid(envelope.get(k)) == envelope[k] for k in ('task_id','child_id','run_id'))
                            or canonical(envelope) != encoded or _hash(SCHEMA, envelope) != digest):
                        raise ValueError('invalid_local_capture')
                    binding = {'run_id': envelope['run_id'], 'lease_epoch': envelope['lease_epoch']}
                except (ValueError, TypeError, KeyError, mc_runner.BridgeError):
                    raise CloudError('invalid_local_capture') from None
                receipt = None
                if not first_delivery:
                    response = self.client.call('receipt', {**binding, 'capture_id': capture_id, 'envelope_hash': digest})
                    if not isinstance(response, dict) or 'receipt' not in response:
                        raise CloudError('invalid_cloud_response')
                    receipt = response['receipt']
                if receipt is None:
                    if before_send and not first_delivery:
                        before_send()
                    response = self.client.call('capture', {**binding, 'envelope': envelope, 'envelope_hash': digest})
                    if not isinstance(response, dict) or 'receipt' not in response:
                        raise CloudError('invalid_cloud_response')
                    receipt = response['receipt']
                if not isinstance(receipt, dict) or type(receipt.get('lease_epoch')) is not int or any(canonical(receipt.get(k)) != canonical(v) for k, v in {
                    'capture_id': capture_id, 'envelope_hash': digest, **binding, 'task_id': envelope['task_id'],
                    'child_id': envelope['child_id'], 'status': 'received', 'source_kind': 'machine_api', 'reward_eligible': False}.items()):
                    raise CloudError('invalid_cloud_ack')
                with self._db() as db:
                    db.execute('UPDATE captures SET state=?,receipt=?,error=NULL WHERE id=? AND digest=? AND state=?',
                               ('acknowledged', canonical(receipt), capture_id, digest, 'pending'))
                    db.execute('UPDATE capture_delivery SET next_attempt_at=0,quarantined=0 WHERE id=?', (capture_id,))
            except DeliveryLeaseError:
                if attempt is not None:
                    with self._db() as db:
                        # A denied send did not consume a payload retry; actual lookup count stays.
                        db.execute('UPDATE capture_delivery SET attempts=max(0,attempts-1),next_attempt_at=0 WHERE id=? AND attempt_token=?', (capture_id, attempt_token))
                raise
            except (CloudError, ValueError) as error:
                code = str(error) if re.fullmatch(r'[a-z_]{1,80}', str(error)) else 'cloud_outcome_unknown'
                with self._db() as db:
                    updated = db.execute('UPDATE captures SET error=? WHERE id=? AND digest=? AND state=?' +
                        (' AND EXISTS(SELECT 1 FROM capture_delivery d WHERE d.id=captures.id AND d.attempt_token=?)' if attempt_token else ''),
                        (code, capture_id, digest, 'pending', attempt_token) if attempt_token else (code, capture_id, digest, 'pending')).rowcount
                    if updated and attempt is not None:
                        quarantined = code in self.PERMANENT_DELIVERY_ERRORS or attempt >= self.MAX_DELIVERY_ATTEMPTS
                        delay = 0 if attempt == 1 else min(300, 5 * 2 ** (attempt - 2))
                        db.execute('UPDATE capture_delivery SET quarantined=?,next_attempt_at=?,last_error=? WHERE id=?',
                                   (int(quarantined), time.time() + delay, code, capture_id))
                # A lost response never deletes data or causes another source dispatch.
                if code in ('worker_revoked', 'principal_denied', 'cloud_outcome_unknown'):
                    break
        return self.stats(run_id)

    def retry_quarantined(self, capture_ids):
        """Explicit operator retry of the same bytes after backend repair; never a source retry."""
        if not isinstance(capture_ids, list) or not 1 <= len(capture_ids) <= 2000:
            raise CloudError('invalid_capture_retry')
        try:
            ids = [mc_runner.uid(value) for value in capture_ids]
        except (mc_runner.BridgeError, ValueError, TypeError):
            raise CloudError('invalid_capture_retry') from None
        if len(set(ids)) != len(ids):
            raise CloudError('invalid_capture_retry')
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            for identity in ids:
                state = db.execute('SELECT c.state,d.quarantined FROM captures c JOIN capture_delivery d ON d.id=c.id WHERE c.id=?', (identity,)).fetchone()
                if state != ('pending', 1):
                    raise CloudError('capture_not_quarantined')
            for identity in ids:
                db.execute('UPDATE capture_delivery SET attempts=0,next_attempt_at=0,last_attempt_at=?,quarantined=0,requeues=requeues+1,attempt_token=NULL WHERE id=?', (time.time(), identity))
        return {'requeued_capture_ids': ids, **self.stats()}

    def manifest(self, lease):
        """Freeze every required original capture, including ACKs; never restage after parking."""
        refs = {}
        with self._db() as db:
            rows = db.execute('SELECT id,envelope,digest FROM captures WHERE run_id=? ORDER BY id', (lease['run_id'],)).fetchall()
        for identity, encoded, digest in rows:
            try:
                envelope = _strict_json(encoded)
                if (canonical(envelope) != encoded or _hash(SCHEMA, envelope) != digest
                        or envelope.get('capture_id') != identity
                        or type(envelope.get('lease_epoch')) is not int
                        or any(envelope.get(k) != lease[k] for k in ('run_id','task_id','child_id','lease_epoch'))):
                    raise CloudError('invalid_delivery_manifest')
            except (ValueError, TypeError, KeyError):
                raise CloudError('invalid_delivery_manifest') from None
            refs[identity] = digest
        if not 1 <= len(refs) <= 2000:
            raise CloudError('invalid_delivery_manifest')
        return refs

    def stats(self, run_id=None):
        with self._db() as db:
            rows = db.execute('SELECT c.id,c.state,c.error,coalesce(d.quarantined,0),coalesce(d.next_attempt_at,0),coalesce(d.total_attempts,0) FROM captures c LEFT JOIN capture_delivery d ON d.id=c.id' + (' WHERE c.run_id=?' if run_id else ''),
                              (run_id,) if run_id else ()).fetchall()
        now = time.time()
        quarantined = [r[0] for r in rows if r[1] == 'pending' and r[3]]
        retry_times = [r[4] for r in rows if r[1] == 'pending' and not r[3] and r[4] > now]
        return {'pending': sum(r[1] == 'pending' for r in rows),
                'acknowledged': sum(r[1] == 'acknowledged' for r in rows),
                'capture_ids': [r[0] for r in rows], 'errors': list(dict.fromkeys(r[2] for r in rows if r[2])),
                'quarantined': len(quarantined), 'quarantined_capture_ids': quarantined,
                'retryable': sum(r[1] == 'pending' and not r[3] and r[4] <= now for r in rows),
                'deferred': len(retry_times), 'next_retry_at': min(retry_times) if retry_times else None,
                'delivery_attempts': sum(r[5] for r in rows)}


class CloudWorker:
    """One durable dispatch controller, backed by cloud leases and the existing runner."""
    def __init__(self, root, client, runner_callback, session_selector=None, existing_reader=None, interval=5, postprocessing_callback=None, capability_provider=None):
        self.capability_provider = capability_provider
        self.root = _private_root(root, 'cloud-worker')
        self.path = self.root / 'state.json'
        self.lock_path = self.root / 'worker.lock'
        _private_file(self.lock_path)
        if self.path.is_symlink():
            raise CloudError('unsafe_cloud_file')
        self.client, self.runner = client, runner_callback
        self.session_selector, self.existing_reader = session_selector, existing_reader
        self.postprocessing_callback = postprocessing_callback
        self.outbox = CloudOutbox(root, client)
        from health_events import HealthEvents
        self.workflow_events = HealthEvents(root, max_events=2000, workflow=True)
        from machine_steps import MachineSteps
        self.machine_steps = MachineSteps(self.root/'machine-steps.sqlite3', client)
        self.interval = interval
        self.closed = threading.Event()
        self.thread = None
        self.scheduler_lock = threading.Lock()
        self.scheduler_started = False
        self.last_tick_at = None
        self.last_success_at = None
        self._last_tick_monotonic = None
        self.scheduler_error = None
        self.postprocessing_error = None
        self.last_error = None
        self.last_stop = None
        self.stop_unknown_run_id = None

    def _save(self, state):
        prior = {}
        if self.stop_unknown_run_id and state.get('local_run_id')==self.stop_unknown_run_id:
            state['phase']='local_stop_unknown'
        if self.path.exists():
            prior=mc_runner.read(self.path)
            if 'session_bindings' not in state:state['session_bindings']=prior.get('session_bindings',{})
            if 'waiting_logins' not in state:state['waiting_logins']=prior.get('waiting_logins',[])
            if 'postprocessing_runs' not in state:state['postprocessing_runs']=prior.get('postprocessing_runs',[])
            if 'material_recompute_requests'not in state and 'material_recompute_requests'in prior:state['material_recompute_requests']=prior['material_recompute_requests']
            if 'postprocessing_contexts' not in state:state['postprocessing_contexts']=prior.get('postprocessing_contexts',{})
            if 'participant_pro_cursor' not in state and 'participant_pro_cursor' in prior:state['participant_pro_cursor']=prior['participant_pro_cursor']
            if 'pending_deliveries' not in state:state['pending_deliveries']=prior.get('pending_deliveries',[])
            if 'last_stop' not in state and 'last_stop' in prior:state['last_stop']=prior['last_stop']
        if self.last_stop is not None:state['last_stop']=self.last_stop
        bindings = state.setdefault('session_bindings', {})
        for context in [state, *state.get('waiting_logins', [])]:
            lease = context.get('lease') or {}
            session_id = context.get('session_id') or context.get('account_context', {}).get('session_id')
            if lease.get('child_id') and session_id:
                binding = {'task_id': mc_runner.uid(lease['task_id']), 'platform': lease['platform'],
                           'session_id': mc_runner.uid(session_id)}
                existing = bindings.get(lease['child_id'])
                if existing and existing != binding:
                    raise CloudError('collector_session_ambiguous')
                bindings[lease['child_id']] = binding
        mc_runner.write(self.path, state)
        # Journal actual durable phase changes, including transitions too short
        # for the five-second health observer. Never store the request or session.
        if state.get('phase') == 'authorized' and prior.get('phase') == 'claiming':
            self._observe_workflow(state, 'claiming')
        self._observe_workflow(state)

    def _observe_workflow(self, state, phase=None):
        lease = state.get('lease') or {}
        count = sum(v.get('desired_state', 'running') == 'running'
                    for v in state.get('waiting_logins', []))
        effective = phase or ('waiting_login' if state.get('phase') == 'idle' and count else state.get('phase'))
        if effective == 'claiming' and not lease:
            return  # Empty queue polling must not evict actual run history.
        try:self.machine_steps.observe(state, effective)
        except (ValueError,OSError,sqlite3.Error):self.machine_steps.error='machine_steps_store_failed'
        self.workflow_events.observe({'phase': effective, 'task_id': lease.get('task_id'),
            'run_id': lease.get('run_id'), 'local_run_id': state.get('local_run_id'),
            'platform': lease.get('platform'), 'waiting_login_count': count})

    def _runner(self, action, payload):
        try:
            value = self.runner(action, payload)
        except Exception:
            raise CloudError('runner_outcome_unknown') from None
        if not isinstance(value, dict) or value.get('ok') is False:
            raise CloudError('runner_outcome_unknown')
        result = value.get('result', value)
        if not isinstance(result, dict):
            raise CloudError('invalid_runner_result')
        return result

    def _heartbeat(self, state):
        lease = state['lease']
        state['sequence'] = state.get('sequence', 0) + 1
        self._save(state)
        payload = {'run_id': lease['run_id'], 'lease_epoch': lease['lease_epoch'], 'sequence': state['sequence']}
        if state.get('local_run_id'):
            payload['local_run_id'] = state['local_run_id']
        response = self.client.call('heartbeat', payload)
        updated = response.get('lease')
        if not isinstance(updated, dict) or any(updated.get(k) != lease[k] for k in ('run_id','task_id','child_id','lease_epoch','worker_id')):
            raise CloudError('invalid_cloud_lease')
        state['lease'] = updated
        self._save(state)
        return updated

    def _renew_delivery(self, state):
        try:
            if state.get('delivery_manifest'):
                payload=state['delivery_manifest']
                response=self.client.call('delivery_resume', {k:payload[k] for k in ('run_id','lease_epoch','manifest_hash')})
                self._delivery_echo(response,state)
                state['lease']=response['lease'];self._save(state)
                if response.get('may_deliver') is not True and not (state.get('phase')=='finishing'
                        and response['lease'].get('state') in ('completed','failed','stopped','waiting')
                        and self.outbox.stats(state['lease']['run_id'])['pending']==0):
                    raise DeliveryLeaseError('cloud_delivery_lease_denied')
                return state['lease']
            lease = self._heartbeat(state)
        except (CloudError, ValueError, OSError, sqlite3.Error):
            raise DeliveryLeaseError('cloud_delivery_lease_unavailable') from None
        if lease.get('may_dispatch') is not True:
            # The server permits this immutable outbox for 24 hours after expiry.
            # Source execution is already terminal here; this never enables start.
            if (state.get('phase') not in ('importing','delivering','finishing')
                    or state.get('outcome') not in ('completed','stopped','failed','unknown','login_required')):
                raise DeliveryLeaseError('cloud_delivery_lease_denied')
            state['delivery_only'] = True
            self._save(state)
        return lease

    @contextmanager
    def _delivery_keepalive(self, state):
        """Only local terminal import/staging is allowed while one lease renews."""
        self._renew_delivery(state)
        done = threading.Event()
        errors = []
        def renew():
            while not done.wait(DELIVERY_RENEW_SECONDS):
                try:
                    self._renew_delivery(state)
                except DeliveryLeaseError as error:
                    errors.append(error)
                    break
        thread = threading.Thread(target=renew, daemon=True, name='cloud-delivery-lease')
        thread.start()
        try:
            yield
        finally:
            done.set()
            thread.join()
        if errors:
            raise errors[0]
        self._renew_delivery(state)

    def _stop_local(self, state, reason, error_code=None):
        context={'origin':'cloud_worker','reason':reason,'lease_epoch':state['lease']['lease_epoch'],
                 'heartbeat_sequence':state.get('sequence',0)}
        desired=state['lease'].get('desired_state')
        if desired in ('running','paused','stopped'):context['desired_state']=desired
        if error_code is not None:
            context['error_code']=error_code if error_code in mc_runner.STOP_ERRORS else 'cloud_worker_failed'
        context=mc_runner.stop_metadata(context)
        request_context=context
        state.setdefault('stop_context',{**context,'requested_at':time.time()})
        context=state['stop_context']
        state['last_stop']={**context,'local_run_id':state['local_run_id'],'cloud_run_id':state['lease']['run_id'],
                            'task_id':state['lease']['task_id'],'delivery':'request_pending'}
        def persist():
            self.last_stop=dict(state['last_stop'])
            try:self._save(state)
            except (OSError,ValueError,sqlite3.Error):
                state['last_stop']['persistence']='write_failed';self.last_stop=dict(state['last_stop'])
                self.last_error='cloud_stop_persistence_failed'
        persist()
        try:payload=mc_runner.stop_metadata(context)
        except mc_runner.BridgeError:payload=request_context
        try:result=self._runner('stop',{'run_id':state['local_run_id'],**payload})
        except CloudError:
            self.stop_unknown_run_id=state['local_run_id']
            state['phase']='local_stop_unknown'
            state['last_stop']['delivery']='request_unknown';persist();raise
        state['last_stop']['delivery']='requested' if result.get('stop_requested') else 'already_terminal'
        actual=result.get('stop_context')
        if isinstance(actual,dict):
            state['stop_context']=mc_runner.safe_stop_context(actual)
            previous=state['last_stop']
            state['last_stop']={**state['stop_context'],**{key:previous[key] for key in ('local_run_id','cloud_run_id','task_id','delivery','persistence') if key in previous}}
        persist()
        return result

    def tick(self):
        self.last_tick_at = time.time()
        self._last_tick_monotonic = time.monotonic()
        try:
            result = self._locked_tick()
        except OSError:
            # Never recreate a missing lock while another controller may own its inode.
            self.scheduler_error = self.last_error = 'cloud_lock_unavailable'
            return {'state': 'controller_unavailable', 'error': self.last_error}
        except Exception:
            self.scheduler_error = self.last_error = 'cloud_scheduler_failed'
            return {'state': 'controller_unavailable', 'error': self.last_error}
        self.scheduler_error = None
        if not result.get('error') and not result.get('errors') and not self.postprocessing_error and result.get('state') != 'controller_busy':
            self.last_success_at = time.time()
        return result

    def enqueue_material_recompute(self,request_id,context_factory,fingerprint):
        """Same existing state/lock/save transaction; no second scheduler or source call."""
        if type(request_id)is not str or str(uuid.UUID(request_id))!=request_id:raise CloudError('invalid_request')
        with open(self.lock_path,'r+')as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise CloudError('controller_busy')from None
            latest=mc_runner.read(self.path)if self.path.exists()else {'phase':'idle'}
            requests=latest.setdefault('material_recompute_requests',{})
            if request_id in requests:
                if requests[request_id].get('fingerprint')!=fingerprint:raise CloudError('material_recompute_request_conflict')
                return dict(requests[request_id])
            if len(requests)>=2000:raise CloudError('material_recompute_request_limit')
            from automatic_materials import material_context_key,validate_context
            context=validate_context(context_factory());key=material_context_key(context)
            for old in latest.get('postprocessing_contexts',{}).values():
                if old.get('schema')=='crowd-material-recompute-v1'and old['pro_key']==context['pro_key']:raise CloudError('material_recompute_pending')
            prior=latest.setdefault('postprocessing_contexts',{}).get(key)
            if prior is not None and prior!=context:raise CloudError('material_recompute_changed')
            latest['postprocessing_contexts'][key]=context
            latest['postprocessing_runs']=list(dict.fromkeys([*latest.get('postprocessing_runs',[]),key]))
            result={'state':'queued','request_id':request_id,'key':key,'pro_key':context['pro_key'],'target_release':context['target_release'],'fingerprint':fingerprint}
            requests[request_id]=result
            self._save(latest)
            return dict(result)

    def _locked_tick(self):
        if self.lock_path.is_symlink():
            raise OSError('unsafe_worker_lock')
        with open(self.lock_path, 'r+') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return {'state': 'controller_busy'}
            state = {'phase': 'state_unreadable'}
            try:
                state = mc_runner.read(self.path) if self.path.exists() else {'phase': 'idle'}
                if self.stop_unknown_run_id and state.get('local_run_id')==self.stop_unknown_run_id:
                    state['phase']='local_stop_unknown'
                result = self._tick(state)
                self.postprocessing_error = None
                if self.postprocessing_callback:
                    latest = mc_runner.read(self.path)
                    if latest.get('phase') == 'idle' and not latest.get('lease'):
                        try:latest = self._participant_postprocessing(latest)
                        except Exception:self.postprocessing_error = 'participant_pro_feed_failed'
                    for run_id in list(latest.get('postprocessing_runs', [])):
                        try:
                            enqueued = self.postprocessing_callback('enqueue', {'run_id': run_id, **({'material_context': latest['postprocessing_contexts'][run_id]} if run_id in latest.get('postprocessing_contexts', {}) else {})})
                            if isinstance(enqueued, dict) and enqueued.get('material_pending') is True:
                                continue  # Normal background work retains the original pending item.
                        except Exception:
                            self.postprocessing_error = 'postprocessing_enqueue_failed'
                            continue  # Retain this pending job without stopping a separate source lease.
                        latest['postprocessing_runs'].remove(run_id)
                        latest.get('postprocessing_contexts', {}).pop(run_id, None)
                        self._save(latest)
                    try:self.postprocessing_callback('tick', {})
                    except Exception:
                        self.postprocessing_error = self.postprocessing_error or 'postprocessing_tick_failed'
                self.last_error = result.get('error')
                result['waiting_login_count'] = sum(v.get('desired_state','running') == 'running' for v in mc_runner.read(self.path).get('waiting_logins', []))
                return result
            except Exception as error:
                code = str(error) if str(error) in WORKER_ERRORS else 'cloud_worker_failed'
                self.last_error = code
                try:
                    state = mc_runner.read(self.path) if self.path.exists() else state
                except (ValueError, OSError):
                    pass
                if self.stop_unknown_run_id and state.get('local_run_id')==self.stop_unknown_run_id:
                    state['phase']='local_stop_unknown'
                # A proven local saved-only refusal owns no source attempt or staged row.
                # Persist the original run's finish before any retry; unknown writes stay unchanged.
                from existing_saved_rejection import rejected_before_dispatch
                lease = state.get('lease')
                if lease and state.get('phase') == 'authorized':
                    try:
                        if rejected_before_dispatch(state, code, self.outbox.stats(lease['run_id'])):
                            terminal = {**state, 'phase':'finishing', 'outcome':'failed',
                                        'api_attempts':0, 'validation_error':code}
                            self._save(terminal)
                            state = terminal
                    except (ValueError, OSError, sqlite3.Error):
                        self.last_error = 'cloud_rejection_persistence_failed'
                # Fail closed if authorization cannot be renewed. Never start another run.
                if lease and state.get('local_run_id') and state.get('phase') == 'running':
                    try:
                        self._stop_local(state, 'cloud_controller_error', code)
                    except CloudError:
                        state['phase'] = 'local_stop_unknown'
                        try:self._save(state)
                        except (OSError,ValueError,sqlite3.Error):self.last_error='cloud_stop_persistence_failed'
                return {'state': state.get('phase'), 'error': code}

    def _participant_postprocessing(self, state):
        """Read Owner-scoped ACKs; atomically join the existing durable retry queue."""
        import copy
        from automatic_materials import validate_context, material_context_key
        page = self.postprocessing_callback('participant_receipts', {'after': state.get('participant_pro_cursor')})
        if page is None:return state
        if type(page) is not dict or set(page) != {'contexts','next_cursor','rescan'} or type(page['contexts']) is not list or len(page['contexts']) > 8 or type(page['rescan']) is not bool:
            raise ValueError('participant_pro_feed_invalid')
        latest = copy.deepcopy(state)
        for context in page['contexts']:
            validate_context(context)
            if context['schema'] != 'crowd-participant-pro-material-context-v1':raise ValueError('participant_pro_feed_invalid')
            key = material_context_key(context)
            prior = latest.setdefault('postprocessing_contexts', {}).get(key)
            if prior is not None and prior != context:raise ValueError('participant_pro_context_changed')
            latest['postprocessing_contexts'][key] = context
            latest['postprocessing_runs'] = list(dict.fromkeys([*latest.get('postprocessing_runs', []), key]))
        # Never advance a cursor without a durable context for every returned group.
        if page['rescan']:
            if page['contexts'] or page['next_cursor'] is not None or state.get('participant_pro_cursor') is None:raise ValueError('participant_pro_feed_invalid')
            latest['participant_pro_cursor']=None
            self._save(latest)
        elif page['contexts']:
            from participant_material_feed import validate_cursor
            validate_cursor(page['next_cursor'])
            if page['next_cursor'] != page['contexts'][-1]['group_cursor']:raise ValueError('participant_pro_feed_invalid')
            latest['participant_pro_cursor'] = page['next_cursor']
            self._save(latest)
        elif page['next_cursor'] != state.get('participant_pro_cursor'):
            raise ValueError('participant_pro_feed_invalid')
        return latest

    def status(self):
        """Safe UI summary. Private lease targets/account bindings never leave this module."""
        try:
            state = mc_runner.read(self.path) if self.path.exists() else {'phase':'idle'}
            count = sum(v.get('desired_state','running') == 'running' for v in state.get('waiting_logins', []))
            phase = 'waiting_login' if state.get('phase') == 'idle' and count else state.get('phase')
            if self.stop_unknown_run_id and state.get('local_run_id')==self.stop_unknown_run_id:phase='local_stop_unknown'
            observation_error='runner_status_unavailable' if state.get('phase')=='running' and state.get('status_read_error')=='runner_status_unavailable' else None
            summary={'phase':phase, 'waiting_login_count':count, 'last_error':self.last_error or observation_error,
                    'local_run_id':state.get('local_run_id'), 'outbox':self.outbox.stats(),
                    'workflow_monitor_error': self.workflow_events.error, 'central_steps':self.machine_steps.status()}
            last=self._stop_summary(self.last_stop or state.get('last_stop'))
            if last:summary['last_stop']=last
            return {**summary, **self.scheduler_status()}
        except (ValueError, OSError, sqlite3.Error):
            summary={'phase':'local_stop_unknown' if self.stop_unknown_run_id else 'state_unreadable','last_error':self.last_error or 'cloud_worker_failed'}
            last=self._stop_summary(self.last_stop)
            if last:summary['last_stop']=last
            return {**summary, **self.scheduler_status()}

    @staticmethod
    def _delivery_echo(response, state):
        lease, manifest = state['lease'], state['delivery_manifest']
        if (not isinstance(response, dict) or type(response.get('lease_epoch')) is not int
                or any(response.get(k) != lease[k] for k in ('run_id','lease_epoch','worker_id'))
                or response.get('manifest_hash') != manifest['manifest_hash']
                or not isinstance(response.get('lease'), dict)
                or type(response['lease'].get('lease_epoch')) is not int
                or any(response['lease'].get(k) != lease[k] for k in ('run_id','task_id','child_id','worker_id','lease_epoch'))
                or response['lease'].get('may_dispatch') is not False):
            raise CloudError('invalid_cloud_delivery')

    def _park_delivery(self, state):
        if not state.get('delivery_manifest'):
            # Commit the exact manifest before the potentially unknown remote write.
            payload = {'run_id':state['lease']['run_id'], 'lease_epoch':state['lease']['lease_epoch'],
                'defer_id':str(uuid.uuid4()), 'local_run_id':state.get('local_run_id'),
                'outcome':state['outcome'], 'api_attempts':state.get('api_attempts',0),
                'capture_refs':self.outbox.manifest(state['lease'])}
            payload['manifest_hash'] = _hash('crowd-machine-delivery-v1',payload)
            state.update(phase='deferring_delivery', delivery_manifest=payload)
            self._save(state)
        if state['phase']=='deferring_delivery':
            response=self.client.call('delivery_defer',state['delivery_manifest'])
            self._delivery_echo(response,state)
            if response.get('deferred') is not True:
                raise CloudError('invalid_cloud_delivery')
            state['lease']=response['lease']
        pending=[p for p in state.get('pending_deliveries',[]) if p['lease']['run_id']!=state['lease']['run_id']]
        context={k:v for k,v in state.items() if k not in ('pending_deliveries','waiting_logins','session_bindings','postprocessing_runs')}
        context.update(phase='delivering', retry_requested=False, desired_state=state['lease'].get('desired_state','running'))
        if state.get('delivery_check_failed'):context['delivery_check_at']=time.time()+30
        else:context.pop('delivery_check_at',None)
        context.pop('delivery_check_failed',None)
        pending.append(context)
        self._save({'phase':'idle','pending_deliveries':pending})
        return {'state':'delivery_pending', **self.outbox.stats(state['lease']['run_id'])}

    def delivery_status(self):
        state=mc_runner.read(self.path) if self.path.exists() else {'phase':'idle'}
        contexts=list(state.get('pending_deliveries',[]))
        if state.get('lease') and state.get('phase') in ('delivering','deferring_delivery','finishing'):
            contexts.append(state)
        groups=[]
        for context in contexts:
            lease=context['lease'];stats=self.outbox.stats(lease['run_id'])
            known=context.get('outcome') in ('completed','stopped','failed')
            groups.append({'run_id':lease['run_id'],'task_id':lease['task_id'],'platform':lease['platform'],
                **{k:stats[k] for k in ('pending','acknowledged','quarantined','deferred','next_retry_at','errors','quarantined_capture_ids')},
                'retry_allowed':known and context.get('desired_state','running')=='running' and stats['quarantined']>0,
                'reason':'task_'+context['desired_state'] if context.get('desired_state') in ('paused','stopped') else 'quarantined_delivery' if known and stats['quarantined'] else 'source_outcome_unknown' if not known else 'delivery_pending'})
        return {'schema':'crowd-delivery-status-v1','groups':groups}

    def recover_cloud_login(self, task_id, child_id, owner_client, open_login):
        """Bind only an existing terminal login wait; never queue or restart source."""
        if getattr(owner_client,'role',None) != 'owner':raise CloudError('principal_denied')
        task_id,child_id=mc_runner.uid(task_id),mc_runner.uid(child_id)
        if self.lock_path.is_symlink():raise CloudError('unsafe_cloud_file')
        with open(self.lock_path,'r+') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise CloudError('cloud_controller_busy') from None
            state=mc_runner.read(self.path)
            if not isinstance(state,dict) or not isinstance(state.get('waiting_logins'),list):
                raise CloudError('cloud_login_context_invalid')
            waits=state['waiting_logins']
            if any(not isinstance(v,dict) or not isinstance(v.get('lease'),dict)
                   or not isinstance(v.get('account_context'),dict)
                   or not isinstance(v['lease'].get('request'),dict) for v in waits):
                raise CloudError('cloud_login_context_invalid')
            contexts=[v for v in state.get('waiting_logins',[]) if isinstance(v,dict)
                      and v.get('lease',{}).get('task_id')==task_id
                      and v.get('lease',{}).get('child_id')==child_id]
            if len(contexts)!=1:raise CloudError('cloud_login_context_missing')
            wait=contexts[0];lease=wait.get('lease',{});account=wait.get('account_context',{})
            local=mc_runner.uid(wait.get('local_run_id'))
            session=mc_runner.uid(wait.get('session_id'))
            if (wait.get('outcome')!='login_required' or wait.get('recovery_authorized_run') not in (None,local)
                    or account.get('session_id')!=session or lease.get('local_run_id')!=local
                    or lease.get('request',{}).get('session_id')!=session
                    or type(lease.get('lease_epoch')) is not int or lease['lease_epoch']<1
                    or type(account.get('generation')) is not int or account['generation']<1
                    or not isinstance(account.get('account_ref'),str)
                    or not re.fullmatch(r'[0-9a-f]{64}',account['account_ref'])):
                raise CloudError('cloud_login_context_invalid')
            response=owner_client.call('task_status',{'task_id':task_id})
            if not isinstance(response,dict) or not isinstance(response.get('task'),dict):
                raise CloudError('cloud_login_context_changed')
            task=response['task']
            if not isinstance(task.get('children'),list) or any(not isinstance(v,dict) for v in task['children']):
                raise CloudError('cloud_login_context_changed')
            children=[v for v in task.get('children',[]) if v.get('child_id')==child_id]
            if len(children)!=1:raise CloudError('cloud_login_context_changed')
            child=children[0]
            attempts=child.get('attempts')
            if (not isinstance(attempts,list) or not attempts or any(not isinstance(v,dict)
                    or type(v.get('lease_epoch')) is not int or v['lease_epoch']<1 for v in attempts)):
                raise CloudError('cloud_login_context_changed')
            newest=max(v['lease_epoch'] for v in attempts)
            latest=[v for v in attempts if v['lease_epoch']==newest]
            if len(latest)!=1:raise CloudError('cloud_login_context_changed')
            attempt=latest[0]
            if (task.get('task_id')!=task_id or task.get('desired_state') not in ('paused','running')
                    or child.get('state')!='waiting' or child.get('reason_code')!='login_required'
                    or child.get('local_run_id')!=local or child.get('worker_id')!=lease.get('worker_id')
                    or child.get('platform')!=lease.get('platform')
                    or type(child.get('lease_epoch')) is not int or child['lease_epoch']!=lease.get('lease_epoch')
                    or not isinstance(child.get('runs'),list) or lease.get('run_id') not in child['runs']
                    or any(attempt.get(k)!=v for k,v in
                           {'run_id':lease.get('run_id'),'lease_epoch':lease.get('lease_epoch'),
                            'local_run_id':local,'worker_id':lease.get('worker_id'),'outcome':'login_required'}.items())
                    or child.get('active_run_id') is not None
                    or type(child.get('requests_reserved')) is not int or child['requests_reserved']!=0
                    or type(child.get('requests_spent')) is not int or child['requests_spent']<0
                    or type(child.get('request_quota')) is not int or child['request_quota']<=child['requests_spent']):
                raise CloudError('cloud_login_context_changed')
            original=self._runner('status',{'run_id':local})
            if (not isinstance(original,dict) or original.get('run_id')!=local or original.get('state')!='login_required'
                    or type(original.get('exit_code')) is not int or original['exit_code']!=77
                    or original.get('platform')!=lease['platform'] or original.get('session_id')!=session
                    or original.get('account_generation') is not None and
                       (type(original['account_generation']) is not int or original['account_generation']!=account['generation'])):
                raise CloudError('cloud_login_source_not_terminal')
            current=self._runner('account_status',{'session_id':session,'platform':lease['platform']})
            if (not isinstance(current,dict) or type(current.get('generation')) is not int or current.get('generation')!=account['generation'] or current.get('account_ref')!=account['account_ref']
                    or current.get('login_in_progress') is True):
                raise CloudError('cloud_login_account_changed')
            result=open_login(session,lease['platform'],{'run_id':local,
                'generation':account['generation'],'account_ref':account['account_ref']},
                lease['request'].get('source_executor','mc'))
            return {**result,'recovery_task_id':task_id,'recovery_local_run_id':local,
                    'source_collection_started':False,'owner_continue_required':task['desired_state']=='paused'}

    def retry_delivery(self, capture_ids, owner_client):
        if getattr(owner_client,'role',None)!='owner':
            raise CloudError('principal_denied')
        if not isinstance(capture_ids,list) or not 1<=len(capture_ids)<=2000 or len(set(str(v) for v in capture_ids))!=len(capture_ids):
            raise CloudError('invalid_capture_retry')
        try: ids=[mc_runner.uid(v) for v in capture_ids]
        except (ValueError,mc_runner.BridgeError,TypeError):raise CloudError('invalid_capture_retry') from None
        if self.lock_path.is_symlink():raise CloudError('unsafe_cloud_file')
        with open(self.lock_path,'r+') as lock:
            try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError: raise CloudError('cloud_controller_busy') from None
            state=mc_runner.read(self.path)
            with self.outbox._db() as db:
                rows=[db.execute('SELECT run_id,state FROM captures WHERE id=?',(v,)).fetchone() for v in ids]
            if any(r is None for r in rows):raise CloudError('invalid_capture_retry')
            runs={r[0] for r in rows}
            if len(runs)!=1:raise CloudError('delivery_retry_run_mismatch')
            run_id=next(iter(runs));contexts=[state,*state.get('pending_deliveries',[])]
            context=next((v for v in contexts if v.get('lease',{}).get('run_id')==run_id),None)
            if context is None or context.get('outcome') not in ('completed','failed','stopped'):
                raise CloudError('delivery_retry_denied')
            lease=context['lease']
            response=owner_client.call('task_status',{'task_id':lease['task_id']})
            task=response.get('task',{})
            if task.get('task_id')==lease['task_id'] and task.get('desired_state') in ('paused','stopped'):
                context['desired_state']=task['desired_state'];self._save(state)
                raise CloudError('task_'+task['desired_state'])
            child=next((v for v in task.get('children',[]) if v.get('child_id')==lease['child_id']),{})
            if (task.get('task_id')!=lease['task_id'] or task.get('desired_state')!='running'
                    or child.get('state') not in ('running','delivery_pending')
                    or child.get('worker_id')!=lease['worker_id'] or type(child.get('lease_epoch')) is not int or child.get('lease_epoch')!=lease['lease_epoch']
                    or run_id not in child.get('runs',[])):
                raise CloudError('delivery_retry_denied')
            stats=self.outbox.stats(run_id)
            to_retry=[v for v in ids if v in stats['quarantined_capture_ids']]
            if any(r[1]!='acknowledged' and v not in to_retry for v,r in zip(ids,rows)):
                raise CloudError('capture_not_quarantined')
            if to_retry:self.outbox.retry_quarantined(to_retry)
            context['retry_requested']=True
            context['desired_state']='running'
            self._save(state)
            return {'schema':'crowd-delivery-retry-v1','accepted':True,'requeued_capture_ids':to_retry,'state':'queued'}

    def scheduler_status(self):
        alive = bool(self.thread and self.thread.is_alive())
        threshold = max(30, self.interval * 3)
        stale = bool(self.scheduler_started and not self.closed.is_set() and (
            not alive or self._last_tick_monotonic is None or
            time.monotonic() - self._last_tick_monotonic > threshold))
        error = self.scheduler_error
        if self.scheduler_started and not self.closed.is_set():
            error = error or ('scheduler_dead' if not alive else 'scheduler_stale' if stale else None)
        return {'scheduler_started': self.scheduler_started, 'scheduler_alive': alive,
                'scheduler_closed': self.closed.is_set(), 'last_tick_at': self.last_tick_at,
                'last_success_at': self.last_success_at, 'stale': stale,
                'stale_after_seconds': threshold, 'health_error': error,
                'postprocessing_error': self.postprocessing_error}

    @staticmethod
    def _stop_summary(last):
        if not isinstance(last,dict):return None
        try:
            value={**mc_runner.safe_stop_context(last),
                   **{k:mc_runner.uid(last.get(k)) for k in ('local_run_id','cloud_run_id','task_id')},
                   'delivery':last['delivery'] if last.get('delivery') in ('request_pending','request_unknown','requested','already_terminal') else 'request_unknown'}
            if last.get('persistence')=='write_failed':value['persistence']='write_failed'
            return value
        except mc_runner.BridgeError:return None

    def _tick(self, state):
        # A login wait owns no running executor; other platforms may continue.
        waiting = state.get('waiting_logins', [])
        # Persist old journal bindings before a successful resume removes its wait.
        self._save(state)
        for pending in list(waiting):
            try:
                if self._resume_login(pending):
                    waiting.remove(pending)
            except CloudError:
                continue
        state['waiting_logins'] = waiting
        self._save(state)
        if state['phase'] == 'idle':
            pending=state.get('pending_deliveries',[])
            for context in list(pending):
                stats=self.outbox.stats(context['lease']['run_id'])
                if context.get('retry_requested') or time.time()>=context.get('delivery_check_at',0) and ((stats['retryable']>0 or stats['pending']==0) or context.get('desired_state') in ('paused','stopped')):
                    pending.remove(context)
                    state={**context,'phase':'delivering','pending_deliveries':pending,'waiting_logins':waiting}
                    self._save(state)
                    break
        if state['phase'] == 'idle':
            state = {'phase': 'claiming', 'claim_id': str(uuid.uuid4()), 'waiting_logins': waiting,
                     'unavailable_platforms': sorted({v['lease']['platform'] for v in waiting if v.get('desired_state','running') == 'running'})}
            self._save(state)
        if state['phase'] == 'claiming':
            response = self.client.call('claim', {'claim_id': state['claim_id'],
                                                'unavailable_platforms': state.get('unavailable_platforms', []),
                                                'source_capabilities': self.capability_provider() if self.capability_provider else []})
            lease = response.get('lease')
            if lease is None:
                self._save({'phase': 'idle', 'waiting_logins': waiting})
                return {'state': 'waiting_login' if waiting else 'idle', 'waiting_login_count': len(waiting)}
            if not isinstance(lease, dict) or not all(k in lease for k in ('run_id','task_id','child_id','worker_id','lease_epoch','platform','request','delivery_basis')):
                raise CloudError('invalid_cloud_lease')
            if lease['platform'] not in mc_runner.PLATFORMS or type(lease['lease_epoch']) is not int or lease['lease_epoch'] < 1 or lease['delivery_basis'] not in ('live_capture','existing_saved'):
                raise CloudError('invalid_cloud_lease')
            for key in ('run_id','task_id','child_id','worker_id'):
                mc_runner.uid(lease[key])
            state.update(phase='authorized', lease=lease, sequence=0)
            self._save(state)
        if state['phase'] in ('dispatching','local_stop_unknown'):
            # A crash between source start and persistence cannot be resolved by another start.
            return {'state': state['phase'], 'error': 'source_outcome_unknown'}
        if state['phase'] == 'reconciling_no_dispatch':
            return self._reconcile_no_dispatch(state, waiting)
        if state['phase']=='deferring_delivery':
            return self._park_delivery(state)
        lease = state['lease']
        if state['phase'] == 'waiting_login':
            # Upgrade the previous single-wait durable state without discarding context.
            if self._resume_login(state):
                self._save({'phase': 'idle', 'last_resumed_run_id': lease['run_id'], 'waiting_logins': waiting})
                return {'state': 'resumed'}
            pending = {k:v for k,v in state.items() if k != 'waiting_logins'}
            self._save({'phase':'idle', 'waiting_logins': [*waiting, pending]})
            return {'state': 'waiting_login'}
        if state['phase'] == 'authorized':
            pre_dispatch = {'phase': 'authorized', 'local_run_id': state.get('local_run_id'),
                            'sequence': state.get('sequence', 0)}
            lease = self._heartbeat(state)
            if lease.get('may_dispatch') is not True:
                if (lease.get('state') == 'unknown' and pre_dispatch['local_run_id'] is None
                        and type(pre_dispatch['sequence']) is int and pre_dispatch['sequence'] >= 1):
                    proof = {**pre_dispatch, 'evidence_sha256': _hash('crowd-machine-pre-dispatch-v1',
                        {**pre_dispatch, 'claim_id': state['claim_id'], 'run_id': lease['run_id'],
                         'lease_epoch': lease['lease_epoch']})}
                    payload = {
                        'claim_id': state['claim_id'], 'run_id': lease['run_id'],
                        'lease_epoch': lease['lease_epoch'], 'proof': proof}
                    state.update(phase='reconciling_no_dispatch', reconciliation_payload=payload)
                    self._save(state)
                    return self._reconcile_no_dispatch(state, waiting)
                state.update(phase='finishing', outcome='unknown', api_attempts=0)
                self._save(state)
            elif lease['delivery_basis'] == 'existing_saved':
                if not isinstance(lease.get('record_refs'), list) or len(lease['record_refs']) > 200:
                    raise CloudError('existing_saved_selection_mismatch')
                if any('results_revision' in ref and (type(ref['results_revision']) is not int or ref['results_revision'] <= 0 or not ref.get('version_hash')) for ref in lease['record_refs']):
                    raise CloudError('existing_saved_selection_mismatch')
                if self.existing_reader is None:
                    raise CloudError('existing_saved_reader_missing')
                with self._delivery_keepalive(state):
                    records = self.existing_reader(lease)
                    if isinstance(records, dict):
                        records = records.get('records')
                    refs = lease.get('record_refs', [])
                    if not isinstance(records, list) or any(not any((r.get('record', r).get('content_id') == ref['content_id'] and r.get('record', r).get('kind') == ref.get('kind','content')) for ref in refs) for r in records):
                        raise CloudError('existing_saved_selection_mismatch')
                    from existing_saved import validate_record_bindings
                    validate_record_bindings(records, refs)
                    self.outbox.stage_imported(records, state['lease'])
                state.update(phase='delivering', outcome='completed', api_attempts=0)
                self._save(state)
            else:
                request = dict(lease['request'])
                binding = state.get('session_bindings', {}).get(lease['child_id'])
                if binding:
                    if (binding.get('task_id') != lease['task_id'] or binding.get('platform') != lease['platform']
                            or request.get('session_id') not in (None, binding.get('session_id'))):
                        raise CloudError('collector_session_ambiguous')
                    request['session_id'] = mc_runner.uid(binding['session_id'])
                if not request.get('session_id') and self.session_selector:
                    session = self.session_selector(lease)
                    if session:
                        request['session_id'] = mc_runner.uid(session)
                try:
                    request = mc_runner.validate(request)
                except mc_runner.BridgeError:
                    # Validation ran before dispatch: there is no unknown source call.
                    # Persist finish first so a lost ACK retries the same finish only.
                    state.update(phase='finishing', outcome='failed', api_attempts=0,
                                 validation_error='invalid_local_task')
                    self._save(state)
                else:
                    state['session_id'] = request['session_id']
                    if lease.get('supplemental_context') and not self._supplemental_account(state, request):
                        state.update(phase='finishing', outcome='login_required', api_attempts=0)
                        self._save(state)
                    else:
                        state['phase'] = 'dispatching'
                        self._save(state)  # Commit authorization before the first source call.
                        if lease.get('source_continuation') is not None:
                            result = self._runner('start_continuation', {'request': request, 'lease': lease})
                            state['account_context'] = lease['source_continuation']['account_context']
                        else:
                            result = self._runner('start', request)
                        run_id = result.get('run_id') or result.get('run', {}).get('run_id')
                        mc_runner.uid(run_id)
                        state.pop('recovery_authorized_run', None)
                        state.update(phase='running', local_run_id=run_id)
                        self._save(state)
        if state['phase'] == 'running':
            lease = self._heartbeat(state)
            if lease.get('may_dispatch') is not True:
                self._stop_local(state, 'owner_stop_requested' if lease.get('desired_state')=='stopped' else 'cloud_dispatch_denied')
            try:
                current = self._runner('status', {'run_id': state['local_run_id']})
                stage = current.get('state') or current.get('stage') or current.get('status')
                if not isinstance(stage,str) or stage not in mc_runner.FINAL | {'starting','running','waiting_login','collecting','comments','media'}:
                    raise CloudError('invalid_runner_result')
            except CloudError:
                if lease.get('may_dispatch') is not True:
                    raise
                # A successful renewal authorizes this exact run. A failed read is not revocation.
                state['status_read_error']='runner_status_unavailable'
                self._save(state)
                return {'state':'running','error':'runner_status_unavailable'}
            for source_step in current.get('source_steps',[]):
                try:self.machine_steps.observe(state,'source_step',**source_step)
                except (ValueError,OSError,sqlite3.Error):self.machine_steps.error='machine_steps_store_failed'
            for page in current.get('step_pages',[]):
                try:self.machine_steps.observe(state,'comments_page',**page)
                except (ValueError,OSError,sqlite3.Error):self.machine_steps.error='machine_steps_store_failed'
            counts = current.get('step_counts', {})
            try:self.machine_steps.observe(state, **{key:counts[key] for key in ('saved_pages','saved_rows') if key in counts})
            except (ValueError,OSError,sqlite3.Error):self.machine_steps.error='machine_steps_store_failed'
            state.pop('status_read_error',None)
            self._save(state)
            if stage not in mc_runner.FINAL:
                return {'state': 'running', 'local_stage': stage}
            terminal_attempts=current.get('api_requests',current.get('api_attempts',0))
            if current.get('api_attempts_unverified') is True or type(terminal_attempts)is not int or terminal_attempts<0 or terminal_attempts>lease['request'].get('max_api_requests',500):
                # Keep the original lease and reservation. Re-read only; never start,
                # import or finish with a guessed zero/old parent sink count.
                state['status_read_error']='runner_budget_unavailable'
                self._save(state)
                return {'state':'running','error':'runner_budget_unavailable'}
            from run_diagnostics import from_status as run_diagnostic_from_status
            diagnostic=run_diagnostic_from_status(current)
            if diagnostic is not None:state['run_diagnostic']=diagnostic
            else:state.pop('run_diagnostic',None)
            state.update(phase='importing', outcome='unknown' if stage == 'interrupted' else stage,
                         api_attempts=current.get('api_requests', current.get('api_attempts', 0)))
            if state['outcome'] not in ('completed','stopped','failed','login_required'):
                state['outcome'] = 'unknown'
            if state['outcome'] == 'login_required':
                from login_recovery_freshness import failure_time
                state['login_failed_at']=failure_time(current) or time.time()
                account = self._runner('account_status', {'session_id': state['session_id'], 'platform': lease['platform']})
                state['account_context'] = {'session_id': state['session_id'],
                    'generation': account.get('generation', 0), 'account_ref': account.get('account_ref')}
            self._save(state)
        if state['phase'] == 'importing':
            with self._delivery_keepalive(state):
                records = self._runner('import', {'run_id': state['local_run_id']})
                if state['lease'].get('source_continuation') is not None:
                    if not isinstance(records,dict) or not isinstance(records.get('capture_records'),list) or not isinstance(records.get('source_reuse'),list):raise CloudError('continuation_import_unknown')
                    self.outbox.stage_imported(records['capture_records'], state['lease'])
                else:
                    self.outbox.stage_imported(records, state['lease'])
            state['phase'] = 'delivering'
            self._save(state)
        if state['phase'] == 'delivering':
            # Deferred/isolated rows still own this lease; absence of sends is not release.
            try:self._renew_delivery(state)
            except DeliveryLeaseError:
                if state.get('delivery_manifest'):
                    state['delivery_check_failed']=True
                    return self._park_delivery(state)
                raise
            acknowledged_before = self.outbox.stats(state['lease']['run_id'])['acknowledged']
            status = self.outbox.flush(state['lease']['run_id'], limit=4,
                                       before_send=lambda: self._renew_delivery(state))
            try:self.machine_steps.observe(state, acknowledged=status['acknowledged'], pending=status['pending'])
            except (ValueError,OSError,sqlite3.Error):self.machine_steps.error='machine_steps_store_failed'
            if status['pending']:
                if state.get('outcome') in ('completed','failed','stopped') and (state.get('delivery_manifest') or state['lease'].get('state')=='running') and (status['quarantined'] or status['deferred'] or status['errors']):
                    return self._park_delivery(state)
                return {'state': 'delivering', **status,
                        'delivery_progress': status['acknowledged'] > acknowledged_before}
            state['phase'] = 'finishing'
            self._save(state)
        if state['phase'] == 'finishing':
            self._renew_delivery(state)
            status = self.outbox.stats(state['lease']['run_id'])
            payload = {'run_id': state['lease']['run_id'], 'lease_epoch': state['lease']['lease_epoch'],
                       'capture_ids': status['capture_ids'], 'outcome': state['outcome'],
                       'api_attempts': state.get('api_attempts', 0)}
            if state.get('account_context'):
                payload['account_context'] = state['account_context']
            if status['pending']:
                raise CloudError('unacknowledged_capture')
            payload['finish_hash'] = _hash('crowd-machine-finish-v1', payload)
            response = self.client.call('finish', payload)
            task=response.get('task')
            child=next((v for v in task.get('children',[]) if isinstance(v,dict) and v.get('child_id')==state['lease']['child_id']),{}) if isinstance(task,dict) else {}
            if (not isinstance(task,dict) or task.get('task_id')!=state['lease']['task_id']
                    or type(child.get('lease_epoch')) is not int
                    or child.get('state') not in ('completed','failed','stopped','waiting','unknown')
                    or any(child.get(k)!=state['lease'][k] for k in ('worker_id','lease_epoch'))
                    or child.get('finish_hash')!=payload['finish_hash']
                    or not isinstance(child.get('runs'),list) or state['lease']['run_id'] not in child['runs']):
                raise CloudError('invalid_cloud_ack')
            self._observe_workflow(state, 'waiting_login' if state['outcome'] == 'login_required' else
                                   'completed' if state['outcome'] == 'completed' else 'paused')
            legacy_postprocessing = (state['outcome'] == 'completed' and state.get('local_run_id')
                    and state['lease'].get('request', {}).get('platform_options', {}).get('transcript_only') is True)
            material_postprocessing = (state['outcome'] in ('completed', 'failed', 'stopped') and state.get('local_run_id')
                    and type(state.get('api_attempts')) is int and state['api_attempts'] >= 0
                    and not state.get('api_attempts_unverified')
                    and type(status.get('acknowledged')) is int and status['acknowledged'] > 0
                    and (self.root.parent / 'data-products/material-auto-runtime.json').is_file())
            if self.postprocessing_callback and (legacy_postprocessing or material_postprocessing):
                local = state['local_run_id']
                state['postprocessing_runs'] = list(dict.fromkeys([*state.get('postprocessing_runs', []), local]))
                if material_postprocessing:
                    state.setdefault('postprocessing_contexts', {})[local] = {
                        'schema': 'crowd-material-postprocessing-v1', 'local_run_id': local,
                        'task_id': state['lease']['task_id'], 'child_id': state['lease']['child_id'],
                        'cloud_run_id': state['lease']['run_id'], 'lease_epoch': state['lease']['lease_epoch'],
                        'platform': mc_runner.PLATFORMS[state['lease']['platform']],
                        'outcome': state['outcome'], 'api_attempts': state['api_attempts'],
                        'finish_hash': payload['finish_hash'], 'finish_verified': True}
                self._save(state)
            if state['outcome'] == 'login_required':
                pending = {k:v for k,v in state.items() if k != 'waiting_logins'}
                pending['phase'] = 'waiting_login'
                self._save({'phase': 'idle', 'waiting_logins': [*waiting, pending]})
            else:
                self._save({'phase': 'idle', 'last_finished_run_id': state['lease']['run_id'],
                            'last_validation_error': state.get('validation_error'),
                            'waiting_logins': waiting})
            return {'state': 'finished', 'task': response.get('task')}
        return {'state': state['phase']}

    def _reconcile_no_dispatch(self, state, waiting):
        response = self.client.call('reconcile_no_dispatch', state['reconciliation_payload'])
        payload = state['reconciliation_payload']
        if (response.get('reconciled') is not True
                or type(response.get('lease_epoch')) is not int
                or any(response.get(key) != payload[key] for key in ('claim_id','run_id','lease_epoch'))
                or response.get('worker_id') != state['lease']['worker_id']):
            raise CloudError('invalid_cloud_reconciliation')
        self._save({'phase': 'idle', 'waiting_logins': waiting,
                    'last_reconciled_run_id': state['lease']['run_id']})
        return {'state': 'reconciled_no_dispatch'}

    def _supplemental_account(self, state, request):
        lease = state['lease']
        recovery = lease['supplemental_context']
        if not isinstance(recovery, dict) or recovery.get('source_worker_id') != lease['worker_id']:
            raise CloudError('supplemental_account_binding_denied')
        source_run = mc_runner.uid(recovery.get('source_local_run_id'))
        source = self._runner('status', {'run_id': source_run})
        session = mc_runner.uid(source.get('session_id'))
        if (source.get('platform') != lease['platform'] or source.get('state') != 'failed'
                or recovery.get('request_session_id') not in (None, session)):
            raise CloudError('supplemental_account_binding_denied')
        request['session_id'] = session
        state['session_id'] = session
        account = self._runner('account_status', {'session_id': session, 'platform': lease['platform']})
        expected = recovery.get('account_context') or {}
        generation = expected.get('generation', source.get('account_generation'))
        if type(generation) is not int or generation < 0:
            raise CloudError('supplemental_account_binding_denied')
        authorization_run = mc_runner.uid(recovery.get('authorization_local_run_id') or source_run)
        if authorization_run != source_run:
            authorization = self._runner('status', {'run_id': authorization_run})
            if (authorization.get('state') != 'login_required' or authorization.get('session_id') != session
                    or authorization.get('platform') != lease['platform']
                    or authorization.get('account_generation') != generation):
                raise CloudError('supplemental_account_binding_denied')
        context = {'session_id': session, 'generation': generation,
                   'account_ref': expected.get('account_ref', account.get('account_ref'))}
        state.update(account_context=context, recovery_authorized_run=authorization_run)
        verified = account.get('verified_at')
        return (account.get('generation') == generation and account.get('account_ref') == context['account_ref']
                and (context['account_ref'] is not None or account.get('identity_status') == 'manually_confirmed_same_account')
                and account.get('state') in ('authenticated', 'resumed') and account.get('login_verified') is True
                and account.get('login_in_progress') is not True
                and type(verified) in (int, float) and 0 <= time.time()-verified <= 180
                and account.get('authorized_for_run') == authorization_run)

    def _resume_login(self, state):
        context, lease = state.get('account_context', {}), state['lease']
        status = self.client.call('heartbeat', {'run_id':lease['run_id'],
            'lease_epoch':lease['lease_epoch'],'sequence':state.get('sequence',0)+1}).get('lease')
        if not isinstance(status, dict) or status.get('run_id') != lease['run_id'] or status.get('lease_epoch') != lease['lease_epoch']:
            raise CloudError('invalid_cloud_lease')
        state['desired_state'] = status.get('desired_state')
        if status.get('desired_state') != 'running':
            return False  # Retain context for explicit Owner continuation, without blocking other tasks.
        account = self._runner('account_status', {'session_id': context['session_id'], 'platform': lease['platform']})
        same = account.get('generation') == context.get('generation') and account.get('account_ref') == context.get('account_ref')
        identified = account.get('account_ref') is not None or account.get('identity_status') == 'manually_confirmed_same_account'
        generation = context.get('generation')
        valid_generation = type(generation) is int and generation >= 0 and (
            generation > 0 or context.get('account_ref') is None and
            account.get('identity_status') == 'manually_confirmed_same_account')
        from login_recovery_freshness import recovery_newer_than_failure
        failed = None
        if 'login_failed_at' not in state:
            failed = self._runner('status', {'run_id':state.get('local_run_id')})
        if not recovery_newer_than_failure(state, account, failed):return False
        verified_at = account.get('verified_at')
        fresh = type(verified_at) in (int,float) and 0 <= time.time()-verified_at <= 180
        authenticated = account.get('state') in ('authenticated','resumed') and account.get('login_verified') is True
        authorization_run = state.get('recovery_authorized_run') or state.get('local_run_id')
        if not (same and identified and valid_generation and fresh and authenticated
                and account.get('login_in_progress') is not True
                and account.get('authorized_for_run') == authorization_run):
            return False
        self.client.call('resume_login', {'run_id':lease['run_id'],'lease_epoch':lease['lease_epoch'],
            'local_run_id':authorization_run,'session_id':context['session_id'],
            'generation':context['generation'],'account_ref':context.get('account_ref'),
            'identity_status':account.get('identity_status'),'verified_at_ms':int(account['verified_at']*1000),
            'authorized_for_run':account['authorized_for_run']})
        self._observe_workflow(state, 'login_resumed')
        return True

    def start_scheduler(self):
        with self.scheduler_lock:
            if self.closed.is_set() or self.thread is not None and self.thread.is_alive():
                return
            def loop():
                try:
                    while not self.closed.is_set():
                        result = self.tick()
                        progressing = (result.get('state') == 'delivering'
                                       and result.get('delivery_progress') is True
                                       and type(result.get('pending')) is int and result['pending'] > 0
                                       and result.get('errors') == [] and not result.get('error'))
                        # Keep a cancellable fairness interval; failures retain the normal backoff.
                        self.closed.wait(min(self.interval, .05) if progressing else self.interval)
                except Exception:
                    self.scheduler_error = self.last_error = 'cloud_scheduler_failed'
            self.thread = threading.Thread(target=loop, daemon=True, name='cloud-machine-worker')
            self.machine_steps.start()
            self.scheduler_started = True
            self.last_tick_at = time.time()
            self._last_tick_monotonic = time.monotonic()
            try:
                self.thread.start()
            except Exception:
                self.thread = None
                self.scheduler_error = self.last_error = 'cloud_scheduler_failed'

    def close(self):
        self.machine_steps.close()
        with self.scheduler_lock:
            self.closed.set()
            thread = self.thread
        if thread:
            thread.join(timeout=20)
        if self.path.exists():
            state = mc_runner.read(self.path)
            if state.get('phase') == 'running' and state.get('local_run_id'):
                try:
                    self._stop_local(state, 'cloud_worker_shutdown')
                except CloudError:
                    state['phase'] = 'local_stop_unknown'
                    try:self._save(state)
                    except (OSError,ValueError,sqlite3.Error):self.last_error='cloud_stop_persistence_failed'
