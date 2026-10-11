"""Bounded local creator observation schedules, using the same OwnerTasks service."""
from contextlib import closing
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid
from urllib.parse import urlsplit, urlunsplit

from owner_tasks import plan
from mc_runner import BridgeError, contains_secret, uid


FIELDS = {'title', 'platforms', 'targets_by_platform', 'interval_minutes', 'window_days',
          'total_request_budget', 'per_cycle_requests', 'per_cycle_items', 'purpose',
          'authorization_ref', 'comments', 'replies', 'media', 'max_comments', 'idempotency_key'}


def _int(data, name, default, low, high):
    value = data.get(name, default)
    if type(value) is not int or not low <= value <= high:
        raise ValueError('invalid_' + name)
    return value


def _validate(payload):
    if not isinstance(payload, dict) or set(payload) - FIELDS:
        raise ValueError('invalid_watchlist_request')
    title = payload.get('title', '博主持续观察')
    if not isinstance(title, str) or not title.strip() or len(title) > 200 or contains_secret(title):
        raise ValueError('invalid_watchlist_title')
    interval = _int(payload, 'interval_minutes', 720, 1, 525600)
    window = _int(payload, 'window_days', 3, 1, 3650)
    if window * 1440 < 2880 + interval:
        raise ValueError('watch_window_requires_48h_overlap_plus_interval')
    total = _int(payload, 'total_request_budget', 1000, 1, 1000000)
    requests = _int(payload, 'per_cycle_requests', 100, 1, 3500)
    items = _int(payload, 'per_cycle_items', 20, 1, 700)
    if total < requests:
        raise ValueError('watch_total_budget_below_cycle_budget')
    request = {key: payload[key] for key in ('platforms', 'targets_by_platform', 'purpose',
               'authorization_ref', 'comments', 'replies', 'media', 'max_comments') if key in payload}
    request.update(mode='creator', desired_items=items, max_api_requests=requests,
                   idempotency_key='watch-validation')
    validated = plan(request)
    if items < len(validated['request']['platforms']) or requests < len(validated['request']['platforms']):
        raise ValueError('watch_cycle_budget_must_cover_platforms')
    key = payload.get('idempotency_key')
    if key is not None and (not isinstance(key, str) or not 1 <= len(key) <= 160 or contains_secret(key)):
        raise ValueError('invalid_watchlist_idempotency_key')
    return {'title': title, 'interval_minutes': interval, 'window_days': window,
            'total_request_budget': total, 'per_cycle_requests': requests,
            'per_cycle_items': items, 'task_request': validated['request']}


class Watchlists:
    def __init__(self, root, owner_tasks, clock=time.time, interval=5):
        base = Path(root).expanduser()
        if base.is_symlink():
            raise ValueError('unsafe_watchlist_root')
        self.root = base.resolve() / 'watchlists'
        if self.root.is_symlink():
            raise ValueError('unsafe_watchlist_root')
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root / 'watchlists.sqlite3'
        if self.path.is_symlink():
            raise ValueError('unsafe_watchlist_database')
        if not self.path.exists():
            os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
        os.chmod(self.path, 0o600)
        self.owner_tasks, self.clock, self.interval = owner_tasks, clock, interval
        self.lock = threading.RLock()
        self.closed, self.wakeup = threading.Event(), threading.Event()
        self.thread = None
        with closing(self._db()) as db:
            db.execute('CREATE TABLE IF NOT EXISTS watches(id TEXT PRIMARY KEY, idem TEXT UNIQUE, digest TEXT NOT NULL, data TEXT NOT NULL)')
            db.commit()

    def _db(self):
        if self.path.is_symlink():
            raise ValueError('unsafe_watchlist_database')
        db = sqlite3.connect(str(self.path), timeout=15)
        db.execute('PRAGMA synchronous=FULL')
        return db

    def _load(self, db, watch_id):
        try:
            uid(watch_id)
        except (ValueError, BridgeError):
            raise ValueError('invalid_watchlist_id') from None
        row = db.execute('SELECT data FROM watches WHERE id=?', (watch_id,)).fetchone()
        if not row:
            raise ValueError('watchlist_not_found')
        return json.loads(row[0])

    def _save(self, db, watch, write_desired=False):
        if not db.in_transaction:
            db.execute('BEGIN IMMEDIATE')
        if not write_desired:
            row = db.execute('SELECT data FROM watches WHERE id=?', (watch['watch_id'],)).fetchone()
            if row:
                saved = json.loads(row[0])
                watch['desired_state'] = saved['desired_state']
                watch['unknown_outcome'] = watch.get('unknown_outcome', False) or saved.get('unknown_outcome', False)
                watch['manual_child_stop'] = watch.get('manual_child_stop', False) or saved.get('manual_child_stop', False)
                if watch['cycles'] and saved['cycles'] and watch['cycles'][-1]['cycle_number'] == saved['cycles'][-1]['cycle_number']:
                    watch['cycles'][-1]['stopped_by_watch'] = watch['cycles'][-1].get('stopped_by_watch', False) or saved['cycles'][-1].get('stopped_by_watch', False)
        watch['updated_at'] = self.clock()
        db.execute('UPDATE watches SET data=? WHERE id=?', (json.dumps(watch, ensure_ascii=False), watch['watch_id']))
        db.commit()

    @staticmethod
    def _public(watch):
        value = json.loads(json.dumps(watch))
        value.pop('task_request', None)
        value.pop('create_hash', None)
        value['platforms'] = list(watch['task_request']['platforms'])
        value['targets_by_platform'] = {platform: [urlunsplit((*urlsplit(target)[:3], '', '')) if '://' in target else target for target in targets]
                                       for platform, targets in watch['task_request']['targets_by_platform'].items()}
        value['navigation_locators_omitted'] = value['targets_by_platform'] != watch['task_request']['targets_by_platform']
        value['cycle_count'] = len(value['cycles'])
        value['cycles'] = value['cycles'][-50:]
        value['request_budget_remaining'] = value['total_request_budget'] - value['requests_reserved_total']
        return value

    def preview(self, payload):
        validated = _validate(payload)
        proposal = plan(validated['task_request'])
        watch = {**validated, 'watch_id': None, 'state': 'preview', 'desired_state': 'not_started',
                 'cycles': [], 'requests_reserved_total': 0, 'active_task_id': None,
                 'coverage': 'observed_window', 'storage_scope': 'local_only',
                 'sampling_semantics': 'creator latest items; requested window is not a source date filter',
                 'budget_semantics': 'each cycle reserves its full maximum; unused budget is not refunded',
                 'blocked_platforms': [{'platform': child['platform'], 'reason_code': child['reason_code']}
                                      for child in proposal['children'] if child['reason_code']]}
        return {'ok': True, 'watchlist': self._public(watch), 'source_actions_started': 0}

    def create(self, payload):
        validated = _validate(payload)
        import hashlib
        digest = hashlib.sha256(json.dumps(validated, sort_keys=True, ensure_ascii=False).encode('utf8')).hexdigest()
        with self.lock, closing(self._db()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            idem = payload.get('idempotency_key')
            row = db.execute('SELECT digest,data FROM watches WHERE idem=?', (idem,)).fetchone() if idem else None
            if row:
                if row[0] != digest:
                    raise ValueError('watchlist_idempotency_conflict')
                watch = json.loads(row[1])
            else:
                now = self.clock()
                watch = {**validated, 'watch_id': str(uuid.uuid4()), 'created_at': now,
                         'updated_at': now, 'desired_state': 'running', 'state': 'scheduled',
                         'reason_code': None, 'next_due_at': now, 'active_task_id': None,
                         'requests_reserved_total': 0, 'cycles': [], 'storage_scope': 'local_only',
                         'unknown_outcome': False, 'manual_child_stop': False,
                         'coverage': 'observed_window', 'sampling_semantics': 'creator latest items; requested window is not a source date filter',
                         'incremental_semantics': 'identity/text versions deduplicate in results store; no source completeness proof',
                         'request_limit_scope': 'Python HTTP attempts; browser resource requests excluded',
                         'budget_semantics': 'each cycle reserves its full maximum; unused budget is not refunded',
                         'reward_eligible': False}
                db.execute('INSERT INTO watches VALUES (?,?,?,?)', (watch['watch_id'], idem, digest, json.dumps(watch, ensure_ascii=False)))
            db.commit()
        self.start_scheduler()
        self.wakeup.set()
        return {'ok': True, 'watchlist': self._public(watch)}

    def list(self):
        with self.lock, closing(self._db()) as db:
            watches = [self._public(json.loads(row[0])) for row in db.execute('SELECT data FROM watches ORDER BY rowid DESC LIMIT 200')]
        return {'ok': True, 'watchlists': watches}

    def status(self, watch_id):
        with self.lock, closing(self._db()) as db:
            watch = self._load(db, watch_id)
        return {'ok': True, 'watchlist': self._public(watch)}

    def stop(self, watch_id):
        with self.lock, closing(self._db()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            watch = self._load(db, watch_id)
            if watch['active_task_id']:
                try:
                    previous = self.owner_tasks.status(watch['active_task_id'])['task']
                    if previous.get('desired_state') in ('stopped', 'paused') and not watch['cycles'][-1].get('stopped_by_watch'):
                        watch['manual_child_stop'] = True
                except Exception:
                    watch['unknown_outcome'] = True
            watch.update(desired_state='stopped', state='paused', reason_code='user_stop')
            if watch['active_task_id']:
                watch['cycles'][-1]['stopped_by_watch'] = True
            self._save(db, watch, write_desired=True)
            if watch['active_task_id']:
                try:
                    self.owner_tasks.stop(watch['active_task_id'])
                except Exception:
                    watch['reason_code'] = 'stop_outcome_unknown'
                    watch['unknown_outcome'] = True
                    self._save(db, watch)
        return {'ok': True, 'watchlist': self._public(watch)}

    def resume(self, watch_id):
        with self.lock, closing(self._db()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            watch = self._load(db, watch_id)
            if watch.get('unknown_outcome') or watch['reason_code'] in ('prior_cycle_unknown', 'dispatch_outcome_unknown', 'stop_outcome_unknown') or watch['cycles'] and watch['cycles'][-1]['state'] in ('dispatching', 'unknown'):
                raise ValueError('watchlist_unknown_requires_reconciliation')
            if watch.get('manual_child_stop') or watch['reason_code'] == 'owner_task_user_stop':
                raise ValueError('watchlist_owner_task_stopped_create_new_watchlist')
            if watch['requests_reserved_total'] >= watch['total_request_budget']:
                raise ValueError('watchlist_budget_exhausted')
            if watch['active_task_id']:
                try:
                    task = self.owner_tasks.status(watch['active_task_id'])['task']
                except Exception:
                    raise ValueError('watchlist_unknown_requires_reconciliation') from None
                if task.get('desired_state') in ('stopped', 'paused') and not watch['cycles'][-1].get('stopped_by_watch'):
                    raise ValueError('watchlist_owner_task_stopped_create_new_watchlist')
                if any(child.get('state') == 'unknown' for child in task['children']):
                    raise ValueError('watchlist_unknown_requires_reconciliation')
                if watch['reason_code'] == 'prior_cycle_requires_action':
                    self.owner_tasks.resume(watch['active_task_id'])
                elif watch['reason_code'] == 'prior_cycle_failed':
                    watch['cycles'][-1].update(state='failed_observed', completed_at=self.clock(), contents=task.get('contents', 0), comments=task.get('comments', 0))
                    watch['active_task_id'] = None
            watch.update(desired_state='running', state='scheduled', reason_code=None, next_due_at=self.clock())
            self._save(db, watch, write_desired=True)
        self.start_scheduler()
        self.wakeup.set()
        return {'ok': True, 'watchlist': self._public(watch)}

    def _refresh(self, db, watch):
        cycle = watch['cycles'][-1]
        try:
            response = self.owner_tasks.status(watch['active_task_id'])
            task = response['task']
            children = task['children']
            if response.get('ok') is False or not isinstance(children, list) or len(children) != len(watch['task_request']['platforms']) or any(not isinstance(child, dict) or child.get('state') not in ('queued', 'dispatching', 'running', 'waiting', 'unknown', 'completed', 'failed', 'stopped') for child in children):
                raise ValueError()
        except Exception:
            watch.update(state='blocked', reason_code='prior_cycle_unknown', unknown_outcome=True)
            return
        if any(c.get('state') == 'unknown' or c.get('reason_code') in ('source_outcome_unknown', 'dispatch_outcome_unknown', 'result_import_failed', 'invalid_import_result') for c in children):
            watch.update(state='blocked', reason_code='prior_cycle_unknown', unknown_outcome=True)
            return
        if task.get('desired_state') in ('stopped', 'paused') and not cycle.get('stopped_by_watch'):
            watch.update(desired_state='stopped', state='paused', reason_code='owner_task_user_stop', manual_child_stop=True)
            return
        unsettled = any(c.get('active_run_id') or c.get('state') in ('queued', 'dispatching', 'running') for c in children)
        if unsettled:
            watch['state'] = 'paused' if watch['desired_state'] == 'stopped' else 'observing'
            return
        reasons = {c.get('reason_code') for c in children if c.get('reason_code')}
        if reasons & {'login_required', 'session_busy', 'configure_executor_first', 'external_executor_missing', 'external_python_missing', 'headless_requires_existing_session', 'missing_targets', 'media_not_supported_by_upstream', 'budget_not_allocated'}:
            watch.update(state='blocked', reason_code='prior_cycle_requires_action')
            return
        if any(c.get('state') == 'failed' for c in children):
            watch.update(state='blocked', reason_code='prior_cycle_failed')
            return
        cycle.update(state='stopped' if cycle.get('stopped_by_watch') else 'observed_only',
                     completed_at=self.clock(), contents=task.get('contents', 0), comments=task.get('comments', 0),
                     requests_spent=sum(c.get('requests_spent', 0) for c in children), coverage='observed_window')
        watch['active_task_id'] = None
        watch['next_due_at'] = self.clock() if cycle.get('stopped_by_watch') and watch['desired_state'] == 'running' else self.clock() + watch['interval_minutes'] * 60
        watch.update(state='scheduled' if watch['desired_state'] == 'running' else 'paused', reason_code=None if watch['desired_state'] == 'running' else 'user_stop')

    def poll(self):
        with self.lock, open(self.root / 'scheduler.lock', 'a+') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return {'ok': True, 'scheduler_busy': True}
            with closing(self._db()) as db:
                ids = [row[0] for row in db.execute('SELECT id FROM watches ORDER BY rowid')]
                for watch_id in ids:
                    watch = self._load(db, watch_id)
                    if watch['active_task_id']:
                        self._refresh(db, watch)
                        self._save(db, watch, write_desired=watch.get('manual_child_stop', False))
                    elif watch['cycles'] and watch['cycles'][-1]['state'] == 'dispatching':
                        watch.update(state='blocked', reason_code='dispatch_outcome_unknown', unknown_outcome=True)
                        self._save(db, watch)
                    if watch['desired_state'] != 'running' or watch['state'] == 'blocked' or watch['active_task_id'] or self.clock() < watch['next_due_at']:
                        continue
                    remaining = watch['total_request_budget'] - watch['requests_reserved_total']
                    budget = min(remaining, watch['per_cycle_requests'])
                    if budget < len(watch['task_request']['platforms']):
                        watch.update(state='budget_exhausted', reason_code='total_request_budget_exhausted')
                        self._save(db, watch)
                        continue
                    number = len(watch['cycles']) + 1
                    request = {**watch['task_request'], 'max_api_requests': budget,
                               'idempotency_key': 'watch:' + watch_id + ':' + str(number)}
                    cycle = {'cycle_number': number, 'state': 'dispatching', 'created_at': self.clock(),
                             'request_budget': budget, 'idempotency_key': request['idempotency_key'],
                             'coverage': 'observed_window'}
                    watch['cycles'].append(cycle)
                    watch['requests_reserved_total'] += budget
                    watch.update(state='dispatching', reason_code=None)
                    self._save(db, watch)
                    if watch['desired_state'] != 'running':
                        cycle.update(state='stopped', stopped_by_watch=True)
                        watch.update(state='paused', reason_code='user_stop')
                        self._save(db, watch)
                        continue
                    try:
                        response = self.owner_tasks.create(request)
                        task_id = response['task']['task_id']
                        uid(task_id)
                        if response.get('ok') is False:
                            raise ValueError()
                    except Exception:
                        cycle['state'] = 'unknown'
                        watch.update(state='blocked', reason_code='dispatch_outcome_unknown', unknown_outcome=True)
                    else:
                        cycle.update(state='running', task_id=task_id)
                        watch.update(active_task_id=task_id, state='observing')
                    self._save(db, watch)
                    if watch['desired_state'] == 'stopped' and watch['active_task_id']:
                        cycle['stopped_by_watch'] = True
                        self.owner_tasks.stop(watch['active_task_id'])
                        self._save(db, watch)
        return {'ok': True}

    def start_scheduler(self):
        with self.lock:
            if self.thread is None and not self.closed.is_set():
                self.thread = threading.Thread(target=self._work, daemon=True, name='watchlist-scheduler')
                self.thread.start()

    def _work(self):
        while not self.closed.is_set():
            try:
                self.poll()
            except (OSError, ValueError, sqlite3.Error):
                pass
            self.wakeup.wait(self.interval)
            self.wakeup.clear()

    def close(self):
        self.closed.set()
        self.wakeup.set()
        if self.thread:
            self.thread.join(timeout=20)
