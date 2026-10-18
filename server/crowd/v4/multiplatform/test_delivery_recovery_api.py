"""Owner recovery route/CSRF tests; no scheduler, credentials, cloud or sources."""
import json
import secrets
import threading
import unittest
import urllib.error
import urllib.request
import uuid
from types import SimpleNamespace
from unittest.mock import Mock

from dashboard import Application, make_server


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.app = Application.__new__(Application)
        self.app.token = secrets.token_urlsafe(32)
        self.app.cloud_client = SimpleNamespace(role='owner')
        self.worker = self.app.cloud_worker = Mock()
        self.worker.delivery_status.return_value = {'schema': 'crowd-delivery-status-v1', 'groups': []}
        self.ids = ['aaaaaaaa-0000-4000-8000-000000000001', 'bbbbbbbb-0000-4000-8000-000000000002']
        self.worker.retry_delivery.return_value = {'schema': 'crowd-delivery-retry-v1', 'accepted': True,
                                                  'state': 'queued', 'requeued_capture_ids': self.ids}

    def test_read_and_retry_delegate_without_arbitrary_run_or_lease(self):
        value = self.app.cloud('delivery_status', {})
        self.assertTrue(value['available']); self.worker.delivery_status.assert_called_once_with()
        result = self.app.cloud('retry_delivery', {'capture_ids': self.ids})
        self.assertTrue(result['accepted'])
        self.worker.retry_delivery.assert_called_once_with(self.ids, self.app.cloud_client)
        self.assertEqual([call[0] for call in self.worker.method_calls], ['delivery_status', 'retry_delivery'])

    def test_strict_capture_list_and_no_run_override(self):
        for payload in ({}, {'capture_ids': []}, {'capture_ids': [self.ids[0]]*2},
                        {'capture_ids': ['bad']}, {'capture_ids': [True]}, {'capture_ids': [{}]},
                        {'capture_ids': [self.ids[0].upper()]}, {'capture_ids': self.ids, 'run_id': str(uuid.uuid4())},
                        {'capture_ids': self.ids, 'lease_epoch': 1}, {'capture_ids': self.ids, 'force': True},
                        {'capture_ids': [str(uuid.uuid4()) for _ in range(2001)]}):
            with self.subTest(payload=type(payload)):
                with self.assertRaisesRegex(ValueError, 'invalid_delivery_request'):
                    self.app.cloud('retry_delivery', payload)
        self.worker.retry_delivery.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'invalid_delivery_request'):
            self.app.cloud('delivery_status', {'run_id': str(uuid.uuid4())})

    def test_worker_only_or_missing_owner_cannot_mutate(self):
        self.app.cloud_client.role = 'worker'
        for action, payload in (('delivery_status', {}), ('retry_delivery', {'capture_ids': self.ids})):
            with self.assertRaisesRegex(ValueError, 'owner_authorization_required'):
                self.app.cloud(action, payload)
        self.worker.retry_delivery.assert_not_called()
        self.app.cloud_client = None
        self.assertFalse(self.app.cloud('delivery_status', {})['available'])
        with self.assertRaisesRegex(ValueError, 'cloud_configuration_required'):
            self.app.cloud('retry_delivery', {'capture_ids': self.ids})

    def test_old_worker_is_upgrade_required_and_bad_ack_is_unknown(self):
        self.app.cloud_worker = SimpleNamespace()
        self.assertEqual(self.app.cloud('delivery_status', {})['reason'], 'upgrade_required')
        with self.assertRaisesRegex(ValueError, 'cloud_upgrade_required'):
            self.app.cloud('retry_delivery', {'capture_ids': self.ids})
        self.app.cloud_worker = self.worker
        self.worker.retry_delivery.return_value = {'accepted': True}
        with self.assertRaisesRegex(ValueError, 'cloud_outcome_unknown'):
            self.app.cloud('retry_delivery', {'capture_ids': self.ids})
        self.worker.delivery_status.return_value = {'schema': 'old', 'groups': []}
        with self.assertRaisesRegex(ValueError, 'cloud_read_unavailable'):
            self.app.cloud('delivery_status', {})

    def test_retry_response_must_keep_requested_ids_and_queued_is_not_ack(self):
        for value in (None, ['extra'], [True], [self.ids[0]]*2):
            self.worker.retry_delivery.return_value = {'schema':'crowd-delivery-retry-v1', 'accepted':True,
                                                       'state':'queued', 'requeued_capture_ids':value}
            with self.assertRaisesRegex(ValueError, 'cloud_outcome_unknown'):
                self.app.cloud('retry_delivery', {'capture_ids':self.ids})
        for value in ([], self.ids[:1], self.ids):
            self.worker.retry_delivery.return_value = {'schema':'crowd-delivery-retry-v1', 'accepted':True,
                                                       'state':'queued', 'requeued_capture_ids':value}
            self.assertEqual(self.app.cloud('retry_delivery', {'capture_ids':self.ids})['state'], 'queued')
        self.worker.retry_delivery.return_value['state'] = 'acknowledged'
        with self.assertRaisesRegex(ValueError, 'cloud_outcome_unknown'):
            self.app.cloud('retry_delivery', {'capture_ids':self.ids})

    def test_error_whitelist_preserves_known_reason_without_raw_leak(self):
        for code in ('task_paused', 'task_stopped', 'cloud_outcome_unknown', 'delivery_state_conflict', 'delivery_retry_run_mismatch'):
            self.worker.retry_delivery.side_effect = ValueError(code)
            with self.assertRaisesRegex(ValueError, code):
                self.app.cloud('retry_delivery', {'capture_ids': self.ids})
        for code in ('Cookie=SECRET', 'SECRET_RAW_KEY', '/private/path/to/config'):
            self.worker.retry_delivery.side_effect = ValueError(code)
            with self.assertRaisesRegex(ValueError, '^delivery_recovery_unavailable$'):
                self.app.cloud('retry_delivery', {'capture_ids': self.ids})

    def test_actual_http_origin_token_host_content_type_and_method(self):
        self.app.health_events = Mock(); self.app.watchlists = Mock()
        self.app.analysis_jobs = self.app.media_jobs = self.app.owner_tasks = None
        server = make_server(self.app, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        url = 'http://127.0.0.1:' + str(server.server_port)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def post(changes=None, body=None, path='/api/cloud'):
            headers = {'Content-Type': 'application/json', 'Origin': url, 'X-Crowd-CSRF': self.app.token}
            for key, value in (changes or {}).items():
                if value is None: headers.pop(key, None)
                else: headers[key] = value
            request = urllib.request.Request(url + path, json.dumps(body if body is not None else {'action': 'retry_delivery',
                'payload': {'capture_ids': self.ids}}).encode(), headers, method='POST')
            return opener.open(request, timeout=5)
        try:
            for headers, code in (({'Origin': 'https://other.invalid'}, 403), ({'Origin': None}, 403),
                                  ({'X-Crowd-CSRF': 'wrong'}, 403), ({'X-Crowd-CSRF': None}, 403),
                                  ({'Host': 'attacker.invalid'}, 403), ({'Content-Type': 'text/plain'}, 400)):
                with self.subTest(headers=headers):
                    with self.assertRaises(urllib.error.HTTPError) as error: post(headers)
                    self.assertEqual(error.exception.code, code)
            self.worker.retry_delivery.assert_not_called()
            with self.assertRaises(urllib.error.HTTPError) as error:
                opener.open(url + '/api/cloud?action=retry_delivery', timeout=5)
            self.assertEqual(error.exception.code, 404)
            with post() as response: self.assertTrue(json.load(response)['accepted'])
            self.worker.retry_delivery.assert_called_once_with(self.ids, self.app.cloud_client)
            large_ids = [str(uuid.uuid4()) for _ in range(2000)]
            self.worker.retry_delivery.return_value['requeued_capture_ids'] = large_ids
            with post(body={'action':'retry_delivery','payload':{'capture_ids':large_ids}}) as response:
                self.assertEqual(json.load(response)['requeued_capture_ids'], large_ids)
            self.assertEqual(self.worker.retry_delivery.call_count, 2)
            # Only exact recovery gets the larger body allowance; all other routes/actions keep 32 KiB.
            for body, path in (({'action':'delivery_status','payload':{'padding':'x'*33000}},'/api/cloud'),
                               ({'action':'status','payload':{'padding':'x'*33000}},'/api/health'),
                               ({'action':'retry_delivery','payload':{'capture_ids':large_ids}},'/api/action'),
                               ({'action':'retry_delivery','payload':{'capture_ids':large_ids,'padding':'x'*131073}},'/api/cloud')):
                with self.assertRaises(urllib.error.HTTPError) as error:post(body=body,path=path)
                self.assertEqual(error.exception.code,400)
            self.assertEqual(self.worker.retry_delivery.call_count, 2)
        finally:
            server.shutdown(); thread.join(3); server.server_close()


if __name__ == '__main__': unittest.main()
