"""Local durable Owner task grouping around the existing MC runner.

This is local_only orchestration, not the cloud TaskService or a source coverage proof.
"""
import argparse
import contextlib
import csv
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from urllib.parse import urlsplit

import mc_runner

ALIASES = {**{k: k for k in mc_runner.PLATFORMS},
           **{v: k for k, v in mc_runner.PLATFORMS.items()},
           '小红书': 'xhs', '抖音': 'dy', '快手': 'ks', 'B站': 'bili',
           '微博': 'wb', '贴吧': 'tieba', '知乎': 'zhihu'}
TERMINAL = {'completed', 'failed', 'stopped', 'login_required', 'interrupted_unknown'}
FIELDS = {'platforms', 'mode', 'targets', 'targets_by_platform', 'desired_items',
          'max_api_requests', 'comments', 'replies', 'media', 'purpose',
          'authorization_ref', 'session_by_platform', 'timeout_seconds',
          'max_comments', 'headless', 'idempotency_key'}


def parse_batch(text, mode='detail'):
    """CSV platform,target (optional header), or platform<TAB>target per line."""
    if not isinstance(text, str) or len(text) > 100000 or mode not in ('detail', 'creator'):
        raise ValueError('invalid_batch')
    targets, errors = {}, []
    dialect = '\t' if '\t' in text and ',' not in text else ','
    try:
        rows = csv.reader(io.StringIO(text), delimiter=dialect, strict=True)
        for number, row in enumerate(rows, 1):
            if not row or not any(v.strip() for v in row):
                continue
            if number == 1 and [v.strip().lower() for v in row] in (['platform', 'target'], ['target'], ['url']):
                continue
            if len(row) == 1:
                target = row[0].strip()
                try:
                    host = urlsplit(target).hostname or ''
                except ValueError:
                    host = ''
                domains = {'xhs': ('xiaohongshu.com',), 'dy': ('douyin.com', 'iesdouyin.com'),
                           'ks': ('kuaishou.com', 'kuaishou.cn'), 'bili': ('bilibili.com',),
                           'wb': ('weibo.com', 'weibo.cn'), 'tieba': ('tieba.baidu.com',), 'zhihu': ('zhihu.com',)}
                platform = next((p for p, values in domains.items() if any(host == domain or host.endswith('.' + domain) for domain in values)), None)
                if platform is None:
                    errors.append({'line': number, 'error': 'platform_required_for_bare_id'})
                    continue
                row = [platform, target]
            if len(row) != 2:
                errors.append({'line': number, 'error': 'platform_and_target_required'})
                continue
            platform, target = ALIASES.get(row[0].strip()), row[1].strip()
            if platform is None:
                errors.append({'line': number, 'error': 'unsupported_platform'})
                continue
            try:
                mc_runner.validate({'platform': platform, 'mode': mode, 'targets': [target],
                                    'max_items': 1, 'purpose': 'noncommercial_research'})
            except mc_runner.BridgeError as error:
                errors.append({'line': number, 'error': str(error)})
                continue
            values = targets.setdefault(platform, [])
            if target not in values:
                values.append(target)
            if len(values) > 10:
                errors.append({'line': number, 'error': 'platform_target_limit'})
        if sum(map(len, targets.values())) > 70:
            raise ValueError('batch_target_limit')
    except csv.Error:
        errors.append({'line': getattr(rows, 'line_num', 0), 'error': 'invalid_csv'})
    return {'ok': not errors, 'mode': mode, 'platforms': list(targets),
            'targets_by_platform': targets, 'errors': errors,
            'unique_targets': sum(map(len, targets.values()))}


def _integer(payload, field, default, low, high):
    value = payload.get(field, default)
    if type(value) is not int or not low <= value <= high:
        raise ValueError('invalid_' + field)
    return value


def plan(payload):
    if not isinstance(payload, dict) or set(payload) - FIELDS:
        raise ValueError('invalid_owner_task_request')
    platforms = payload.get('platforms')
    if not isinstance(platforms, list) or not platforms or len(platforms) > 7:
        raise ValueError('invalid_platforms')
    if any(not isinstance(p, str) or p not in mc_runner.PLATFORMS for p in platforms) or len(set(platforms)) != len(platforms):
        raise ValueError('invalid_platforms')
    mode = payload.get('mode')
    if mode not in ('search', 'detail', 'creator', 'homefeed', 'trending'):
        raise ValueError('invalid_mode')
    discovery_mode = mode in ('homefeed', 'trending')
    if discovery_mode:
        from discovery import SUPPORT
        if any(p not in SUPPORT[mode] for p in platforms):
            raise ValueError('discovery_not_supported_for_platform')
        if payload.get('targets') or payload.get('targets_by_platform'):
            raise ValueError('discovery_does_not_accept_targets')
    total = _integer(payload, 'desired_items', 20, 1, 700)
    requests = _integer(payload, 'max_api_requests', 100, 1, 3500)
    sessions = payload.get('session_by_platform', {})
    if not isinstance(sessions, dict) or set(sessions) - set(platforms):
        raise ValueError('invalid_session_mapping')
    for value in sessions.values():
        try:
            mc_runner.uid(value)
        except mc_runner.BridgeError:
            raise ValueError('invalid_session_mapping')
    if discovery_mode:
        targets = {p: [] for p in platforms}
    elif mode == 'search':
        if payload.get('targets_by_platform'):
            raise ValueError('search_requires_shared_targets')
        targets = {p: payload.get('targets') for p in platforms}
    else:
        targets = payload.get('targets_by_platform')
        if payload.get('targets') or not isinstance(targets, dict) or set(targets) - set(platforms):
            raise ValueError('platform_targets_required')
    children = []
    for index, platform in enumerate(platforms):
        count = total // len(platforms) + (index < total % len(platforms))
        budget = requests // len(platforms) + (index < requests % len(platforms))
        if count > 100 or budget > 500:
            raise ValueError('per_platform_budget_limit')
        request = {k: payload[k] for k in ('comments', 'replies', 'media', 'purpose',
                    'authorization_ref', 'timeout_seconds', 'max_comments', 'headless') if k in payload}
        missing_targets = not discovery_mode and not targets.get(platform)
        unsupported_media = request.get('media') is True and platform not in mc_runner.MEDIA
        if unsupported_media:
            request['media'] = False
        placeholders = {'xhs': '0' * 24, 'dy': '1', 'ks': 'placeholder', 'bili': 'BV1234567890' if mode == 'detail' else '1', 'wb': '1', 'tieba': '1', 'zhihu': 'https://www.zhihu.com/question/1/answer/1' if mode == 'detail' else 'placeholder'}
        request.update(platform=platform, mode=mode, targets=[] if discovery_mode else targets.get(platform) or [placeholders[platform]],
                       max_items=max(count, 20 if mode == 'search' else 1),
                       max_api_requests=max(budget, 1))
        if platform in sessions:
            request['session_id'] = sessions[platform]
        try:
            request = mc_runner.validate(request)
        except mc_runner.BridgeError as error:
            raise ValueError(str(error))
        # Validate all input, but never dispatch a quota-inflated upstream request.
        request['max_items'] = count
        request['max_api_requests'] = budget
        reason = 'missing_targets' if missing_targets else 'media_not_supported_by_upstream' if unsupported_media else 'budget_not_allocated' if not count or not budget else 'upstream_search_minimum_20' if mode == 'search' and count < 20 else None
        children.append({'child_id': str(uuid.uuid4()), 'platform': platform,
                         'state': 'waiting' if reason else 'queued', 'reason_code': reason,
                         'request': request, 'item_quota': count, 'request_quota': budget,
                         'requests_spent': 0, 'requests_reserved': 0, 'runs': [],
                         'active_run_id': None, 'session_selection': 'explicit' if platform in sessions else 'auto',
                         'session_login_state': 'unverified', 'contents': 0, 'comments': 0,
                         'content_keys': [], 'comment_keys': [], 'coverage': 'unverified', 'delivery_state': 'none'})
    key = payload.get('idempotency_key')
    if not isinstance(key, str) or not 1 <= len(key) <= 160 or mc_runner.contains_secret(key):
        raise ValueError('idempotency_key_required')
    normalized = {**payload, 'platforms': platforms, 'desired_items': total, 'max_api_requests': requests}
    digest = hashlib.sha256(mc_runner.canonical(normalized).encode()).hexdigest()
    return {'request': normalized, 'request_hash': digest, 'children': children,
            'desired_items': total, 'max_api_requests': requests,
            'mode': mode, 'display_title': {'search': '多平台关键词采集', 'detail': '多平台指定内容采集', 'creator': '多平台博主采集', 'homefeed': '平台推荐内容采集', 'trending': '平台热门内容采集'}[mode],
            'storage_scope': 'local_only', 'coverage': 'unverified',
            'quantity_semantics': 'expected_entities_not_hard_source_limit',
            'request_limit_scope': 'Python httpx/requests attempts; browser resources excluded'}


class OwnerTasks:
    def __init__(self, root, runner, interval=1):
        self.root = Path(root).resolve() / 'owner-tasks'
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root / 'tasks.sqlite3'
        self.runner = runner
        self.interval = interval
        self.lock = threading.RLock()
        self.wakeup = threading.Event()
        self.closed = threading.Event()
        self.thread = None
        with self._db() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, idem TEXT UNIQUE NOT NULL, digest TEXT NOT NULL, data TEXT NOT NULL)')
            db.commit()
        os.chmod(self.path, 0o600)

    @contextlib.contextmanager
    def _db(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.execute('PRAGMA synchronous=FULL')
        try:
            yield connection
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _save(self, db, task, write_desired=False):
        if not db.in_transaction:
            db.execute('BEGIN IMMEDIATE')
        if not write_desired:
            saved = db.execute('SELECT data FROM tasks WHERE id=?', (task['task_id'],)).fetchone()
            if saved:
                task['desired_state'] = json.loads(saved[0])['desired_state']
        self._aggregate(task)
        task['updated_at'] = time.time()
        db.execute('UPDATE tasks SET data=? WHERE id=?', (mc_runner.canonical(task), task['task_id']))
        db.commit()

    def _load(self, db, task_id):
        try:
            mc_runner.uid(task_id)
        except mc_runner.BridgeError:
            raise ValueError('invalid_task_id')
        row = db.execute('SELECT data FROM tasks WHERE id=?', (task_id,)).fetchone()
        if not row:
            raise ValueError('owner_task_not_found')
        return json.loads(row[0])

    @staticmethod
    def _public(task):
        value = json.loads(mc_runner.canonical(task))
        value.pop('request', None)
        value.pop('request_hash', None)
        for child in value['children']:
            child.pop('request', None)
            child.pop('content_keys', None)
            child.pop('comment_keys', None)
        return value

    def preview(self, payload):
        proposal = plan(payload)
        return {'ok': True, **self._public({**proposal, 'task_id': None}),
                'source_actions_started': 0}

    def create(self, payload):
        proposal = plan(payload)
        with self.lock, self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT digest,data FROM tasks WHERE idem=?', (payload['idempotency_key'],)).fetchone()
            if row:
                if row[0] != proposal['request_hash']:
                    raise ValueError('idempotency_conflict')
                task = json.loads(row[1])
            else:
                task = {**proposal, 'task_id': str(uuid.uuid4()), 'created_at': time.time(),
                        'updated_at': time.time(), 'desired_state': 'running', 'state': 'queued',
                        'reason_code': None, 'source_kind': 'mediacrawler_api', 'reward_eligible': False}
                db.execute('INSERT INTO tasks VALUES (?,?,?,?)', (task['task_id'], payload['idempotency_key'],
                           task['request_hash'], mc_runner.canonical(task)))
            db.commit()
        self._ensure_thread()
        self.wakeup.set()
        return {'ok': True, 'task': self._public(task)}

    def list(self):
        with self.lock, self._db() as db:
            rows = db.execute('SELECT data FROM tasks ORDER BY rowid DESC LIMIT 200').fetchall()
        return {'ok': True, 'tasks': [self._public(json.loads(row[0])) for row in rows]}

    def status(self, task_id):
        with self.lock, self._db() as db:
            task = self._load(db, task_id)
        return {'ok': True, 'task': self._public(task)}

    def _ensure_thread(self):
        with self.lock:
            if self.thread is None and not self.closed.is_set():
                self.thread = threading.Thread(target=self._work, daemon=True, name='owner-task-scheduler')
                self.thread.start()

    def start_scheduler(self):
        """Reattach persisted tasks on dashboard start; no new tasks are created."""
        self._ensure_thread()

    def _call(self, action, payload):
        try:
            response = self.runner(action, payload)
        except Exception:
            return {'ok': False, 'error': 'runner_unavailable'}
        if not isinstance(response, dict) or response.get('ok') is False:
            return response if isinstance(response, dict) else {'ok': False, 'error': 'invalid_runner_result'}
        result = response.get('result', response)
        return result if isinstance(result, dict) else {'ok': False, 'error': 'invalid_runner_result'}

    def _control(self, task_id, desired):
        with self.lock, self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            task = self._load(db, task_id)
            task['desired_state'] = desired
            if desired == 'running':
                for child in task['children']:
                    if child['state'] in ('failed', 'stopped', 'waiting') and not child['active_run_id']:
                        if child['reason_code'] in ('source_outcome_unknown', 'dispatch_outcome_unknown', 'budget_not_allocated', 'upstream_search_minimum_20', 'missing_targets', 'media_not_supported_by_upstream', 'login_required', 'account_changed'):
                            continue
                        remaining = child['request_quota'] - child['requests_spent'] - child['requests_reserved']
                        if remaining > 0 and child['contents'] < child['item_quota']:
                            child.update(state='queued', reason_code=None)
            self._aggregate(task)
            self._save(db, task, write_desired=True)
        self._ensure_thread()
        self.wakeup.set()
        return {'ok': True, 'task': self._public(task)}

    def stop(self, task_id):
        return self._control(task_id, 'stopped')

    def resume(self, task_id):
        return self._control(task_id, 'running')

    @staticmethod
    def _aggregate(task):
        children = task['children']
        if task['desired_state'] == 'stopped':
            task['state'] = 'stopped'
            task['reason_code'] = 'user_stop'
        elif any(c['state'] in ('dispatching', 'running') for c in children):
            task['state'], task['reason_code'] = 'running', None
        elif any(c['state'] == 'queued' for c in children):
            task['state'], task['reason_code'] = 'queued', None
        elif all(c['state'] == 'completed' for c in children):
            task['state'], task['reason_code'] = 'completed', None
        elif any(c['state'] in ('waiting', 'unknown') for c in children):
            task['state'] = 'partial' if any(c['contents'] for c in children) else 'waiting'
            task['reason_code'] = next(c['reason_code'] for c in children if c['state'] in ('waiting', 'unknown'))
        else:
            task['state'] = 'partial' if any(c['contents'] for c in children) else 'failed'
            task['reason_code'] = 'incomplete_scope'
        task['contents'] = sum(c['contents'] for c in children)
        task['comments'] = sum(c['comments'] for c in children)
        task['delivery_state'] = 'local_only' if task['contents'] or task['comments'] else 'none'

    def _refresh(self, db, task, child):
        run_id = child['active_run_id']
        result = self._call('status', {'run_id': run_id})
        if result.get('ok') is False:
            child.update(state='unknown', reason_code='source_outcome_unknown')
            return
        state = result.get('state')
        child['session_login_state'] = result.get('account_state', child.get('session_login_state', 'unverified'))
        if 'account_generation' in result:
            child['account_generation'] = result['account_generation']
        if state not in TERMINAL | {'starting', 'running', 'waiting_login', 'collecting', 'comments', 'media'}:
            child.update(state='unknown', reason_code='source_outcome_unknown')
            return
        if task['desired_state'] == 'stopped' and state not in TERMINAL:
            self._call('stop', {'run_id': run_id})
        if state not in TERMINAL:
            child.update(state='waiting' if state in ('waiting_login', 'login_required') else 'running',
                         reason_code='login_required' if state == 'waiting_login' else None)
            return
        if state == 'interrupted_unknown':
            child.update(state='unknown', reason_code='source_outcome_unknown')
            return
        imported = self._call('import', {'run_id': run_id})
        if imported.get('ok') is False:
            child.update(state='unknown', reason_code='result_import_failed')
            return
        records = imported.get('records', [])
        if not isinstance(records, list):
            child.update(state='unknown', reason_code='invalid_import_result')
            return
        keys = set(child['content_keys'])
        records = [r for r in records if isinstance(r, dict) and r.get('platform') == mc_runner.PLATFORMS[child['platform']]]
        for record in records:
            if record.get('kind') in ('content', 'dynamic') and record.get('content_id') and (record.get('text') or record.get('title') or record.get('description') or record.get('body')):
                keys.add(record.get('entity_key') or record['kind'] + ':' + str(record['content_id']))
        child['content_keys'] = sorted(keys)
        child['contents'] = len(keys)
        comments = set(child.get('comment_keys', []))
        comments.update(str(r.get('content_id')) + ':' + str(r['comment_id']) for r in records if r.get('kind') == 'comment' and r.get('comment_id'))
        child['comment_keys'] = sorted(comments)
        child['comments'] = len(comments)
        attempts = result.get('api_attempts')
        used = attempts if type(attempts) is int and 0 <= attempts <= child['requests_reserved'] else child['requests_reserved']
        child['requests_spent'] += used
        child['requests_reserved'] = 0
        child['active_run_id'] = None
        child['delivery_state'] = 'local_only' if keys or child['comments'] else 'none'
        if state == 'login_required':
            child.update(state='waiting', reason_code='account_changed' if result.get('reason') == 'account_changed' else 'login_required')
        elif state == 'stopped':
            child.update(state='stopped', reason_code='user_stop')
        elif state == 'failed':
            child.update(state='failed', reason_code=result.get('reason') or 'executor_error')
        elif not keys:
            child.update(state='waiting', reason_code='no_content_observed')
        else:
            # A successful process does not prove requested quantity or source coverage.
            child.update(state='completed' if len(keys) >= child['item_quota'] else 'waiting',
                         reason_code=None if len(keys) >= child['item_quota'] else 'observed_window_partial')

    def _select_session(self, child):
        if child['runs'] or child.get('session_selection') != 'auto':
            return
        response = self._call('list', {})
        runs = response.get('runs', [])
        if not isinstance(runs, list):
            runs = []
        busy = {r.get('session_id') for r in runs if isinstance(r, dict) and r.get('state') not in ('completed', 'failed', 'stopped', 'login_required')}
        candidates = [r for r in runs if isinstance(r, dict) and r.get('platform') == child['platform']
                      and r.get('state') in ('completed', 'failed', 'stopped')
                      and r.get('session_id') not in busy]
        candidates.sort(key=lambda r: (r.get('updated_at', 0), r.get('session_id', '')), reverse=True)
        for row in candidates:
            try:
                session_id = mc_runner.uid(row.get('session_id'))
            except mc_runner.BridgeError:
                continue
            child['request']['session_id'] = session_id
            child['session_selection'] = 'auto_reused'
            return
        child['session_selection'] = 'new_isolated'

    def _recover_login(self, task, child):
        if (task['desired_state'] != 'running' or child['active_run_id'] or child['state'] != 'waiting'
                or child['reason_code'] not in ('login_required', 'account_changed')
                or not child['request'].get('session_id') or not child['runs']):
            return
        status = self._call('account_status', {'session_id': child['request']['session_id'],
                                             'platform': child['platform']})
        if status.get('ok') is False:
            return
        child['session_login_state'] = status.get('state', 'unverified')
        if (status.get('state') not in ('resumed', 'authenticated')
                or status.get('authorized_for_run') != child['runs'][-1]
                or not status.get('login_verified') or time.time() - status.get('verified_at', 0) > 180):
            return
        remaining = child['request_quota'] - child['requests_spent'] - child['requests_reserved']
        if remaining <= 0:
            child['reason_code'] = 'budget_exhausted'
            return
        child.update(state='queued', reason_code=None)
        child['account_generation'] = status.get('generation', 0)

    def poll(self):
        """One bounded scheduling pass, protected against concurrent processes."""
        with self.lock, open(self.root / 'scheduler.lock', 'a+') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return {'ok': True, 'scheduler_busy': True}
            with self._db() as db:
                tasks = [json.loads(row[0]) for row in db.execute('SELECT data FROM tasks ORDER BY rowid')]
                active = False
                for task in tasks:
                    for child in task['children']:
                        self._recover_login(task, child)
                        if child['state'] == 'dispatching' and not child['active_run_id']:
                            child.update(state='unknown', reason_code='dispatch_outcome_unknown')
                        if child['state'] == 'unknown' and child['requests_reserved']:
                            active = True
                        if child['active_run_id']:
                            self._refresh(db, task, child)
                            active = active or bool(child['active_run_id'])
                    self._aggregate(task)
                    self._save(db, task)
                if not active:
                    for task in tasks:
                        task['desired_state'] = self._load(db, task['task_id'])['desired_state']
                        if task['desired_state'] != 'running':
                            continue
                        child = next((c for c in task['children'] if c['state'] == 'queued'), None)
                        if child is None:
                            continue
                        count = child['item_quota'] - child['contents']
                        budget = child['request_quota'] - child['requests_spent'] - child['requests_reserved']
                        if budget <= 0 or count <= 0 or (child['request']['mode'] == 'search' and count < 20):
                            child.update(state='waiting', reason_code='budget_exhausted' if budget <= 0 else 'upstream_search_minimum_20' if count < 20 else 'scope_completed')
                            self._aggregate(task); self._save(db, task)
                            continue
                        self._select_session(child)
                        request = {**child['request'], 'max_items': count, 'max_api_requests': budget}
                        child.update(state='dispatching', reason_code=None, requests_reserved=budget)
                        self._aggregate(task); self._save(db, task)
                        if task['desired_state'] != 'running':
                            child.update(state='queued', requests_reserved=0)
                            self._save(db, task)
                            continue
                        result = self._call('start', request)
                        if result.get('ok') is False or not result.get('run_id'):
                            error = result.get('error', 'runner_unavailable')
                            known_not_started = error in ('session_busy', 'configure_executor_first', 'external_executor_missing', 'external_python_missing', 'headless_requires_existing_session', 'session_platform_mismatch')
                            if known_not_started:
                                child.update(state='waiting', reason_code=error, requests_reserved=0)
                            else:
                                child.update(state='unknown', reason_code='dispatch_outcome_unknown')
                        else:
                            child['active_run_id'] = result['run_id']
                            child['runs'].append(result['run_id'])
                            child.update(state='running', reason_code=None)
                        self._aggregate(task); self._save(db, task)
                        if task['desired_state'] == 'stopped' and child['active_run_id']:
                            self._call('stop', {'run_id': child['active_run_id']})
                        break
            return {'ok': True}

    def _work(self):
        while not self.closed.is_set():
            try:
                self.poll()
            except (OSError, sqlite3.Error, ValueError):
                # Leave the last durable state intact; a persisted dispatch is never replayed.
                pass
            self.wakeup.wait(self.interval)
            self.wakeup.clear()

    def close(self):
        self.closed.set()
        self.wakeup.set()
        if self.thread:
            self.thread.join(timeout=20)


def main():
    parser = argparse.ArgumentParser(description='Local durable Owner tasks; no cloud delivery implied')
    parser.add_argument('--root', required=True)
    parser.add_argument('--mc-root')
    parser.add_argument('action', choices=('preview', 'create', 'list', 'status', 'stop', 'resume', 'poll', 'serve', 'batch'))
    args = parser.parse_args()
    payload = json.load(sys.stdin) if args.action not in ('list', 'poll', 'serve') else {}

    def runner(action, request):
        if not args.mc_root:
            return {'ok': False, 'error': 'configure_executor_first'}
        command = [sys.executable, str(Path(__file__).with_name('mc_runner.py')),
                   '--root', str(Path(args.root) / 'collector'), '--mc-root', args.mc_root, action]
        try:
            response = subprocess.run(command, input=json.dumps(request), text=True,
                                      capture_output=True, timeout=15)
            if len(response.stdout.encode()) > 10 * 1024 * 1024:
                return {'ok': False, 'error': 'runner_result_too_large'}
            return json.loads(response.stdout)
        except (ValueError, subprocess.TimeoutExpired):
            return {'ok': False, 'error': 'runner_response_unknown'}

    service = OwnerTasks(args.root, runner)
    try:
        if args.action == 'serve':
            service.start_scheduler()
            while True:
                time.sleep(1)
        elif args.action == 'batch':
            result = parse_batch(payload.get('text'), payload.get('mode', 'detail'))
        elif args.action in ('preview', 'create'):
            result = getattr(service, args.action)(payload)
        elif args.action in ('status', 'stop', 'resume'):
            result = getattr(service, args.action)(payload.get('task_id'))
        else:
            result = getattr(service, args.action)()
        print(mc_runner.canonical(result))
    except (ValueError, KeyboardInterrupt) as error:
        if isinstance(error, ValueError):
            print(mc_runner.canonical({'ok': False, 'error': str(error)}))
            return 2
    finally:
        service.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
