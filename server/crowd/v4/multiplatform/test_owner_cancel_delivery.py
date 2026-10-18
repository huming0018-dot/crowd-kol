"""Owner cancellation must not shadow the UUID validator of saved-delivery recovery."""
import unittest
from types import SimpleNamespace
from dashboard import Application

class DeliveryRecovery(unittest.TestCase):
    def test_valid_retry_still_reaches_existing_worker(self):
        capture = '00000000-0000-4000-8000-000000000001'
        calls = []
        def retry(ids, client):
            calls.append((ids, client))
            return {'schema': 'crowd-delivery-retry-v1', 'accepted': True,
                    'state': 'queued', 'requeued_capture_ids': ids}
        app = Application.__new__(Application)
        app.cloud_client = SimpleNamespace(role='owner')
        app.cloud_worker = SimpleNamespace(retry_delivery=retry)
        result = app.cloud('retry_delivery', {'capture_ids': [capture]})
        self.assertTrue(result['accepted'])
        self.assertEqual(calls, [([capture], app.cloud_client)])

    def test_invalid_retry_remains_rejected(self):
        app = Application.__new__(Application)
        app.cloud_client = SimpleNamespace(role='owner')
        app.cloud_worker = SimpleNamespace()
        with self.assertRaisesRegex(ValueError, 'invalid_delivery_request'):
            app.cloud('retry_delivery', {'capture_ids': ['bad']})

if __name__ == '__main__':
    unittest.main()
