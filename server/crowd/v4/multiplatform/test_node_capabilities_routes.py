import unittest
from unittest.mock import Mock
from dashboard import Application
from cloud_sync import CloudError


class NodeCapabilityRoutes(unittest.TestCase):
    def setUp(self):
        self.app = Application.__new__(Application)
        self.app.cloud_client = Mock(role='owner')
        self.app.cloud_client.call.return_value = {'schema': 'crowd-worker-capabilities-page-v1', 'nodes': [], 'total': 0}

    def test_original_owner_read_only_forward(self):
        for payload in ({}, {'limit': 100}, {'limit': 1, 'after_worker_id': '00000000-0000-4000-8000-000000000001'}):
            self.assertTrue(self.app.cloud('worker_capabilities', payload)['available'])
            self.app.cloud_client.call.assert_called_with('worker_capabilities', payload)

    def test_invalid_filter_does_not_call_cloud(self):
        for payload in ({'limit': True}, {'limit': 0}, {'limit': 101}, {'after_worker_id': 'bad'}, {'token': 'PRIVATE'}, {'after_worker_id': None}):
            with self.assertRaises(ValueError): self.app.cloud('worker_capabilities', payload)
        self.app.cloud_client.call.assert_not_called()

    def test_missing_or_old_cloud_never_claims_ready(self):
        self.app.cloud_client.call.return_value = {'schema': 'old'}
        self.assertFalse(self.app.cloud('worker_capabilities', {})['available'])
        for code in ('invalid_action', 'principal_denied'):
            self.app.cloud_client.call.side_effect = CloudError(code)
            self.assertFalse(self.app.cloud('worker_capabilities', {})['available'])
        self.app.cloud_client = None
        self.assertFalse(self.app.cloud('worker_capabilities', {})['available'])

    def test_worker_role_cannot_read_owner_fleet(self):
        self.app.cloud_client.role = 'worker'
        with self.assertRaises(ValueError): self.app.cloud('worker_capabilities', {})
        self.app.cloud_client.call.assert_not_called()


if __name__ == '__main__': unittest.main()
