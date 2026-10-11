"""Durable local processing of already downloaded task media; no network requests."""
import hashlib
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import uuid

from mc_runner import PLATFORMS, uid, write, read

PROCESSOR = Path(__file__).resolve().parent.parent / 'postprocess' / 'evidence.py'
TERMINAL = {'completed', 'failed', 'cancelled', 'interrupted_unknown'}


class MediaJobs:
    def __init__(self, root, asr_model=None, python=None):
        self.root = Path(root).resolve() / 'media-processing'
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.asr_model = Path(asr_model).resolve() if asr_model else None
        self.python = python or sys.executable
        self.lock = threading.RLock()
        self.processes = {}
        self.threads = {}
        self.cancelled = set()
        self.closed = False

    def capabilities(self):
        return {'ocr': sys.platform == 'darwin', 'asr': self.asr_model is not None and (self.asr_model / 'crowd-model.json').is_file(),
                'transcript': True, 'network': False, 'source': 'saved_task_file',
                'limits': {'bytes': 25 * 1024 * 1024, 'seconds': 180, 'max_audio_seconds': 60, 'concurrency': 1}}

    def status(self, job_id):
        try:
            job_id = uid(job_id)
        except Exception:
            raise ValueError('invalid_media_job_id') from None
        folder = self.root / job_id
        if folder.is_symlink() or not (folder / 'state.json').is_file():
            raise ValueError('media_job_not_found')
        state = read(folder / 'state.json')
        with self.lock:
            if state['state'] not in TERMINAL and job_id not in self.threads:
                state = {**state, 'state': 'interrupted_unknown', 'reason': 'processor_restart_check_existing_output'}
        if state['state'] == 'completed':
            state['result'] = read(folder / 'result.json')
        return state

    def start(self, source, platform, content_id, kind, run_id):
        if kind not in ('ocr', 'asr', 'transcript') or platform not in PLATFORMS.values():
            raise ValueError('invalid_media_processor')
        if kind == 'asr' and not self.capabilities()['asr']:
            raise ValueError('local_asr_model_not_configured')
        source = Path(source)
        if source.is_symlink() or not source.is_file() or source.stat().st_size > 25 * 1024 * 1024:
            raise ValueError('media_missing_or_over_25mb')
        data = source.read_bytes()
        if len(data) > 25 * 1024 * 1024:
            raise ValueError('media_over_25mb')
        digest = hashlib.sha256(data).hexdigest()
        identity = {'asset_sha256': digest, 'platform': platform, 'content_id': content_id,
                    'kind': kind, 'processor_schema': 1,
                    'processor_sha256': hashlib.sha256(PROCESSOR.read_bytes()).hexdigest(),
                    'model': str(self.asr_model) if kind == 'asr' else None}
        identity['processor_files'] = {name: hashlib.sha256((PROCESSOR.parent / name).read_bytes()).hexdigest()
            for name in ('local_asr.py', 'vision.swift', 'speech.swift', 'crowd-vision', 'crowd-speech')
            if (PROCESSOR.parent / name).is_file()}
        if kind == 'asr':
            manifest = self.asr_model / 'crowd-model.json'
            if manifest.stat().st_size > 10000:
                raise ValueError('invalid_local_asr_model_manifest')
            identity['model_manifest_sha256'] = hashlib.sha256(manifest.read_bytes()).hexdigest()
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        with self.lock:
            if self.closed:
                raise ValueError('media_processor_closed')
            unknown = False
            for folder in self.root.iterdir():
                if folder.is_dir() and not folder.is_symlink() and (folder / 'state.json').is_file():
                    state = self.status(folder.name)
                    if state.get('input_hash') == key and state['state'] not in ('failed', 'cancelled'):
                        return {**state, 'cached': state['state'] == 'completed', 'reused_existing_job': True}
                    unknown = unknown or state['state'] == 'interrupted_unknown'
            if unknown:
                raise ValueError('media_processor_reconciliation_required')
            if any(thread.is_alive() for thread in self.threads.values()):
                raise ValueError('media_processor_busy')
            process_lock = open(self.root / 'processor.lock', 'a+')
            try:
                fcntl.flock(process_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                process_lock.close()
                raise ValueError('media_processor_busy') from None
            job_id = str(uuid.uuid4()); folder = self.root / job_id
            folder.mkdir(mode=0o700)
            snapshot = folder / ('input' + source.suffix.lower())
            with os.fdopen(os.open(snapshot, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as stream:
                stream.write(data)
            state = {'job_id': job_id, 'state': 'queued', 'input_hash': key, 'asset_sha256': digest,
                     'platform': platform, 'content_id': content_id, 'kind': kind, 'run_id': run_id,
                     'association': 'owner_selected_content', 'created_at': time.time(),
                     'source_kind': 'authorized_local_file', 'review_status': 'unreviewed', 'uploaded': False}
            write(folder / 'state.json', state)
            thread = threading.Thread(target=self._execute, args=(state, snapshot, process_lock), daemon=True)
            self.threads[job_id] = thread; thread.start()
            return state

    def list(self, run_id):
        try:
            uid(run_id)
        except Exception:
            raise ValueError('invalid_media_run_id') from None
        jobs = [self.status(p.name) for p in self.root.iterdir()
                if p.is_dir() and not p.is_symlink() and (p / 'state.json').is_file()]
        return {'jobs': sorted((s for s in jobs if s['run_id'] == run_id), key=lambda s: s['created_at'], reverse=True)[:100]}

    def _execute(self, state, snapshot, process_lock):
        folder = snapshot.parent; job_id = state['job_id']; result = folder / 'result.json'
        command = [self.python, str(PROCESSOR), '--kind', state['kind'], '--input', str(snapshot),
                   '--platform', state['platform'], '--content-id', state['content_id'],
                   '--authorization-ref', 'owner-selected-saved-media', '--output', str(result)]
        if state['kind'] == 'asr':
            command += ['--asr-model', str(self.asr_model)]
        proc = None
        try:
            with self.lock:
                if job_id in self.cancelled or self.closed:
                    state.update(state='cancelled'); return
                proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, start_new_session=True,
                                        pass_fds=(process_lock.fileno(),))
                self.processes[job_id] = proc
                state['processor_pid'] = proc.pid
            write(folder / 'state.json', {**state, 'state': 'running'})
            proc.wait(timeout=180)
            if job_id in self.cancelled:
                state.update(state='cancelled')
            elif proc.returncode != 0:
                state.update(state='failed', reason='local_media_processing_failed')
            elif not result.is_file() or result.stat().st_size > 200000:
                state.update(state='failed', reason='invalid_media_processing_result')
            else:
                rows = read(result)
                if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict) or not isinstance(rows[0].get('evidence'), dict) or rows[0].get('platform') != state['platform'] or rows[0].get('content_id') != state['content_id'] or rows[0]['evidence'].get('asset_sha256') != state['asset_sha256']:
                    state.update(state='failed', reason='media_result_identity_mismatch')
                else:
                    state.update(state='completed')
        except subprocess.TimeoutExpired:
            self._kill(proc); state.update(state='failed', reason='local_media_processing_timeout')
        except (OSError, ValueError, TypeError):
            if proc is not None and proc.poll() is None:
                self._kill(proc)
            state.update(state='failed', reason='local_media_processor_unavailable')
        finally:
            snapshot.unlink(missing_ok=True)
            process_lock.close()
            with self.lock:
                self.processes.pop(job_id, None)
                if job_id in self.cancelled:
                    state.update(state='cancelled')
                write(folder / 'state.json', {**state, 'finished_at': time.time()})

    @staticmethod
    def _kill(proc):
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=5)

    def cancel(self, job_id):
        state = self.status(job_id)
        with self.lock:
            if state['state'] in TERMINAL:
                return state
            self.cancelled.add(job_id); self._kill(self.processes.get(job_id))
        return {**state, 'cancel_requested': True}

    def close(self):
        with self.lock:
            self.closed = True
            for job_id in list(self.processes):
                self.cancelled.add(job_id); self._kill(self.processes[job_id])
            threads = list(self.threads.values())
        for thread in threads:
            thread.join(timeout=6)
