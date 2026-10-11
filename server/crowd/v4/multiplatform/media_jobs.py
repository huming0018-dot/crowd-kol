"""Durable local processing of already downloaded task media; no network requests."""
import hashlib
import fcntl
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import threading
import time
import uuid

from mc_runner import PLATFORMS, uid, write, read

PROCESSOR = Path(__file__).resolve().parent.parent / 'postprocess' / 'evidence.py'
LONG_PROCESSOR = PROCESSOR.parent / 'long_media.py'
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
        model_ready = self.asr_model is not None and (self.asr_model / 'crowd-model.json').is_file()
        model_name = None
        if model_ready:
            try:
                manifest = self.asr_model / 'crowd-model.json'
                if manifest.stat().st_size <= 10000:
                    model_name = read(manifest).get('repository', '').rsplit('/', 1)[-1]
            except (OSError, ValueError, TypeError, AttributeError):
                model_name = None
        executable = os.environ.get('CROWD_FFMPEG') or shutil.which('ffmpeg')
        return {'ocr': sys.platform == 'darwin', 'asr': model_ready,
                'asr_model_state': 'configured_unverified' if model_ready else 'local_model_unavailable',
                'asr_model_name': model_name,
                'long_audio': True, 'ffmpeg': bool(executable and Path(executable).is_file()),
                'audio_extraction_state': 'configured_unverified' if executable else 'ffmpeg_unavailable_pcm_wav_only',
                'transcript': True, 'network': False, 'source': 'saved_task_file',
                'limits': {'bytes': 25 * 1024 * 1024, 'seconds': 3600, 'max_audio_seconds': 3600,
                           'long_audio_bytes': 64 * 1024 * 1024, 'long_audio_seconds': 7200,
                           'segment_seconds': 55, 'overlap_seconds': 2, 'concurrency': 1}}

    def status(self, job_id):
        try:
            job_id = uid(job_id)
        except Exception:
            raise ValueError('invalid_media_job_id') from None
        folder = self.root / job_id
        if folder.is_symlink() or not (folder / 'state.json').is_file():
            raise ValueError('media_job_not_found')
        with self.lock:
            state = read(folder / 'state.json')
            if state['state'] not in TERMINAL and job_id not in self.threads:
                state = {**state, 'state': 'interrupted_unknown', 'reason': 'processor_restart_check_existing_output'}
            if state['state'] == 'completed':
                state['result'] = read(folder / 'result.json')
            progress = folder / 'long-asr' / 'state.json'
            if progress.is_file():
                detail = read(progress)
                for field in ('completed_chunks', 'total_chunks', 'current_chunk'):
                    if field in detail:
                        state[field] = detail[field]
                state['processor_state'] = detail.get('state')
                if state['state'] == 'failed' and detail.get('reason'):
                    state['reason'] = detail['reason']
            state['checkpoint_available'] = state.get('kind') == 'asr' and state['state'] in ('failed', 'cancelled') and bool(list(folder.glob('input*')))
        return state

    def start(self, source, platform, content_id, kind, run_id, entity_ref=None):
        if kind not in ('ocr', 'asr', 'transcript') or platform not in PLATFORMS.values():
            raise ValueError('invalid_media_processor')
        if kind == 'asr' and not self.capabilities()['asr']:
            raise ValueError('local_asr_model_not_configured')
        source = Path(source)
        limit = 64 * 1024 * 1024 if kind == 'asr' and source.suffix.lower() in ('.m4a', '.mp3', '.aac') else 25 * 1024 * 1024
        if source.is_symlink() or not source.is_file() or source.stat().st_size > limit:
            raise ValueError('media_missing_or_over_processing_limit')
        data = source.read_bytes()
        if len(data) > limit:
            raise ValueError('media_over_processing_limit')
        digest = hashlib.sha256(data).hexdigest()
        identity = {'asset_sha256': digest, 'platform': platform, 'content_id': content_id,
                    'processing_profile': 'long_audio_64mib_7200s' if limit == 64 * 1024 * 1024 else 'standard_25mib_3600s',
                    'kind': kind, 'processor_schema': 2,
                    'processor_sha256': hashlib.sha256(PROCESSOR.read_bytes()).hexdigest(),
                    'model': str(self.asr_model) if kind == 'asr' else None}
        identity['processor_files'] = {name: hashlib.sha256((PROCESSOR.parent / name).read_bytes()).hexdigest()
            for name in ('local_asr.py', 'fetch_model.py', 'long_media.py', 'vision.swift', 'speech.swift', 'crowd-vision', 'crowd-speech')
            if (PROCESSOR.parent / name).is_file()}
        if entity_ref is not None:
            from results_store import _entity_selector
            _entity_selector(entity_ref,platform,content_id)
            identity['entity_ref']=entity_ref
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
            if entity_ref is not None:state['entity_ref']=entity_ref
            state['processor_files']=identity['processor_files']
            if kind == 'asr':
                state['model_manifest_sha256'] = identity['model_manifest_sha256']
                state['processor_files'] = identity['processor_files']
            write(folder / 'state.json', state)
            thread = threading.Thread(target=self._execute, args=(state, snapshot, process_lock), daemon=True)
            self.threads[job_id] = thread; thread.start()
            return state

    def playback(self, job_id, asset_sha256):
        try:
            job_id = uid(job_id)
        except Exception:
            raise ValueError('invalid_media_job_id') from None
        folder = self.root / job_id
        if any(parent.is_symlink() for parent in (folder, *folder.parents)) or (folder / 'state.json').is_symlink() or (folder / 'result.json').is_symlink():
            raise ValueError('media_playback_format_or_path_invalid')
        state = self.status(job_id)
        if state.get('job_id') != job_id or state.get('kind') != 'asr' or state['state'] != 'completed' or asset_sha256 != state.get('asset_sha256'):
            raise ValueError('media_playback_identity_mismatch')
        snapshots = list(folder.glob('input*'))
        if len(snapshots) != 1:
            raise ValueError('media_playback_snapshot_missing')
        path = snapshots[0]
        mimes = {'.mp4': 'video/mp4', '.webm': 'video/webm', '.wav': 'audio/wav', '.m4a': 'audio/mp4', '.mp3': 'audio/mpeg', '.aac': 'audio/aac', '.ogg': 'audio/ogg'}
        if path.suffix.lower() not in mimes or path.is_symlink() or not path.resolve().is_relative_to(folder.resolve()):
            raise ValueError('media_playback_format_or_path_invalid')
        limit = 64 * 1024 * 1024 if path.suffix.lower() in ('.m4a', '.mp3', '.aac') else 25 * 1024 * 1024
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
            data = stream.read(limit + 1)
        if len(data) > limit or hashlib.sha256(data).hexdigest() != state['asset_sha256']:
            raise ValueError('media_playback_snapshot_changed')
        return {'data': data, 'mime': mimes[path.suffix.lower()], 'sha256': state['asset_sha256']}

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
            command = [self.python, str(LONG_PROCESSOR), '--input', str(snapshot),
                       '--platform', state['platform'], '--content-id', state['content_id'],
                       '--authorization-ref', 'owner-selected-saved-media', '--output', str(result),
                       '--asr-model', str(self.asr_model), '--work-dir', str(folder / 'long-asr')]
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
            proc.wait(timeout=3600 if state['kind'] == 'asr' else 180)
            if job_id in self.cancelled:
                state.update(state='cancelled')
            elif proc.returncode != 0:
                state.update(state='failed', reason='local_media_processing_failed')
            elif result.is_symlink() or not result.is_file() or result.stat().st_nlink!=1 or result.stat().st_size > (2_000_000 if state['kind'] == 'asr' else 200000):
                state.update(state='failed', reason='invalid_media_processing_result')
            else:
                result_data=result.read_bytes()
                rows = json.loads(result_data)
                if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict) or not isinstance(rows[0].get('evidence'), dict) or rows[0].get('platform') != state['platform'] or rows[0].get('content_id') != state['content_id'] or rows[0]['evidence'].get('asset_sha256') != state['asset_sha256']:
                    state.update(state='failed', reason='media_result_identity_mismatch')
                else:
                    state.update(state='completed',result_sha256=hashlib.sha256(result_data).hexdigest())
        except subprocess.TimeoutExpired:
            self._kill(proc); state.update(state='failed', reason='local_media_processing_timeout')
        except (OSError, ValueError, TypeError):
            if proc is not None and proc.poll() is None:
                self._kill(proc)
            state.update(state='failed', reason='local_media_processor_unavailable')
        finally:
            process_lock.close()
            with self.lock:
                self.processes.pop(job_id, None)
                if job_id in self.cancelled:
                    state.update(state='cancelled')
                if state['kind'] != 'asr':
                    snapshot.unlink(missing_ok=True)
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
            (self.root / job_id / 'cancel.requested').touch(mode=0o600, exist_ok=True)
            self.cancelled.add(job_id); self._kill(self.processes.get(job_id))
        return {**state, 'cancel_requested': True}

    def resume(self, job_id):
        with self.lock:
            if self.closed:
                raise ValueError('media_processor_closed')
            state = self.status(job_id)
            if not state.get('checkpoint_available'):
                raise ValueError('media_checkpoint_not_available')
            if any(thread.is_alive() for thread in self.threads.values()):
                raise ValueError('media_processor_busy')
            if not self.capabilities()['asr']:
                raise ValueError('local_asr_model_not_configured')
            for other in self.root.iterdir():
                if other.name != job_id and other.is_dir() and not other.is_symlink() and (other / 'state.json').is_file() and self.status(other.name)['state'] == 'interrupted_unknown':
                    raise ValueError('media_processor_reconciliation_required')
            if (self.asr_model / 'crowd-model.json').stat().st_size > 10000:
                raise ValueError('invalid_local_asr_model_manifest')
            model_hash = hashlib.sha256((self.asr_model / 'crowd-model.json').read_bytes()).hexdigest()
            if model_hash != state.get('model_manifest_sha256'):
                raise ValueError('media_checkpoint_model_changed')
            current_processors = {name: hashlib.sha256((PROCESSOR.parent / name).read_bytes()).hexdigest()
                                  for name in state.get('processor_files', {}) if (PROCESSOR.parent / name).is_file()}
            if current_processors != state.get('processor_files'):
                raise ValueError('media_checkpoint_processor_changed')
            folder = self.root / job_id
            snapshots = list(folder.glob('input*'))
            limit = 64 * 1024 * 1024 if state['kind'] == 'asr' and len(snapshots) == 1 and snapshots[0].suffix.lower() in ('.m4a', '.mp3', '.aac') else 25 * 1024 * 1024
            if len(snapshots) != 1 or snapshots[0].is_symlink() or snapshots[0].stat().st_size > limit or hashlib.sha256(snapshots[0].read_bytes()).hexdigest() != state['asset_sha256']:
                raise ValueError('media_checkpoint_source_changed')
            process_lock = open(self.root / 'processor.lock', 'a+')
            try:
                fcntl.flock(process_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                process_lock.close()
                raise ValueError('media_processor_busy') from None
            (folder / 'cancel.requested').unlink(missing_ok=True)
            (folder / 'result.json').unlink(missing_ok=True)
            self.cancelled.discard(job_id)
            state = {k: v for k, v in state.items() if k not in ('result', 'reason', 'finished_at', 'processor_pid', 'checkpoint_available')}
            state.update(state='queued', resumed_at=time.time())
            write(folder / 'state.json', state)
            thread = threading.Thread(target=self._execute, args=(state, snapshots[0], process_lock), daemon=True)
            self.threads[job_id] = thread
            thread.start()
            return state

    def close(self):
        with self.lock:
            self.closed = True
            for job_id in list(self.processes):
                self.cancelled.add(job_id); self._kill(self.processes[job_id])
            threads = list(self.threads.values())
        for thread in threads:
            thread.join(timeout=6)
