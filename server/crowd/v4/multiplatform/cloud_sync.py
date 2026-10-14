"""Scoped cloud task adapter and durable machine delivery. No participant rewards."""
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import fcntl
import hashlib
import json
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
    'capture_size_limit','cloud_response_size_limit','invalid_cloud_response','cloud_redirect_denied','unacknowledged_capture',
    'supplemental_account_binding_denied','invalid_cloud_reconciliation','invalid_encoding','integer_required',
    'duplicate_json_key','invalid_unicode','encoding_limit','unsafe_cloud_file','unsafe_cloud_root','cloud_outcome_unknown',
    'runner_status_unavailable','cloud_delivery_lease_unavailable','cloud_delivery_lease_denied'}
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
        for attempt in range(attempts):
            http_response = False
            try:
                try:
                    response = self.opener.open(request, timeout=15)
                except urllib.error.HTTPError as error:
                    response = error
                    http_response = True
                with response:
                    raw = response.read(2000001)
                    if len(raw) > 2000000:
                        raise CloudError('cloud_response_size_limit')
                    result = _strict_json(raw, max_nodes=100000)
                if not isinstance(result, dict) or result.get('ok') is not True or not isinstance(result.get('result'), dict):
                    code = result.get('error') if isinstance(result, dict) else None
                    raise CloudError(code if isinstance(code, str) and re.fullmatch(r'[a-z_]{1,80}', code) else 'invalid_cloud_response')
                return result['result']
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                if (attempt + 1 < attempts and not http_response
                        and isinstance(error, (urllib.error.URLError, TimeoutError))):
                    continue
                code = 'cloud_read_unavailable' if self.role == 'owner' and action in ('task_list', 'task_status', 'transcript_get', 'participant_health', 'unified_status', 'node_events', 'unified_preview', 'unified_dispatches') else 'cloud_outcome_unknown'
                raise CloudError(code) from None


class CloudOwnerAdapter:
    """OwnerTasks-compatible UI/watch adapter. Cloud alone owns dispatch."""
    def __init__(self, client):
        self.client = client

    def preview(self, payload):
        return {'ok': True, **self.client.call('task_preview', payload)}

    def create(self, payload):
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

    def reconcile(self, payload):
        return {'ok': True, **self.client.call('task_reconcile', payload)}

    def start_scheduler(self):
        pass

    def close(self):
        pass


class CloudOutbox:
    def __init__(self, root, client):
        self.root = _private_root(root, 'cloud-outbox')
        self.path = self.root / 'outbox.sqlite3'
        _private_file(self.path)
        self.client = client
        with self._db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS captures(id TEXT PRIMARY KEY, run_id TEXT NOT NULL, envelope TEXT NOT NULL, digest TEXT NOT NULL, state TEXT NOT NULL, receipt TEXT, error TEXT)')

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
                    if not isinstance(entry, str) or entry not in mc_runner.DISCOVERY_KINDS or entry == 'trending' and platform != 'bilibili':
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
        return list(dict.fromkeys(ids))

    def flush(self, run_id=None, limit=2000, before_send=None):
        if type(limit) is not int or not 1 <= limit <= 2000:
            raise CloudError('invalid_imported_records')
        with self._db() as db:
            rows = db.execute('SELECT id,envelope,digest FROM captures WHERE state=?' +
                (' AND run_id=?' if run_id else '') + ' ORDER BY rowid LIMIT ?',
                ('pending', run_id, limit) if run_id else ('pending', limit)).fetchall()
        for capture_id, encoded, digest in rows:
            envelope = json.loads(encoded)
            binding = {'run_id': envelope['run_id'], 'lease_epoch': envelope['lease_epoch']}
            try:
                if before_send:
                    before_send()
                receipt = self.client.call('receipt', {**binding, 'capture_id': capture_id, 'envelope_hash': digest}).get('receipt')
                if receipt is None:
                    if before_send:
                        before_send()
                    receipt = self.client.call('capture', {**binding, 'envelope': envelope, 'envelope_hash': digest}).get('receipt')
                if not isinstance(receipt, dict) or any(receipt.get(k) != v for k, v in {
                    'capture_id': capture_id, 'envelope_hash': digest, **binding, 'task_id': envelope['task_id'],
                    'child_id': envelope['child_id'], 'status': 'received', 'source_kind': 'machine_api', 'reward_eligible': False}.items()):
                    raise CloudError('invalid_cloud_ack')
                with self._db() as db:
                    db.execute('UPDATE captures SET state=?,receipt=?,error=NULL WHERE id=? AND digest=?',
                               ('acknowledged', canonical(receipt), capture_id, digest))
            except DeliveryLeaseError:
                raise
            except (CloudError, ValueError) as error:
                code = str(error) if re.fullmatch(r'[a-z_]{1,80}', str(error)) else 'cloud_outcome_unknown'
                with self._db() as db:
                    db.execute('UPDATE captures SET error=? WHERE id=?', (code, capture_id))
                # A lost response never deletes data or causes another source dispatch.
                if code in ('worker_revoked', 'principal_denied', 'cloud_outcome_unknown'):
                    break
        return self.stats(run_id)

    def stats(self, run_id=None):
        with self._db() as db:
            rows = db.execute('SELECT id,state,error FROM captures' + (' WHERE run_id=?' if run_id else ''),
                              (run_id,) if run_id else ()).fetchall()
        return {'pending': sum(r[1] == 'pending' for r in rows),
                'acknowledged': sum(r[1] == 'acknowledged' for r in rows),
                'capture_ids': [r[0] for r in rows], 'errors': list(dict.fromkeys(r[2] for r in rows if r[2]))}


class CloudWorker:
    """One durable dispatch controller, backed by cloud leases and the existing runner."""
    def __init__(self, root, client, runner_callback, session_selector=None, existing_reader=None, interval=5, postprocessing_callback=None):
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
                    for run_id in list(latest.get('postprocessing_runs', [])):
                        try:self.postprocessing_callback('enqueue', {'run_id': run_id})
                        except Exception:
                            self.postprocessing_error = 'postprocessing_enqueue_failed'
                            continue  # Retain this pending job without stopping a separate source lease.
                        latest['postprocessing_runs'].remove(run_id)
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
                # Fail closed if authorization cannot be renewed. Never start another run.
                lease = state.get('lease')
                if lease and state.get('local_run_id') and state.get('phase') == 'running':
                    try:
                        self._stop_local(state, 'cloud_controller_error', code)
                    except CloudError:
                        state['phase'] = 'local_stop_unknown'
                        try:self._save(state)
                        except (OSError,ValueError,sqlite3.Error):self.last_error='cloud_stop_persistence_failed'
                return {'state': state.get('phase'), 'error': code}

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
                    'workflow_monitor_error': self.workflow_events.error}
            last=self._stop_summary(self.last_stop or state.get('last_stop'))
            if last:summary['last_stop']=last
            return {**summary, **self.scheduler_status()}
        except (ValueError, OSError, sqlite3.Error):
            summary={'phase':'local_stop_unknown' if self.stop_unknown_run_id else 'state_unreadable','last_error':self.last_error or 'cloud_worker_failed'}
            last=self._stop_summary(self.last_stop)
            if last:summary['last_stop']=last
            return {**summary, **self.scheduler_status()}

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
            state = {'phase': 'claiming', 'claim_id': str(uuid.uuid4()), 'waiting_logins': waiting,
                     'unavailable_platforms': sorted({v['lease']['platform'] for v in waiting if v.get('desired_state','running') == 'running'})}
            self._save(state)
        if state['phase'] == 'claiming':
            response = self.client.call('claim', {'claim_id': state['claim_id'],
                                                'unavailable_platforms': state.get('unavailable_platforms', [])})
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
                if self.existing_reader is None:
                    raise CloudError('existing_saved_reader_missing')
                with self._delivery_keepalive(state):
                    records = self.existing_reader(lease)
                    if isinstance(records, dict):
                        records = records.get('records')
                    refs = lease.get('record_refs', [])
                    if not isinstance(records, list) or any(not any((r.get('record', r).get('content_id') == ref['content_id'] and r.get('record', r).get('kind') == ref.get('kind','content')) for ref in refs) for r in records):
                        raise CloudError('existing_saved_selection_mismatch')
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
            state.pop('status_read_error',None)
            self._save(state)
            if stage not in mc_runner.FINAL:
                return {'state': 'running', 'local_stage': stage}
            state.update(phase='importing', outcome='unknown' if stage == 'interrupted' else stage,
                         api_attempts=current.get('api_requests', current.get('api_attempts', 0)))
            if state['outcome'] not in ('completed','stopped','failed','login_required'):
                state['outcome'] = 'unknown'
            if state['outcome'] == 'login_required':
                account = self._runner('account_status', {'session_id': state['session_id'], 'platform': lease['platform']})
                state['account_context'] = {'session_id': state['session_id'],
                    'generation': account.get('generation', 0), 'account_ref': account.get('account_ref')}
            self._save(state)
        if state['phase'] == 'importing':
            with self._delivery_keepalive(state):
                records = self._runner('import', {'run_id': state['local_run_id']})
                self.outbox.stage_imported(records, state['lease'])
            state['phase'] = 'delivering'
            self._save(state)
        if state['phase'] == 'delivering':
            acknowledged_before = self.outbox.stats(state['lease']['run_id'])['acknowledged']
            status = self.outbox.flush(state['lease']['run_id'], limit=4,
                                       before_send=lambda: self._renew_delivery(state))
            if status['pending']:
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
            self._observe_workflow(state, 'waiting_login' if state['outcome'] == 'login_required' else
                                   'completed' if state['outcome'] == 'completed' else 'paused')
            if (self.postprocessing_callback and state['outcome'] == 'completed' and state.get('local_run_id')
                    and state['lease'].get('request', {}).get('platform_options', {}).get('transcript_only') is True):
                state['postprocessing_runs'] = list(dict.fromkeys([*state.get('postprocessing_runs', []), state['local_run_id']]))
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
            self.scheduler_started = True
            self.last_tick_at = time.time()
            self._last_tick_monotonic = time.monotonic()
            try:
                self.thread.start()
            except Exception:
                self.thread = None
                self.scheduler_error = self.last_error = 'cloud_scheduler_failed'

    def close(self):
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
