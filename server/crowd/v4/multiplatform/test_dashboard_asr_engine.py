"""Exercise the real dashboard routing, without source/model/cloud requests."""
from pathlib import Path
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import Mock

from dashboard import Application


class Tests(unittest.TestCase):
    def setUp(self):
        self.app = Application.__new__(Application)
        self.app.lock = threading.Lock()
        self.app.media_jobs = SimpleNamespace(
            capabilities=lambda: {'asr_engines': ['cpu', 'mlx', 'mlx_fast']},
            start=Mock(return_value={'state': 'queued'}),
            preview=Mock(return_value={'native_video_verified': True}))
        self.app._registered_run_root = lambda _: Path('/test-root')
        self.app.media_file = Mock(return_value=Path('/test-root/audio.m4a'))
        self.app.run = Mock(return_value={'records': [{'kind': 'content', 'platform': 'bilibili', 'content_id': '123'}], 'media': []})
        self.payload = {'run_id': 'test-run', 'path': 'audio.m4a', 'content_id': '123', 'kind': 'asr'}

    def test_explicit_engine_forwarded_and_default_keeps_original_signature(self):
        self.app.process_media('start', {**self.payload, 'asr_engine': 'mlx'})
        self.assertEqual(self.app.media_jobs.start.call_args.kwargs['asr_engine'], 'mlx')
        self.app.process_media('start', {**self.payload, 'asr_engine': 'mlx_fast'})
        self.assertEqual(self.app.media_jobs.start.call_args.kwargs['asr_engine'], 'mlx_fast')
        self.app.process_media('start', self.payload)
        self.assertNotIn('asr_engine', self.app.media_jobs.start.call_args.kwargs)

    def test_preview_checks_availability_without_changing_source_preview(self):
        self.app.process_media('preview', {**self.payload, 'asr_engine': 'mlx'})
        self.assertNotIn('asr_engine', self.app.media_jobs.preview.call_args.kwargs)
        self.app.media_jobs.capabilities = lambda: {'asr_engines': ['cpu']}
        with self.assertRaisesRegex(ValueError, 'mac_asr_engine_not_configured'):
            self.app.process_media('start', {**self.payload, 'asr_engine': 'mlx'})

    def test_invalid_or_non_asr_engine_rejected_before_source_read(self):
        for delta in ({'asr_engine': 'remote'}, {'asr_engine': True}, {'kind': 'ocr', 'asr_engine': 'mlx'}):
            with self.subTest(delta=delta), self.assertRaisesRegex(ValueError, 'invalid_asr_engine'):
                self.app.process_media('start', {**self.payload, **delta})
        self.app.media_file.assert_not_called()


if __name__ == '__main__':
    unittest.main()
