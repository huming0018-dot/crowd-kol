"""Versioned analysis of saved text through the already installed Codex CLI."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid

from analysis_contract import build_snapshot, make_prompt, validate_result, MODEL_SCHEMA
from mc_runner import BridgeError, canonical, read, uid, write

PROMPT_VERSION = 'content-comments-v1'
TIMEOUT_SECONDS = 180


class AnalysisJobs:
    def __init__(self, root, executable=None):
        self.root = Path(root).resolve() / 'analysis'
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.executable = executable or shutil.which('codex')
        self.mutex = threading.RLock()
        self.running = {}
        self.closed = False
        self.provider_version = 'unavailable'
        if self.executable:
            try:
                value = subprocess.run([self.executable, '--version'], capture_output=True,
                                       timeout=5, check=True)
                self.provider_version = value.stdout[:200].decode().strip()
            except (OSError, subprocess.SubprocessError, UnicodeError):
                self.executable = None

    def folder(self, job_id):
        try:
            folder = self.root / uid(job_id)
        except BridgeError:
            raise ValueError('invalid_analysis_job_id') from None
        if folder.is_symlink() or not folder.is_dir():
            raise ValueError('analysis_not_found')
        return folder

    def status(self, job_id):
        folder = self.folder(job_id)
        with self.mutex:
            # Pair the durable snapshot with ownership. The worker writes its terminal
            # state before removing ownership; reading outside this lock could combine
            # an old running snapshot with a newly removed record and report unknown.
            state = read(folder / 'state.json')
            if state['state'] in ('queued', 'running') and job_id not in self.running:
                # A restarted UI never repeats a possibly billed request automatically.
                state = {**state, 'state': 'interrupted_unknown', 'error': 'analysis_interrupted_check_before_retry'}
            if state['state'] == 'completed':
                state['result'] = read(folder / 'result.json')
        return {'ok': True, **state}

    def start(self, imported, platform, content_id):
        snapshot = build_snapshot(imported, platform, content_id)
        if not self.executable:
            raise ValueError('analysis_provider_missing')
        cache_key = hashlib.sha256(canonical({
            'snapshot': snapshot['snapshot_hash'], 'prompt': PROMPT_VERSION,
            'provider_version': self.provider_version,
        }).encode()).hexdigest()
        with self.mutex:
            if self.closed:
                raise ValueError('analysis_service_closed')
            for folder in self.root.iterdir():
                if not folder.is_dir() or folder.is_symlink() or not (folder / 'state.json').is_file():
                    continue
                state = read(folder / 'state.json')
                if state.get('cache_key') == cache_key and state.get('state') == 'completed':
                    return {**self.status(state['job_id']), 'cached': True}
                if state.get('state') in ('queued', 'running'):
                    pid = state.get('provider_pid')
                    if state['job_id'] in self.running or self._alive(pid):
                        raise ValueError('analysis_busy')
            lock = (self.root / 'active.lock').open('a+')
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                lock.close()
                raise ValueError('analysis_busy')
            job_id = str(uuid.uuid4())
            folder = self.root / job_id
            try:
                folder.mkdir(mode=0o700)
                write(folder / 'snapshot.json', snapshot)
                write(folder / 'schema.json', MODEL_SCHEMA)
                state = {'job_id': job_id, 'state': 'queued', 'cache_key': cache_key,
                         'snapshot_hash': snapshot['snapshot_hash'], 'run_id': imported.get('run_id'),
                         'platform': platform, 'content_id': content_id,
                         'prompt_version': PROMPT_VERSION, 'provider': 'codex_cli',
                         'provider_version': self.provider_version, 'created_at': time.time(),
                         'review_status': 'unreviewed_model_analysis'}
                write(folder / 'state.json', state)
                record = {'cancel': threading.Event(), 'process': None}
                self.running[job_id] = record
                thread = threading.Thread(target=self._work, args=(folder, state, snapshot, lock, record), daemon=True)
                record['thread'] = thread
                thread.start()
            except BaseException:
                self.running.pop(job_id, None)
                lock.close()
                raise
            return {'ok': True, **state, 'cached': False}

    @staticmethod
    def _alive(pid):
        if type(pid) is not int or pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    @staticmethod
    def _terminate(process):
        if process and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            except ProcessLookupError:
                pass

    def command(self, folder):
        command = [self.executable, '-a', 'never', 'exec', '--sandbox', 'read-only',
                   '--ephemeral', '--ignore-user-config', '--skip-git-repo-check',
                   '--enable', 'skip_host_skill_discovery', '-c', 'project_doc_max_bytes=0',
                   '-c', 'web_search="disabled"', '--output-schema', str(folder / 'schema.json'),
                   '--output-last-message', str(folder / 'model-output.json'), '--json', '--color', 'never']
        for feature in ('shell_tool', 'apps', 'plugins', 'hooks', 'memories', 'multi_agent',
                        'browser_use', 'computer_use', 'image_generation', 'code_mode_host',
                        'view_image', 'sleep_tool', 'workspace_dependencies'):
            command.extend(['--disable', feature])
        return command + ['-']

    def _work(self, folder, state, snapshot, lock, record):
        process = None
        try:
            # Existing auth is handled by Codex; this process never opens credential files.
            for name in ('model-output.json', 'events.jsonl'):
                with os.fdopen(os.open(folder / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'w'):
                    pass
            with (folder / 'events.jsonl').open('wb') as events:
                with self.mutex:
                    if record['cancel'].is_set():
                        raise ValueError('analysis_cancelled')
                    process = subprocess.Popen(self.command(folder), cwd=folder, stdin=subprocess.PIPE,
                                               stdout=events, stderr=subprocess.PIPE,
                                               start_new_session=True, pass_fds=(lock.fileno(),))
                    record['process'] = process
                    state.update(state='running', provider_pid=process.pid, started_at=time.time())
                    write(folder / 'state.json', state)
                try:
                    _, diagnostic = process.communicate(make_prompt(snapshot).encode(), timeout=TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired:
                    self._terminate(process)
                    raise ValueError('analysis_timeout')
            if record['cancel'].is_set():
                raise ValueError('analysis_cancelled')
            if process.returncode:
                state['provider_returncode'] = process.returncode
                raise ValueError(self._failure_code(diagnostic))
            if (folder / 'model-output.json').stat().st_size > 512 * 1024 or (folder / 'events.jsonl').stat().st_size > 2 * 1024 * 1024:
                raise ValueError('analysis_output_limit')
            # No agent tool results are accepted as analysis. All numeric results are local.
            for line in (folder / 'events.jsonl').read_text().splitlines():
                event = json.loads(line)
                item = event.get('item', {})
                if item and item.get('type') not in ('agent_message', 'reasoning'):
                    raise ValueError('analysis_unexpected_tool_event')
            value = read(folder / 'model-output.json')
            result = validate_result(snapshot, value)
            result.update(snapshot_hash=snapshot['snapshot_hash'], prompt_version=PROMPT_VERSION,
                          provider='codex_cli', provider_version=self.provider_version,
                          input_snapshot=snapshot)
            with self.mutex:
                if record['cancel'].is_set():
                    raise ValueError('analysis_cancelled')
                write(folder / 'result.json', result)
                state.update(state='completed', completed_at=time.time())
        except (ValueError, OSError, subprocess.SubprocessError, TypeError, KeyError) as error:
            self._terminate(process)
            state.update(state='cancelled' if record['cancel'].is_set() else 'failed',
                         error=str(error) if type(error) is ValueError and str(error).replace('_', '').isalnum()
                         else 'analysis_invalid_result', completed_at=time.time())
        finally:
            try:
                if process is not None:
                    for stream in (process.stdin, process.stdout, process.stderr):
                        if stream is not None and not stream.closed:
                            stream.close()
                for name in ('model-output.json', 'events.jsonl'):
                    (folder / name).unlink(missing_ok=True)
                # Publish a terminal state only after private intermediate files are removed.
                write(folder / 'state.json', state)
            finally:
                with self.mutex:
                    self.running.pop(state['job_id'], None)
                lock.close()

    @staticmethod
    def _failure_code(diagnostic):
        # Classify in memory; never expose a raw provider message or credential in logs.
        text = diagnostic[:65536].decode('utf8', errors='replace').lower()
        for code, words in (
            ('analysis_environment_denied', ('operation not permitted', 'permission denied')),
            ('analysis_login_required', ('unauthorized', 'authentication required', '401 unauthorized')),
            ('analysis_quota_exceeded', ('quota exceeded', 'rate limit', '429 too many')),
            ('analysis_network_unavailable', ('error sending request', 'failed to connect', 'connection refused', 'stream disconnected')),
            ('analysis_provider_incompatible', ('unknown feature', 'unrecognized', 'invalid schema')),
        ):
            if any(word in text for word in words):
                return code
        return 'analysis_provider_failed'

    def cancel(self, job_id):
        self.folder(job_id)
        with self.mutex:
            record = self.running.get(job_id)
            if record:
                record['cancel'].set()
                process = record['process']
            else:
                process = None
        self._terminate(process)
        return self.status(job_id)

    def close(self):
        with self.mutex:
            self.closed = True
            records = list(self.running.values())
            for record in records:
                record['cancel'].set()
        for record in records:
            self._terminate(record['process'])
        for record in records:
            record['thread'].join(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--platform', required=True)
    parser.add_argument('--content-id', required=True)
    parser.add_argument('--allow-model-transfer', action='store_true')
    args = parser.parse_args()
    if not args.allow_model_transfer:
        parser.error('analysis_transfer_authorization_required')
    manager = AnalysisJobs(args.root)
    try:
        job = manager.start(read(args.input), args.platform, args.content_id)
        while job['state'] in ('queued', 'running'):
            time.sleep(0.5)
            job = manager.status(job['job_id'])
        print(json.dumps(job, ensure_ascii=False))
    finally:
        manager.close()


if __name__ == '__main__':
    main()
