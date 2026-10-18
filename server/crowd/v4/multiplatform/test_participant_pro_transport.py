import json
import subprocess
import unittest
from unittest.mock import patch
from participant_pro_transport import ParticipantProTransport, ParticipantTransportError


class TransportTests(unittest.TestCase):
    def transport(self):
        return ParticipantProTransport('/private/original-profile',
            '2fc8765e-700a-41c1-b325-a21c5faa22ce',
            '3cde2858-39a5-42e1-b7ab-dd62053d2dac', node='/absolute/node')

    def test_uses_stdin_no_credentials_or_arguments(self):
        with patch('participant_pro_transport.subprocess.run') as run:
            run.return_value=subprocess.CompletedProcess([], 0, json.dumps({'ok':True,'result':{'received':20}}), '')
            self.assertEqual(self.transport()('pro_claim', {'p_task':19}), {'received':20})
            args,kw=run.call_args
            self.assertEqual(len(args[0]),2)
            self.assertEqual(json.loads(kw['input'])['params'],{'p_task':19})
            self.assertNotIn('token',kw['input'])

    def test_arbitrary_action_rejected_before_process(self):
        with patch('participant_pro_transport.subprocess.run') as run:
            with self.assertRaises(ParticipantTransportError):self.transport()('admin',{})
            run.assert_not_called()

    def test_unknown_does_not_retry(self):
        for failure in (subprocess.TimeoutExpired('node',35),OSError('secret-path')):
            with patch('participant_pro_transport.subprocess.run',side_effect=failure) as run:
                with self.assertRaisesRegex(ParticipantTransportError,'^participant_rpc_outcome_unknown$'):
                    self.transport()('pro_submit',{'p_request':'original-request'})
                self.assertEqual(run.call_count,1)

    def test_invalid_response_and_stderr_never_escape(self):
        for stdout in ('', 'not-json', 'null', '{}', '{"ok":false,"error":"sensitive"}'):
            with patch('participant_pro_transport.subprocess.run',return_value=subprocess.CompletedProcess([],1,stdout,'sensitive')):
                with self.assertRaisesRegex(ParticipantTransportError,'^participant_rpc_outcome_unknown$'):
                    self.transport().scope()


if __name__=='__main__':unittest.main()
