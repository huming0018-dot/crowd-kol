import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import MagicMock

from dashboard import Application, make_server


class HealthDashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Application(Path(self.temp.name))
        self.server = make_server(self.app, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.temp.cleanup()

    def post(self, body, origin=None):
        return urllib.request.urlopen(urllib.request.Request(self.url+'/api/health',
            data=json.dumps(body).encode(), headers={'Content-Type': 'application/json',
            'Origin': origin or self.url, 'X-Crowd-CSRF': self.app.token}), timeout=2)

    def test_health_read_is_scoped_and_never_exposes_raw_error(self):
        self.app.health_events.observe({'phase': 'running', 'health_error': 'scheduler_dead',
                                       'last_error': 'Cookie SECRET', 'url': 'private'})
        value = json.load(self.post({'action': 'status', 'payload': {}}))
        self.assertEqual(value['current']['health_error'], 'scheduler_dead')
        self.assertNotIn('SECRET', json.dumps(value))
        self.assertEqual(value['storage_scope'], 'local')
        self.assertEqual(value['incident_count'], 1)

    def test_health_rejects_foreign_origin_and_extra_fields(self):
        for body, origin in [({'action': 'status', 'payload': {}}, 'https://foreign.example'),
                             ({'action': 'status', 'payload': {'token': 'hidden'}}, self.url)]:
            with self.assertRaises(urllib.error.HTTPError): self.post(body, origin)

    def test_fifo_cannot_block_health_api(self):
        self.app.health_events.root.mkdir(mode=0o700)
        os.mkfifo(self.app.health_events.root/'events.jsonl', 0o600)
        value = json.load(self.post({'action': 'status', 'payload': {}}))
        self.assertEqual(value['monitor_error'], 'health_history_unavailable')

    def test_participant_health_empty_payload_only_forwards_owner_read(self):
        self.app.cloud_client = MagicMock()
        self.app.cloud_client.call.return_value = {'schema': 'crowd-participant-health-v1', 'participants': [], 'events': []}
        value = self.app.cloud('participant_health', {})
        self.assertEqual(value['storage_scope'], 'cloud')
        self.app.cloud_client.call.assert_called_once_with('participant_health', {})
        with self.assertRaises(ValueError): self.app.cloud('participant_health', {'user_id': 'outside'})


if __name__ == '__main__':
    unittest.main()
