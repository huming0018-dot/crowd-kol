"""Bounded local health history. Never persist raw errors, targets or credentials."""
import json
import math
import os
from pathlib import Path
import stat
import threading
import time
import uuid

PHASES = {'idle', 'claiming', 'authorized', 'dispatching', 'running', 'importing',
          'delivering', 'finishing', 'waiting_login', 'local_stop_unknown', 'state_unreadable',
          'reconciling_no_dispatch', 'completed', 'login_resumed', 'paused'}
HEALTH_ERRORS = {'scheduler_dead', 'scheduler_stale', 'cloud_lock_unavailable',
                 'cloud_scheduler_failed', 'postprocessing_enqueue_failed',
                 'postprocessing_tick_failed', 'health_observation_failed', 'health_history_unavailable',
                 'cloud_worker_failed', 'cloud_stop_persistence_failed'}
BOOLS = ('scheduler_started', 'scheduler_alive', 'scheduler_closed', 'stale')
TIMES = ('last_tick_at', 'last_success_at', 'stale_after_seconds')


def safe_snapshot(value):
    from cloud_sync import WORKER_ERRORS
    value = value if isinstance(value, dict) else {}
    phase = value.get('phase')
    snapshot = {'phase': phase if isinstance(phase, str) and phase in PHASES else 'state_unreadable'}
    for key in BOOLS:
        snapshot[key] = value.get(key) if type(value.get(key)) is bool else False
    for key in TIMES:
        number = value.get(key)
        snapshot[key] = number if type(number) in (int, float) and 0 <= number <= 1e12 and math.isfinite(number) else None
    for key in ('health_error', 'postprocessing_error', 'last_error'):
        error = value.get(key)
        snapshot[key] = error if isinstance(error, str) and error in HEALTH_ERRORS | WORKER_ERRORS else ('health_observation_failed' if error else None)
    outbox = value.get('outbox') if isinstance(value.get('outbox'), dict) else {}
    for key in ('pending', 'acknowledged'):
        number = outbox.get(key)
        snapshot[key] = number if type(number) is int and 0 <= number <= 10**9 else 0
    for key in ('task_id', 'run_id', 'local_run_id'):
        candidate = value.get(key)
        try:
            snapshot[key] = str(uuid.UUID(candidate)) if isinstance(candidate, str) else None
        except ValueError:
            snapshot[key] = None
    platform = value.get('platform')
    snapshot['platform'] = platform if isinstance(platform, str) and platform in {'xhs', 'bili', 'dy', 'ks', 'wb', 'zhihu', 'tieba'} else None
    count = value.get('waiting_login_count')
    snapshot['waiting_login_count'] = count if type(count) is int and 0 <= count <= 1000 else 0
    return snapshot


class HealthEvents:
    def __init__(self, root, *, clock=time.time, max_events=1000, retention_seconds=7*86400, workflow=False):
        self.root = Path(root) / ('workflow-events' if workflow else 'health-monitor')
        self.clock = clock
        self.max_events = max_events
        self.retention_seconds = retention_seconds
        self.lock = threading.Lock()
        self.error = None
        self.observed_at = None
        self.current = None
        self.closed = threading.Event()
        self.thread = None

    def _directory(self):
        self.root.mkdir(mode=0o700, exist_ok=True)
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            os.close(fd)
            raise OSError('private_health_directory_required')
        return fd

    def _read(self, fd):
        try:
            handle = os.open('events.jsonl', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        except FileNotFoundError:
            return []
        with os.fdopen(handle, 'r') as file:
            info = os.fstat(file.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > 2_000_000:
                raise ValueError('invalid_health_history')
            result = []
            for line in file:
                event = json.loads(line)
                timestamp = event.get('at') if isinstance(event, dict) else None
                if type(timestamp) not in (float, int) or not 0 <= timestamp <= 1e12 or not math.isfinite(timestamp):
                    raise ValueError('invalid_health_history')
                # Re-sanitize disk contents before serving or rewriting them.
                sequence = event.get('seq', len(result) + 1)
                if type(sequence) is not int or not 1 <= sequence <= 2**53-1 or (result and sequence <= result[-1]['seq']):
                    raise ValueError('invalid_health_history')
                result.append({'at': timestamp, 'seq': sequence, **safe_snapshot({**event, 'outbox': {
                    key: event.get(key) for key in ('pending', 'acknowledged')}})})
                if len(result) > self.max_events:
                    raise ValueError('invalid_health_history')
            return result

    def observe(self, value):
        snapshot = safe_snapshot(value)
        now = self.clock()
        with self.lock:
            self.current, self.observed_at = snapshot, now
            fd, temporary = None, None
            try:
                fd = self._directory()
                original = self._read(fd)
                events = [event for event in original if now-self.retention_seconds <= event['at'] <= now]
                # Tick timestamps are liveness, not a new incident every five seconds.
                compare = lambda row: {k: v for k, v in row.items() if k not in ('at', 'seq', *TIMES)}
                if not events or compare(events[-1]) != compare(snapshot):
                    sequence = original[-1]['seq'] + 1 if original else 1
                    if sequence > 2**53-1:
                        raise ValueError('invalid_health_history')
                    events.append({'at': now, 'seq': sequence, **snapshot})
                elif len(events) == len(original):
                    self.error = None
                    return
                events = events[-self.max_events:]
                temporary = 'events-' + uuid.uuid4().hex + '.tmp'
                handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
                with os.fdopen(handle, 'w') as file:
                    os.fchmod(file.fileno(), 0o600)
                    file.write(''.join(json.dumps(event, allow_nan=False) + '\n' for event in events))
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(temporary, 'events.jsonl', src_dir_fd=fd, dst_dir_fd=fd)
                self.error = None
            except (OSError, ValueError, TypeError):
                self.error = 'health_history_unavailable'
            finally:
                if fd is not None:
                    if temporary:
                        try: os.unlink(temporary, dir_fd=fd)
                        except FileNotFoundError: pass
                    os.close(fd)

    def status(self):
        with self.lock:
            fd = None
            events = []
            try:
                fd = self._directory()
                now = self.clock()
                events = [event for event in self._read(fd) if now-self.retention_seconds <= event['at'] <= now]
            except (OSError, ValueError, TypeError):
                self.error = 'health_history_unavailable'
            finally:
                if fd is not None:
                    os.close(fd)
            incidents = [event for event in events if event['health_error'] or event['postprocessing_error'] or event['last_error']
                         or event['stale'] or (event['scheduler_started'] and not event['scheduler_alive'] and not event['scheduler_closed'])]
            return {'current': self.current, 'observed_at': self.observed_at,
                    'monitor_alive': bool(self.thread and self.thread.is_alive()),
                    'monitor_error': self.error,
                    'retention_days': 7, 'max_events': self.max_events,
                    'event_count': len(events), 'incident_count': len(incidents),
                    'first_sequence': events[0]['seq'] if events else None,
                    'last_sequence': events[-1]['seq'] if events else None,
                    'truncated': bool(events and events[0]['seq'] > 1),
                    'events': list(reversed(events[-50:])),
                    'incidents': list(reversed(incidents[-50:]))}

    def start(self, source, interval=5):
        if self.thread is not None:
            return
        def loop():
            while not self.closed.is_set():
                try:
                    self.observe(source())
                except Exception:
                    self.observe({'health_error': 'health_observation_failed'})
                self.closed.wait(interval)
        self.thread = threading.Thread(target=loop, daemon=True, name='crowd-health-monitor')
        self.thread.start()

    def close(self):
        self.closed.set()
        if self.thread:
            self.thread.join(timeout=10)
