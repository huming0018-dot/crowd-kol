import hashlib
import json
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import dashboard
import workbench_cli


class WorkbenchCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = dashboard.Application(Path(self.temp.name))
        self.server = dashboard.make_server(self.app, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.temp.cleanup()

    def test_same_http_task_list_preview_no_source(self):
        with patch.object(self.app, 'run') as runner:
            value, manifest = workbench_cli.call(self.url, 'tasks', 'list', {})
            self.assertEqual(value['tasks'], [])
            payload = {'platforms': ['wb'], 'mode': 'detail', 'targets_by_platform': {'wb': ['123']},
                       'desired_items': 1, 'max_api_requests': 3,
                       'purpose': 'noncommercial_research', 'idempotency_key': 'cli-preview'}
            value, _ = workbench_cli.call(self.url, 'tasks', 'preview', payload)
            self.assertEqual(value['source_actions_started'], 0)
            runner.assert_not_called()

    def test_same_result_revision_export_hash_manifest(self):
        imported = {'run_id': 'cli-saved', 'records': [{'kind': 'content',
                    'platform': 'weibo', 'content_id': '123', 'title': '已保存', 'body': '已有正文'}]}
        with patch.object(self.app, 'run', return_value={'ok': True, 'result': imported}):
            workbench_cli.call(self.url, 'results', 'ingest', {'run_id': 'cli-saved'})
        rows, _ = workbench_cli.call(self.url, 'results', 'list', {})
        data, manifest = workbench_cli.call(self.url, 'results', 'export', {
            'format': 'json', 'revision': rows['results_revision']})
        self.assertEqual(manifest['sha256'], hashlib.sha256(data).hexdigest())
        self.assertEqual(manifest['row_count'], 1)

    def test_remote_userinfo_and_redirect_rejected_without_network(self):
        for url in ('https://127.0.0.1:123', 'http://evil.example:123',
                    'http://user:pass@127.0.0.1:123', self.url + '?token=x'):
            with self.assertRaisesRegex(ValueError, 'explicit_loopback_url_required'):
                workbench_cli.call(url, 'tasks', 'list', {})
        with self.assertRaisesRegex(ValueError, 'redirect_rejected'):
            workbench_cli.NoRedirect().redirect_request(None, None, None, None, None, None)

    def test_export_collision_preserves_other_file_and_leaves_no_partial(self):
        path = Path(self.temp.name) / 'export.json'
        manifest = Path(str(path) + '.manifest.json')
        manifest.write_text('existing')
        with self.assertRaises(FileExistsError):
            workbench_cli.save_export(path, b'new', {'row_count': 1})
        self.assertFalse(path.exists())
        self.assertEqual(manifest.read_text(), 'existing')
        manifest.unlink()
        workbench_cli.save_export(path, b'new', {'row_count': 1})
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(manifest.read_text())['row_count'], 1)


if __name__ == '__main__':
    unittest.main()
