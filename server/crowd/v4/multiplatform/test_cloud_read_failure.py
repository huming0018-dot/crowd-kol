import io
import unittest
import urllib.error
from unittest.mock import Mock

from cloud_sync import CloudClient, CloudError


class CloudReadFailureTests(unittest.TestCase):
    def client(self, role, error, during_read=False):
        client = CloudClient.__new__(CloudClient)
        client.role = role
        client.endpoint = 'https://isolated.supabase.co/functions/v1/crowd-machine'
        client.headers = {}
        client.opener = Mock()
        if during_read:
            response = Mock()
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            response.read.side_effect = error
            client.opener.open.return_value = response
        else:
            client.opener.open.side_effect = error
        return client

    def test_only_owner_task_reads_have_read_failure(self):
        errors = (urllib.error.URLError('sensitive detail'), TimeoutError('sensitive detail'), OSError('sensitive detail'))
        for role in ('owner', 'worker'):
            for action in ('task_list', 'task_status', 'task_preview', 'task_create', 'task_control', 'retry_supplemental', 'worker_pair', 'worker_revoke', 'claim', 'heartbeat', 'capture', 'receipt', 'finish', 'resume_login', 'reconcile_no_dispatch', 'future_action'):
                for error in errors:
                    for during_read in (False, True):
                        with self.subTest(role=role, action=action, error=type(error).__name__, during_read=during_read):
                            client = self.client(role, error, during_read)
                            expected = 'cloud_read_unavailable' if role == 'owner' and action in ('task_list', 'task_status') else 'cloud_outcome_unknown'
                            with self.assertRaises(CloudError) as caught:
                                client.call(action)
                            self.assertEqual(str(caught.exception), expected)
                            self.assertEqual(client.opener.open.call_count, 1)

    def test_explicit_http_denial_remains_authoritative(self):
        for action in ('task_list', 'task_status', 'task_create'):
            client = self.client('owner', None)
            client.opener.open.side_effect = urllib.error.HTTPError(client.endpoint, 403, 'Forbidden', {}, io.BytesIO(b'{"ok":false,"error":"principal_denied"}'))
            with self.assertRaises(CloudError) as caught:
                client.call(action)
            self.assertEqual(str(caught.exception), 'principal_denied')
            self.assertEqual(client.opener.open.call_count, 1)


if __name__ == '__main__':
    unittest.main()
