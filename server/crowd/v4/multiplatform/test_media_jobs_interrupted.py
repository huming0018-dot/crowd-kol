"""Owned cancelled checkpoints; no source, model calls or production writes."""
import fcntl
import hashlib
import json
import os
import unittest
import wave
from unittest.mock import patch

import media_jobs
import test_native_video_asr as fixtures


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


class InterruptedCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.NativeVideoAsrTests();self.fixture.setUp()
        self.fixture.grow(26 * 1024 * 1024)
        self.manager = self.fixture.manager
        self.state = self.fixture.start();self.job_id = self.state['job_id']
        self.folder = self.manager.root / self.job_id
        self.state.update(state='running', processor_pid=424242)
        media_jobs.write(self.folder / 'state.json', self.state)
        (self.folder / 'result.json').unlink()
        self.work = self.folder / 'long-asr';self.work.mkdir()
        (self.work / 'active.lock').touch()
        rows = []
        for index in range(3):
            start = index * 53;end = min(110, start + 55)
            audio = self.work / ('chunk-%04d.wav' % index)
            with wave.open(str(audio), 'wb') as stream:
                stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(16000)
                stream.writeframes(b'\0\0' * ((end - start) * 16000))
            rows.append({'index': index, 'start': start, 'end': end, 'file': audio.name, 'sha256': sha(audio)})
            if index < 2:
                processors = ''.join(self.state['processor_files'][name] for name in ('long_media.py', 'local_asr.py', 'fetch_model.py'))
                key = hashlib.sha256((sha(audio) + self.state['model_manifest_sha256'] + processors + '1').encode()).hexdigest()
                media_jobs.write(self.work / ('result-%04d.json' % index), {'segments': [{'start': 0, 'end': 1, 'text': 'owned synthetic checkpoint'}],
                    'input_hash': key, 'timing_adjustments': [], 'segment_metrics': [None]})
        media_jobs.write(self.work / 'chunks.json', {'schema': 1, 'asset_sha256': self.state['asset_sha256'],
            'duration_seconds': 110, 'segment_seconds': 55, 'overlap_seconds': 2, 'chunks': rows})
        self.detail = {'state': 'cancelled', 'reason': 'long_media_cancelled', 'completed_chunks': 2, 'total_chunks': 3, 'current_chunk': 1}
        media_jobs.write(self.work / 'state.json', self.detail)
        self.gone = patch.object(media_jobs.os, 'kill', side_effect=ProcessLookupError())
        self.gone.start()

    def tearDown(self):
        self.gone.stop();self.fixture.tearDown()

    def status(self):return self.manager.status(self.job_id)

    def test_readonly_status_known_cancelled_checkpoint_and_same_job_resume_history(self):
        protected = [self.folder / 'state.json', self.folder / 'input.mp4', self.work / 'state.json', self.work / 'chunks.json',
                     self.work / 'result-0000.json', self.work / 'result-0001.json']
        before = {str(path): sha(path) for path in protected}
        value = self.status()
        self.assertEqual(value['state'], 'failed');self.assertTrue(value['checkpoint_available'])
        self.assertEqual(value['reason'], 'processor_interrupted_with_cancelled_checkpoint')
        self.assertEqual(before, {str(path): sha(path) for path in protected})
        with patch.object(self.manager, '_execute', side_effect=self.fixture.complete):
            resumed = self.manager.resume(self.job_id)
            self.manager.threads[self.job_id].join(3)
        self.assertEqual(resumed['job_id'], self.job_id)
        history = self.status()['recovery_history']
        self.assertEqual(len(history), 1);self.assertEqual(history[0]['trigger_actor'], 'unknown')
        self.assertEqual(history[0]['parent_state_sha256'], before[str(self.folder / 'state.json')])
        backup = self.folder / history[0]['parent_backup']
        self.assertEqual(sha(backup), before[str(self.folder / 'state.json')]);self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        self.assertEqual(history[0]['cache_sha256'], [before[str(self.work / ('result-%04d.json' % index))] for index in range(2)])
        for path in protected[1:]:self.assertEqual(sha(path), before[str(path)])

    def test_live_or_unverifiable_pid_and_owned_thread_stay_unknown(self):
        for effect in (None, PermissionError()):
            with self.subTest(effect=effect), patch.object(media_jobs.os, 'kill', side_effect=effect):
                self.assertEqual(self.status()['state'], 'interrupted_unknown')
                with self.assertRaisesRegex(ValueError, 'media_checkpoint_not_available'):self.manager.resume(self.job_id)
        with patch.object(self.manager.threads[self.job_id], 'is_alive', return_value=True):
            self.assertEqual(self.status()['state'], 'running')
            self.assertFalse(self.status()['checkpoint_available'])

    def test_both_locks_block_recovery_and_symlink_or_hardlink_lock_rejected(self):
        for path in (self.manager.root / 'processor.lock', self.work / 'active.lock'):
            with path.open('rb') as stream:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.assertEqual(self.status()['state'], 'interrupted_unknown')
        outside = self.fixture.root / 'owned-lock';outside.touch()
        path = self.work / 'active.lock';path.unlink();path.symlink_to(outside)
        self.assertEqual(self.status()['state'], 'interrupted_unknown')
        path.unlink();os.link(outside, path)
        self.assertEqual(self.status()['state'], 'interrupted_unknown')

    def test_unknown_reason_bad_progress_and_non_native_are_not_recovered(self):
        for change in ({'state': 'failed'}, {'reason': 'private_error_do_not_publish'}, {'completed_chunks': True}, {'completed_chunks': 1}, {'total_chunks': 2}, {'current_chunk': 9}):
            with self.subTest(change=change):
                media_jobs.write(self.work / 'state.json', {**self.detail, **change})
                self.assertEqual(self.status()['state'], 'interrupted_unknown')
        media_jobs.write(self.work / 'state.json', self.detail)
        for change in ({'processing_profile': 'standard_25mib_3600s'}, {'kind': 'ocr'}, {'processor_pid': True}):
            media_jobs.write(self.folder / 'state.json', {**self.state, **change})
            self.assertEqual(self.status()['state'], 'interrupted_unknown')

    def test_result_unknown_or_changed_snapshot_cache_and_audio_refuse(self):
        result = self.folder / 'result.json';result.write_text('[]')
        self.assertEqual(self.status()['state'], 'interrupted_unknown');result.unlink()
        result.symlink_to(self.folder / 'not-created')
        self.assertEqual(self.status()['state'], 'interrupted_unknown');result.unlink()
        for path in (self.folder / 'input.mp4', self.work / 'chunk-0002.wav', self.work / 'result-0000.json'):
            data = path.read_bytes();path.write_bytes(data + b'changed')
            self.assertEqual(self.status()['state'], 'interrupted_unknown')
            path.write_bytes(data)
        context = self.folder / 'native-asr-context.json';value = json.loads(context.read_text())
        media_jobs.write(context, {**value, 'content_id': 'OTHER'})
        self.assertEqual(self.status()['state'], 'interrupted_unknown')

    def test_resume_rechecks_evidence_under_lock_before_any_dispatch(self):
        before = sha(self.folder / 'state.json');original = self.manager._cancelled_checkpoint
        def changed(folder, state, process_lock_held=False):
            if process_lock_held:
                cache = self.work / 'result-0000.json';value = json.loads(cache.read_text())
                value['segments'][0]['text'] = 'different owned synthetic text';media_jobs.write(cache, value)
            return original(folder, state, process_lock_held)
        with patch.object(self.manager, '_cancelled_checkpoint', side_effect=changed), patch.object(self.manager, '_execute') as execute:
            with self.assertRaisesRegex(ValueError, 'media_interrupted_checkpoint_not_verified'):self.manager.resume(self.job_id)
            execute.assert_not_called()
        self.assertEqual(sha(self.folder / 'state.json'), before)
        with (self.manager.root / 'processor.lock').open('rb') as stream:fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_unsafe_backup_does_not_change_parent_or_dispatch_and_releases_lock(self):
        parent = self.folder / 'state.json';before = sha(parent)
        outside = self.fixture.root / 'owned-prior-state';outside.write_bytes(parent.read_bytes())
        os.link(outside, self.folder / ('recovery-parent-' + before + '.json'))
        with patch.object(self.manager, '_execute') as execute:
            with self.assertRaisesRegex(ValueError, 'media_interrupted_checkpoint_not_verified'):self.manager.resume(self.job_id)
            execute.assert_not_called()
        self.assertEqual(sha(parent), before);self.assertEqual(sha(outside), before)
        with (self.manager.root / 'processor.lock').open('rb') as stream:fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


if __name__ == '__main__':unittest.main()
