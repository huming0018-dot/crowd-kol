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


    def test_owner_transcript_timeout_retries_once_and_recovers(self):
        for error in (TimeoutError('private'),urllib.error.URLError('private')):
            client=self.client('owner',None)
            response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
            response.read.return_value=b'{"ok":true,"result":{"status":"received"}}'
            client.opener.open.side_effect=[error,response]
            self.assertEqual(client.call('transcript_get',{'job_id':'saved'})['status'],'received')
            self.assertEqual(client.opener.open.call_count,2)
            self.assertIs(client.opener.open.call_args_list[0].args[0],client.opener.open.call_args_list[1].args[0])

    def test_owner_transcript_double_failure_and_read_timeout_are_bounded(self):
        for during_read in (False,True):
            client=self.client('owner',TimeoutError('private'),during_read)
            with self.assertRaisesRegex(CloudError,'^cloud_read_unavailable$'):client.call('transcript_get')
            self.assertEqual(client.opener.open.call_count,2)

    def test_transcript_writes_worker_reads_and_os_errors_never_retry(self):
        for role,action in (('owner','transcript_put'),('worker','transcript_get'),('owner','future_write')):
            client=self.client(role,TimeoutError('private'))
            with self.assertRaisesRegex(CloudError,'^cloud_outcome_unknown$'):client.call(action)
            self.assertEqual(client.opener.open.call_count,1)
        client=self.client('owner',OSError('private'))
        with self.assertRaisesRegex(CloudError,'^cloud_read_unavailable$'):client.call('transcript_get')
        self.assertEqual(client.opener.open.call_count,1)

    def test_transcript_business_error_does_not_retry_after_transport_or_http(self):
        for initial_failure in (False,True):
            client=self.client('owner',None)
            error=urllib.error.HTTPError(client.endpoint,404,'Not Found',{},io.BytesIO(b'{"ok":false,"error":"transcript_not_found"}'))
            client.opener.open.side_effect=[TimeoutError('private'),error] if initial_failure else error
            with self.assertRaisesRegex(CloudError,'^transcript_not_found$'):client.call('transcript_get')
            self.assertEqual(client.opener.open.call_count,2 if initial_failure else 1)


if __name__ == '__main__':
    unittest.main()
