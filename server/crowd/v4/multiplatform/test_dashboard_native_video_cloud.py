from pathlib import Path
import threading
import unittest
from unittest.mock import Mock, patch
from dashboard import Application


RUN = '191578de-5510-4fae-a8a7-aca16d80e31b'
SHA = 'a' * 64


class Tests(unittest.TestCase):
    def setUp(self):
        self.app = Application.__new__(Application)
        self.app.lock = threading.Lock()
        self.app.media_jobs = Mock()
        self.app.cloud_client = Mock()
        self.app._registered_run_root = Mock(return_value=Path('/registered'))
        self.payload = {'run_id': RUN, 'content_id': '123', 'asset_sha256': SHA}

    def test_status_uses_registered_root_without_storage_initialization(self):
        self.app.cloud_client = None
        with patch('media_native.native_video_cloud_status', return_value={'state': 'not_saved'}) as check:
            self.assertEqual(self.app.process_media('native_video_cloud_status', self.payload), {'state': 'not_saved'})
            check.assert_called_once_with(self.app.media_jobs, None, Path('/registered/runs') / RUN, '123', SHA, None)
        self.app._registered_run_root.assert_called_once_with(RUN)

    def test_full_local_validation_precedes_explicit_storage_initialization(self):
        events = []
        self.app.cloud_client.call.side_effect = lambda *args: events.append('initialize')
        with patch('media_native.prepare_native_video', side_effect=lambda *args: events.append('validate')), patch('media_native.publish_native_video', side_effect=lambda *args: events.append('publish') or {'receipt': 'fixture'}):
            self.app.process_media('native_video_cloud_save', self.payload)
        self.assertEqual(events, ['validate', 'initialize', 'publish'])
        self.app.cloud_client.call.reset_mock()
        with patch('media_native.prepare_native_video', side_effect=ValueError('media_native_asset_changed')):
            with self.assertRaises(ValueError): self.app.process_media('native_video_cloud_save', self.payload)
        self.app.cloud_client.call.assert_not_called()

    def test_typed_selector_and_binary_download_use_same_registered_identity(self):
        typed = {**self.payload, 'entity_ref': 'zhihu:content:123:zvideo'}
        with patch('media_native.download_native_video', return_value={'data': b'video', 'sha256': SHA}) as download:
            self.assertEqual(self.app.process_media('native_video_cloud_file', typed)['data'], b'video')
            self.assertEqual(download.call_args.args[-1], typed['entity_ref'])

    def test_foreign_path_url_fields_and_unregistered_run_never_initialize_storage(self):
        for fields in ({'path': '/foreign'}, {'upload_url': 'https://foreign'}, {'binding': {}}, {'worker_secret': 'fixture'}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.app.process_media('native_video_cloud_save', {**self.payload, **fields})
        self.app._registered_run_root.side_effect = ValueError('run_not_found')
        with self.assertRaises(ValueError): self.app.process_media('native_video_cloud_save', self.payload)
        self.app.cloud_client.call.assert_not_called()


if __name__ == '__main__': unittest.main()
