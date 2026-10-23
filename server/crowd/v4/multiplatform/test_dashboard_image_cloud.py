import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch
from dashboard import Application


class ImageDashboard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.app = Application.__new__(Application)
        self.app.root = Path(self.tmp.name); self.app.lock = threading.Lock()
        self.app.media_jobs = Mock(); self.app.cloud_client = Mock(); self.app.results_store = Mock()
        self.app._registered_run_root = Mock(return_value=self.app.root / 'original')
        self.app.run = Mock(side_effect=AssertionError('must never reimport source'))
        self.rid = str(uuid.uuid4()); self.payload = {'run_id': self.rid, 'path': 'attachments/' + 'a' * 64 + '/' + 'b' * 64 + '.webp'}
    def tearDown(self): self.tmp.cleanup()
    def test_explicit_save_uses_same_registered_attachment_and_no_video_init(self):
        with patch('saved_media_attachments.SavedMediaAttachments') as adapter, patch('image_cloud_client.publish', return_value={'state': 'received'}) as publish:
            self.assertEqual(self.app.process_media('image_cloud_save', self.payload)['state'], 'received')
            publish.assert_called_once_with(self.app.media_jobs, adapter.return_value, self.app.root / 'cloud-outbox/outbox.sqlite3', self.app.cloud_client, self.rid, self.payload['path'])
            self.assertEqual(adapter.call_args.args[1](self.rid), self.app.root / 'original/runs' / self.rid)
        self.app.cloud_client.call.assert_not_called(); self.app.run.assert_not_called()
    def test_status_never_publishes_and_download_expected_hash_is_bound(self):
        with patch('saved_media_attachments.SavedMediaAttachments'), patch('image_cloud_client.status', return_value={'state': 'not_saved'}), patch('image_cloud_client.publish') as publish:
            self.assertEqual(self.app.process_media('image_cloud_status', self.payload)['state'], 'not_saved'); publish.assert_not_called()
        value = {'data': b'bytes', 'mime': 'image/webp', 'sha256': 'b' * 64}
        with patch('saved_media_attachments.SavedMediaAttachments'), patch('image_cloud_client.download', return_value=value):
            self.assertEqual(self.app.process_media('image_cloud_file', {**self.payload, 'asset_sha256': 'b' * 64}), value)
            with self.assertRaisesRegex(ValueError, 'image_cloud_download_mismatch'):
                self.app.process_media('image_cloud_file', {**self.payload, 'asset_sha256': 'c' * 64})
    def test_foreign_path_extra_fields_bad_identity_refused_without_network(self):
        for payload in ({**self.payload, 'path': '/private/file'}, {**self.payload, 'run_id': 'bad'}, {**self.payload, 'upload_url': 'https://foreign.invalid'}):
            with self.subTest(payload=payload), self.assertRaises(ValueError): self.app.process_media('image_cloud_save', payload)
        self.app.cloud_client.call.assert_not_called(); self.app.run.assert_not_called()
    def test_missing_cloud_configuration_is_explicit_and_never_requests_login(self):
        self.app.cloud_client = None
        with self.assertRaisesRegex(ValueError, 'cloud_configuration_required'):
            self.app.process_media('image_cloud_save', self.payload)
        self.app.run.assert_not_called()


if __name__ == '__main__': unittest.main()
