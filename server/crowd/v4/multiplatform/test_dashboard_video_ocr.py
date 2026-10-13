"""Bind local OCR to registered runs; never accept caller provenance or paths."""
import tempfile
import unittest
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import dashboard
from workbench_cli import ROUTES


class VideoOCRDispatch(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app = dashboard.Application(self.root / 'runtime')
        self.start = Mock(return_value={'state': 'queued', 'kind': 'video_ocr'})
        self.app.media_jobs = SimpleNamespace(start_video_ocr=self.start)
        self.run = '00000000-0000-4000-8000-000000000001'
        self.source = '00000000-0000-4000-8000-000000000002'

    def tearDown(self):
        self.app.watchlists.close()
        self.app.owner_tasks.close()
        self.temp.cleanup()

    def test_registered_run_only(self):
        with patch.object(self.app, '_registered_run_root', return_value=self.root / 'runner') as registered:
            value = self.app.process_media('video_ocr_start', {'run_id': self.run, 'source_job_id': self.source})
        registered.assert_called_once_with(self.run)
        self.start.assert_called_once_with(self.source, self.root / 'runner' / 'runs' / self.run)
        self.assertEqual(value['kind'], 'video_ocr')

    def test_unregistered_no_start(self):
        with patch.object(self.app, '_registered_run_root', side_effect=ValueError('run_not_registered')):
            with self.assertRaisesRegex(ValueError, 'run_not_registered'):
                self.app.process_media('video_ocr_start', {'run_id': self.run, 'source_job_id': self.source})
        self.start.assert_not_called()

    def test_no_caller_paths_or_provenance(self):
        base = {'run_id': self.run, 'source_job_id': self.source}
        for payload in [{}, base | {'path': '/tmp/source.mp4'}, base | {'source_record_sha256': 'a' * 64}, base | {'crop_top': 0}]:
            with self.assertRaisesRegex(ValueError, 'invalid_video_ocr_request'):
                self.app.process_media('video_ocr_start', payload)
        self.start.assert_not_called()

    def test_cli_route(self):
        self.assertIn('video_ocr_start', ROUTES['media-processing'])

    def test_retry_is_explicit_boolean(self):
        with patch.object(self.app, '_registered_run_root', return_value=self.root / 'runner'):
            self.app.process_media('video_ocr_start', {'run_id': self.run, 'source_job_id': self.source, 'retry': True})
        self.start.assert_called_once_with(self.source, self.root / 'runner' / 'runs' / self.run, retry=True)
        self.start.reset_mock()
        for retry in (1, 'true', None, {}):
            with self.assertRaisesRegex(ValueError, 'invalid_video_ocr_request'):
                self.app.process_media('video_ocr_start', {'run_id': self.run, 'source_job_id': self.source, 'retry': retry})
        self.start.assert_not_called()

    def test_only_bounded_region_presets(self):
        with patch.object(self.app, '_registered_run_root', return_value=self.root / 'runner'):
            self.app.process_media('video_ocr_start', {'run_id': self.run, 'source_job_id': self.source, 'text_region': 'top'})
        self.start.assert_called_once_with(self.source, self.root / 'runner' / 'runs' / self.run, crop_top=.12, crop_bottom=.32)
        self.start.reset_mock()
        for region in ([], {}, 'custom', '../', 0):
            with self.assertRaisesRegex(ValueError, 'invalid_video_ocr_region'):
                self.app.process_media('video_ocr_start', {'run_id': self.run, 'source_job_id': self.source, 'text_region': region})
        self.start.assert_not_called()

    def test_saved_mp4_candidate_is_not_promised_source_validation(self):
        from media_jobs import MediaJobs
        jobs = MediaJobs(self.root / 'candidate')
        job = str(uuid.uuid4())
        folder = jobs.root / job
        folder.mkdir()
        state = {'job_id': job, 'run_id': self.run, 'kind': 'asr', 'state': 'completed'}
        (folder / 'state.json').write_text(json.dumps(state))
        (folder / 'result.json').write_text('[]')
        (folder / 'input.mp4').write_bytes(b'fixture-only-not-validated-media')
        self.assertTrue(jobs.status(job)['video_ocr_candidate'])
        (folder / 'input.mp4').unlink()
        self.assertFalse(jobs.status(job)['video_ocr_candidate'])
        (folder / 'input.mp4').symlink_to(folder / 'result.json')
        self.assertFalse(jobs.status(job)['video_ocr_candidate'])
        jobs.close()
