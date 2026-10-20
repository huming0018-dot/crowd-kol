"""Explicit Owner accounting recovery; never imports, starts or retries source."""
from contextlib import contextmanager
from datetime import datetime, timezone
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat

import mc_runner
from cloud_sync import canonical

PHASES = {'terminal_recovery_parked', 'terminal_recovery_unknown'}


def need(value, code='terminal_recovery_denied'):
    if not value:
        raise ValueError(code)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def state_hash(value):
    return digest(canonical(value).encode())


def read(path):
    path = Path(path)
    need(path.is_absolute() and path.resolve() == path and not path.is_symlink())
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        need(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
             and not info.st_mode & 0o022 and info.st_size <= 1048576)
        raw = os.read(fd, 1048577)
        after = os.fstat(fd)
        need(len(raw) == info.st_size and
             (info.st_ino, info.st_mtime_ns, info.st_ctime_ns, info.st_size) ==
             (after.st_ino, after.st_mtime_ns, after.st_ctime_ns, after.st_size))
        return raw
    finally:
        os.close(fd)


@contextmanager
def inactive_session(app, original):
    run_id = mc_runner.uid(original['local_run_id'])
    root = app._registered_run_root(run_id)
    session = mc_runner.uid(original['session_id'])
    path = root / 'sessions' / session / 'active.lock'
    need(not path.is_symlink() and path.resolve() == path)
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        need(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
             and not info.st_mode & 0o077)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield root / 'runs' / run_id
    finally:
        os.close(fd)


def persist(worker, state):
    worker._save(state)
    directory = os.open(worker.path.parent, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def local_proof(worker, original, run):
    need(original.get('phase') == 'importing' and original.get('outcome') == 'failed')
    lease = original['lease']
    need(lease.get('delivery_basis') == 'live_capture'
         and lease.get('source_continuation') is None)
    manifest_raw, status_raw = read(run / 'manifest.json'), read(run / 'status.json')
    manifest, status = json.loads(manifest_raw), json.loads(status_raw)
    local_id = original['local_run_id']
    need(manifest.get('run_id') == status.get('run_id') == local_id)
    need(status.get('state') == 'failed' and type(status.get('exit_code')) is int
         and -128 <= status['exit_code'] <= 255 and status['exit_code'] != 0)
    # Unknown request accounting remains null even if the old worker guessed zero.
    need(status.get('api_requests') is None and status.get('api_attempts') is None)
    need(lease['request'].get('session_id') in (None, original['session_id']))
    request = {**lease['request'], 'session_id': original['session_id']}
    need(manifest.get('request') == mc_runner.validate(request))
    need(manifest.get('executor', {}).get('backend') == 'pro')
    stats = worker.outbox.stats(lease['run_id'])
    need(stats['pending'] == 0 and stats['capture_ids'] == [])
    return {'executor_inactive': True, 'local_state': 'failed',
            'exit_code': status['exit_code'], 'api_attempts': None,
            'status_sha256': digest(status_raw), 'manifest_sha256': digest(manifest_raw)}


def cloud_view(client, original):
    lease = original['lease']
    task = client.call('task_status', {'task_id': lease['task_id']})['task']
    need(task.get('task_id') == lease['task_id'] and type(task.get('revision')) is int and task['revision'] >= 1)
    matches = [c for c in task.get('children', []) if c.get('child_id') == lease['child_id']]
    need(len(matches) == 1)
    child = matches[0]
    need(child.get('worker_id') == lease['worker_id']
         and type(child.get('lease_epoch')) is int and child['lease_epoch'] == lease['lease_epoch']
         and child.get('local_run_id') == original['local_run_id']
         and lease['run_id'] in child.get('runs', [])
         and type(child.get('received_captures')) is int and child['received_captures'] == 0)
    attempts = [a for a in child.get('attempts', []) if a.get('run_id') == lease['run_id']
                and a.get('claim_id') == original['claim_id']]
    need(len(attempts) == 1 and attempts[0].get('worker_id') == lease['worker_id']
         and attempts[0].get('local_run_id') == original['local_run_id']
         and type(attempts[0].get('lease_epoch')) is int
         and attempts[0]['lease_epoch'] == lease['lease_epoch'])
    need(type(child.get('request_quota')) is int and child['request_quota'] > 0
         and child['request_quota'] == lease['request']['max_api_requests'])
    need(all(type(child.get(k)) is int and 0 <= child[k] <= child['request_quota']
             for k in ('requests_spent', 'requests_reserved')))
    return task, child


def summary(state, original, task, child):
    recovery = state.get('terminal_recovery', {})
    expired = False
    if type(child.get('lease_until')) is str:
        try:
            until = datetime.fromisoformat(child['lease_until'].replace('Z', '+00:00'))
            expired = until <= datetime.now(timezone.utc)
        except (ValueError, TypeError):
            pass
    return {'ok': True, 'available': True, 'schema': 'crowd-terminal-import-recovery-v1',
            'state_hash': state_hash(state), 'task_id': original['lease']['task_id'],
            'cloud_run_id': original['lease']['run_id'], 'local_run_id': original['local_run_id'],
            'state': recovery.get('state', 'needs_park'), 'source_outcome': 'unknown',
            'api_attempts': None, 'quota_charge': child['request_quota'], 'released_requests': 0,
            'can_park': not recovery,
            'can_reconcile': recovery.get('state') == 'parked' and child.get('state') == 'unknown' and expired,
            'can_verify': recovery.get('state') == 'unknown', 'cloud_revision': task['revision']}


def audited_receipt(recovery, task, child):
    payload = recovery['intent']
    audit = child.get('terminal_audit') or {}
    need(child.get('state') == 'failed' and child.get('reason_code') == 'audited_terminal_unknown'
         and audit.get('audit_hash') == payload['audit_hash']
         and audit.get('mode') == 'terminal_unknown' and audit.get('outcome') == 'unknown'
         and type(audit.get('released_requests')) is int and audit['released_requests'] == 0
         and type(child.get('requests_spent')) is int and child['requests_spent'] == child['request_quota']
         and type(child.get('requests_reserved')) is int and child['requests_reserved'] == 0
         and type(audit.get('charged_requests')) is int
         and audit['charged_requests'] == recovery['quota'] - recovery['prior_spent'])
    mc_runner.uid(audit.get('audit_id'))
    return audit


def finish_local(worker, state, task, child):
    recovery = copy.deepcopy(state['terminal_recovery'])
    audit = audited_receipt(recovery, task, child)
    recovery.update(state='accounted_unknown', audit=audit)
    history = copy.deepcopy(state.get('terminal_recoveries', {}))
    history[state['lease']['run_id']] = recovery
    updated = {k: v for k, v in state.items() if k not in
               {'lease', 'local_run_id', 'claim_id', 'sequence', 'session_id', 'outcome',
                'api_attempts', 'terminal_recovery'}}
    updated.update(phase='idle', terminal_recoveries=history)
    persist(worker, updated)
    return {'ok': True, 'state': 'accounted_unknown', 'source_outcome': 'unknown',
            'api_attempts': None, 'source_restarted': False, 'audit_id': audit['audit_id']}


def handle(app, payload):
    need(type(payload) is dict and payload.get('recovery_action') in
         {'status', 'park', 'reconcile', 'verify'}, 'invalid_terminal_recovery_request')
    action = payload['recovery_action']
    need(set(payload) == ({'recovery_action'} if action == 'status' else
                         {'recovery_action', 'expected_state_hash', 'expected_revision'}), 'invalid_terminal_recovery_request')
    worker, client = app.cloud_worker, app.cloud_client
    need(worker is not None and client is not None and client.role == 'owner')
    need(not worker.lock_path.is_symlink())
    with open(worker.lock_path, 'r+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = mc_runner.read(worker.path)
        if state.get('phase') not in PHASES | {'importing'}:
            need(action == 'status')
            return {'ok': True, 'available': False, 'reason': 'no_failed_import'}
        if action != 'status':
            need(payload['expected_state_hash'] == state_hash(state), 'terminal_recovery_state_changed')
        recovery = state.get('terminal_recovery')
        original = recovery['original_state'] if recovery else state
        with inactive_session(app, original) as run:
            proof = local_proof(worker, original, run)
            task, child = cloud_view(client, original)
            if action != 'status':
                need(type(payload['expected_revision']) is int and payload['expected_revision'] == task['revision'],
                     'terminal_recovery_revision_changed')
            if recovery:
                need(proof == recovery['proof'], 'terminal_recovery_artifacts_changed')
            info = summary(state, original, task, child)
            if action == 'status':
                return info
            if action == 'park':
                need(recovery is None, 'terminal_recovery_already_parked')
                state['terminal_recovery'] = {'state': 'parked', 'proof': proof,
                    'original_state': copy.deepcopy(state), 'cloud_revision_at_park': task['revision'],
                    'prior_spent': child['requests_spent'], 'quota': child['request_quota']}
                state['phase'] = 'terminal_recovery_parked'
                persist(worker, state)
                return summary(state, original, task, child)
            need(recovery is not None)
            if action == 'verify':
                need(recovery['state'] == 'unknown', 'terminal_recovery_no_unknown')
                return finish_local(worker, state, task, child)
            need(info['can_reconcile'], 'terminal_recovery_waiting_expiry')
            need('intent' not in recovery, 'terminal_recovery_outcome_unknown')
            lease = original['lease']
            audit = {**{k: lease[k] for k in ('task_id', 'child_id', 'worker_id', 'run_id', 'lease_epoch')},
                     'claim_id': original['claim_id'], 'local_run_id': original['local_run_id'],
                     'expected_revision': task['revision'], 'expected_finish_hash': child.get('finish_hash'),
                     'idempotency_key': 'terminal-import:' + lease['run_id'], 'mode': 'terminal_unknown',
                     'capture_count': 0, 'capture_digest': digest(b'crowd-machine-capture-audit-v1\n'),
                     'proof': proof}
            audit['canonical_audit'] = canonical({k: v for k, v in audit.items() if k != 'expected_revision'})
            audit['audit_hash'] = digest(('crowd-machine-terminal-audit-v1\n' + audit['canonical_audit']).encode())
            recovery.update(state='unknown', intent=audit)
            state['phase'] = 'terminal_recovery_unknown'
            persist(worker, state)  # One fixed intent before one mutation. Never resend it.
            response = client.call('task_reconcile', {k: v for k, v in audit.items()
                                  if k not in ('canonical_audit', 'audit_hash')})
            need(response.get('reconciled') is True and response.get('audit_hash') == audit['audit_hash']
                 and all(response.get(k) == audit[k] for k in ('worker_id', 'claim_id', 'run_id', 'lease_epoch')),
                 'terminal_recovery_ack_unknown')
            task, child = cloud_view(client, original)
            return finish_local(worker, state, task, child)
