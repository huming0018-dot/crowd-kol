import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

import dashboard


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = dashboard.Application(Path(self.temp.name) / 'runtime')
        self.server = dashboard.make_server(self.app, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def post(self, path, body, origin=None, token=None):
        request = urllib.request.Request(self.url + path, data=json.dumps(body).encode(), headers={
            'Content-Type': 'application/json', 'Origin': origin or self.url,
            'X-Crowd-CSRF': token if token is not None else self.app.token})
        return urllib.request.urlopen(request)

    def test_local_page_does_not_start_collection(self):
        with patch.object(self.app, 'run') as run:
            response = urllib.request.urlopen(self.url)
            text = response.read().decode()
            self.assertIn('新建采集', text)
            self.assertIn(self.app.token, text)
            self.assertIn("frame-ancestors 'none'", response.headers['Content-Security-Policy'])
            run.assert_not_called()

    def test_cross_origin_and_forged_host_rejected(self):
        with patch.object(self.app, 'run') as run:
            for origin, token in [('https://evil.example', self.app.token), (self.url, 'invalid')]:
                with self.assertRaises(urllib.error.HTTPError) as error:
                    self.post('/api/action', {'action': 'start', 'payload': {}}, origin, token)
                self.assertEqual(error.exception.code, 403)
            request = urllib.request.Request(self.url, headers={'Host': 'evil.example'})
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request)
            self.assertEqual(error.exception.code, 403)
            run.assert_not_called()

    def test_valid_action_reaches_runner_without_shell(self):
        self.app.mc_root = '/local/example'
        completed = type('Result', (), {'stdout': '{"ok":true,"result":{"runs":[]}}'})()
        with patch('dashboard.subprocess.run', return_value=completed) as run:
            response = json.load(self.post('/api/action', {'action': 'list', 'payload': {}}))
            self.assertEqual(response['result']['runs'], [])
            args, kwargs = run.call_args
            self.assertIsInstance(args[0], list)
            self.assertEqual(args[0][-1], 'list')
            self.assertFalse(kwargs.get('shell', False))

    def test_config_new_file_only_valid_executor_and_no_other_fields(self):
        mc = Path(self.temp.name) / 'mc'; mc.mkdir()
        for name in ['main.py', 'LICENSE']:
            (mc / name).write_text('fixture')
        json.load(self.post('/api/config', {'mc_root': str(mc)}))
        self.assertEqual(json.loads(self.app.config_path.read_text())['mc_root'], str(mc.resolve()))
        self.assertEqual(self.app.config_path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(urllib.error.HTTPError):
            self.post('/api/config', {'mc_root': str(mc), 'cookie': 'forbidden'})

    def test_media_only_downloads_task_manifest_files(self):
        run_id = '00000000-0000-4000-8000-000000000001'
        folder = self.app.runner_root / 'runs' / run_id / 'output' / 'xhs' / 'media'
        folder.mkdir(parents=True); (folder / 'test.bin').write_bytes(b'visible-media')
        result = {'ok': True, 'result': {'media': [{'path': 'output/xhs/media/test.bin'}]}}
        with patch.object(self.app, 'run', return_value=result):
            self.assertEqual(self.post('/api/media', {'run_id': run_id, 'path': 'output/xhs/media/test.bin'}).read(), b'visible-media')
            with self.assertRaises(urllib.error.HTTPError):
                self.post('/api/media', {'run_id': run_id, 'path': '../../../../private'})


if __name__ == '__main__':
    unittest.main()
