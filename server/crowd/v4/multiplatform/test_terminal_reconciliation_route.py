"""The normal owner route forwards one reviewed reconciliation, never retries."""
import tempfile
import unittest
from unittest.mock import Mock

from cloud_sync import CloudOwnerAdapter, CloudError
from dashboard import Application
from workbench_cli import ROUTES


class Tests(unittest.TestCase):
    def test_owner_forward_one_call_and_preserve_unknown_failure(self):
        client=Mock();client.call.return_value={'audit_id':'audit','resolution':'terminal_unknown'}
        adapter=CloudOwnerAdapter(client);payload={'mode':'terminal_unknown','proof':{'executor_inactive':True}}
        self.assertEqual(adapter.reconcile(payload)['audit_id'],'audit')
        client.call.assert_called_once_with('task_reconcile',payload)
        client.reset_mock();client.call.side_effect=CloudError('cloud_outcome_unknown')
        with self.assertRaisesRegex(CloudError,'cloud_outcome_unknown'):adapter.reconcile(payload)
        client.call.assert_called_once()
    def test_same_dashboard_cloud_route_and_local_rejection(self):
        with tempfile.TemporaryDirectory() as root:
            app=Application(root)
            try:
                with self.assertRaisesRegex(ValueError,'reconciliation_requires_cloud_task'):
                    app.tasks('reconcile',{'mode':'terminal_unknown'})
                app.owner_tasks.close()
                client=Mock();client.call.return_value={'audit_id':'audit'}
                app.owner_tasks=CloudOwnerAdapter(client)
                self.assertEqual(app.tasks('reconcile',{'mode':'terminal_unknown'})['audit_id'],'audit')
                client.call.assert_called_once_with('task_reconcile',{'mode':'terminal_unknown'})
                self.assertIn('reconcile',ROUTES['tasks'])
            finally:
                app.owner_tasks.close()
                app.watchlists.close()

if __name__=='__main__':unittest.main()
