import threading
import unittest
from unittest.mock import Mock, patch

from dashboard import Application


JOB = 'bc3e6585-10e8-4d47-a433-7f38001dcb28'
HASH = 'a' * 64


class MediaCloudCallerTests(unittest.TestCase):
    def setUp(self):
        self.app = Application.__new__(Application)
        self.app.lock = threading.Lock()
        self.app.media_jobs = Mock()
        self.app.media_jobs.status.return_value = {'state': 'completed', 'kind': 'complete_video'}
        self.app.cloud_client = Mock()

    def test_lookup_is_readonly_and_can_show_unsaved_without_cloud_configuration(self):
        self.app.cloud_client = None
        with patch('media_cloud.media_video_cloud_status', return_value={'state': 'not_saved'}) as lookup:
            self.assertEqual(self.app.process_media('video_cloud_status', {'job_id': JOB}), {'state': 'not_saved'})
            lookup.assert_called_once_with(self.app.media_jobs, None, JOB)

    def test_explicit_save_initializes_private_storage_then_publishes_same_job(self):
        events = []
        self.app.cloud_client.call.side_effect = lambda action, payload: events.append((action, payload))
        with patch('media_cloud.publish_media_video', side_effect=lambda jobs, client, job: events.append(('publish', job)) or {'receipt': 'synthetic'}):
            self.assertEqual(self.app.process_media('video_cloud_save', {'job_id': JOB}), {'receipt': 'synthetic'})
        self.assertEqual(events, [('media_storage_init', {}), ('publish', JOB)])

    def test_invalid_identity_payload_and_incomplete_job_never_initialize_storage(self):
        for payload in ({'job_id': '../other'}, {'job_id': None}, {'job_id': JOB, 'upload_url': 'https://foreign.invalid/'}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.app.process_media('video_cloud_save', payload)
        for state in ({'state': 'running', 'kind': 'complete_video'}, {'state': 'completed', 'kind': 'asr'}):
            self.app.media_jobs.status.return_value = state
            with self.subTest(state=state), self.assertRaisesRegex(ValueError, 'media_cloud_not_completed'):
                self.app.process_media('video_cloud_save', {'job_id': JOB})
        self.app.cloud_client.call.assert_not_called()

    def test_download_returns_only_verified_bytes_and_refuses_wrong_expected_hash(self):
        value = {'data': b'video', 'mime': 'video/mp4', 'sha256': HASH, 'receipt': 'synthetic'}
        with patch('media_cloud.download_media_video', return_value=value) as download:
            self.assertEqual(self.app.process_media('video_cloud_file', {'job_id': JOB, 'asset_sha256': HASH}), value)
            download.assert_called_once_with(self.app.media_jobs, self.app.cloud_client, JOB)
            with self.assertRaisesRegex(ValueError, 'media_cloud_download_mismatch'):
                self.app.process_media('video_cloud_file', {'job_id': JOB, 'asset_sha256': 'b' * 64})

    def test_save_and_download_require_original_cloud_configuration(self):
        self.app.cloud_client = None
        for action, payload in (('video_cloud_save', {'job_id': JOB}), ('video_cloud_file', {'job_id': JOB, 'asset_sha256': HASH})):
            with self.subTest(action=action), self.assertRaisesRegex(ValueError, 'cloud_configuration_required'):
                self.app.process_media(action, payload)


if __name__ == '__main__':
    unittest.main()
