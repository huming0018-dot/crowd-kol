import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import urllib.request
import uuid
from unittest.mock import patch, Mock

from dashboard import Application, make_server


class CollectorRootsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name).resolve()
        self.mc = base / 'fake-mc'; self.mc.mkdir()
        for name in ('main.py', 'LICENSE'):
            (self.mc / name).write_text('fixture')
        self.roots = [base / 'old-wb', base / 'old-xhs']
        self.ids = []
        for root, platform in zip(self.roots, ('wb', 'xhs')):
            rid, sid = str(uuid.uuid4()), str(uuid.uuid4())
            self.ids.append((rid, sid))
            session = root / 'sessions' / sid
            session.mkdir(parents=True)
            (session / 'identity.json').write_text(json.dumps({'platform': platform}))
            (session / 'browser_data').mkdir()
            (session / 'browser_data' / 'untouched').write_text('private sentinel')
            run = root / 'runs' / rid
            folder = run / 'output' / platform / 'media'; folder.mkdir(parents=True)
            (folder / 'image.png').write_bytes(platform.encode())
            (run / 'status.json').write_text(json.dumps({'run_id': rid, 'session_id': sid,
                'platform': platform, 'state': 'completed', 'updated_at': time.time()}))
            (run / 'manifest.json').write_text(json.dumps({'run_id': rid, 'source': {},
                'request': {'platform': platform, 'session_id': sid}}))
            data = run / 'output' / platform / 'jsonl'; data.mkdir()
            (data / 'fixture_contents_1.jsonl').write_text(json.dumps(
                {'note_id': '123', 'desc': 'body'} if platform == 'xhs' else {'note_id': '123', 'content': 'body'}) + '\n')
        self.app = Application(base / 'workbench', self.mc, self.roots)
        self.app.owner_tasks.close(); self.app.watchlists.close()
        self.server = make_server(self.app, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.temp.cleanup()

    def post(self, action, payload):
        request = urllib.request.Request(self.url + '/api/action',
            data=json.dumps({'action': action, 'payload': payload}).encode(),
            headers={'Content-Type': 'application/json', 'Origin': self.url, 'X-Crowd-CSRF': self.app.token})
        return json.load(urllib.request.urlopen(request))

    def test_real_http_list_status_import_and_restart_preserve_roots(self):
        listed = self.post('list', {})['result']['runs']
        self.assertEqual({r['run_id'] for r in listed}, {i[0] for i in self.ids})
        self.assertNotIn(str(self.roots[0]), json.dumps(listed))
        for rid, _ in self.ids:
            self.assertEqual(self.post('status', {'run_id': rid})['result']['state'], 'completed')
            self.assertEqual(self.post('stop', {'run_id': rid})['result']['state'], 'completed')
            self.assertTrue(self.post('import', {'run_id': rid})['ok'])
        self.app.configure({'mc_root': str(self.mc)})
        restored = Application(self.app.root)
        restored.owner_tasks.close(); restored.watchlists.close()
        self.assertEqual(restored.collector_roots, self.roots)
        self.assertEqual(len(restored.run('list', {})['result']['runs']), 2)
        for root, (_, sid) in zip(self.roots, self.ids):
            self.assertEqual((root / 'sessions' / sid / 'browser_data' / 'untouched').read_text(), 'private sentinel')

    def test_session_route_platform_and_ambiguity_without_source_start(self):
        rid, sid = self.ids[0]
        with patch.object(self.app, '_call_runner', return_value={'ok': True, 'result': {'run_id': rid}}) as runner:
            self.post('start', {'platform': 'wb', 'session_id': sid})
            self.assertEqual(runner.call_args.args[0], self.roots[0])
            with self.assertRaisesRegex(ValueError, 'session_platform_mismatch'):
                self.app.run('start', {'platform': 'xhs', 'session_id': sid})
            duplicate = self.roots[1] / 'sessions' / sid; duplicate.mkdir()
            with self.assertRaisesRegex(ValueError, 'collector_session_ambiguous'):
                self.app.run('start', {'platform': 'wb', 'session_id': sid})
            (self.roots[1] / 'runs' / rid).mkdir()
            with self.assertRaisesRegex(ValueError, 'collector_run_ambiguous'):
                self.app.run('status', {'run_id': rid})
            self.assertEqual(runner.call_count, 1)
        with self.assertRaisesRegex(ValueError, 'invalid_configuration'):
            self.app.configure({'mc_root': str(self.mc), 'collector_roots': ['/tmp']})

    def test_media_route_uses_original_run_and_rejects_cross_content(self):
        rid, _ = self.ids[0]
        self.app.media_jobs = Mock()
        self.app.media_jobs.start.return_value = {'ok': True, 'job_id': 'fake'}
        # Use a valid imported content contract, while exercising the real run-root/media lookup.
        imported = {'records': [{'kind': 'content', 'platform': 'weibo', 'content_id': '123'}],
                    'media': [{'path': 'output/wb/media/image.png'}]}
        with patch.object(self.app, 'run', return_value={'ok': True, 'result': imported}):
            path = self.app.media_file({'run_id': rid, 'path': 'output/wb/media/image.png'})
            self.assertEqual(path, self.roots[0] / 'runs' / rid / 'output/wb/media/image.png')
            self.app.process_media('start', {'run_id': rid, 'path': 'output/wb/media/image.png', 'content_id': '123', 'kind': 'ocr'})
            self.assertEqual(self.app.media_jobs.start.call_args.args[0], path)
            with self.assertRaisesRegex(ValueError, 'media_content_not_in_task'):
                self.app.process_media('start', {'run_id': rid, 'path': 'output/wb/media/image.png', 'content_id': 'other', 'kind': 'ocr'})
            self.assertEqual(self.app.media_jobs.start.call_count, 1)


if __name__ == '__main__':
    unittest.main()
