"""Actual Owner route -> worker -> durable outbox with synthetic scoped cloud only."""
import fcntl
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from cloud_sync import CloudError, CloudWorker
from dashboard import Application
from test_cloud_outbox_retry import PoisonCloud
from test_cloud_sync import lease, row


class OwnerRecoveryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cloud = PoisonCloud()
        self.runner = Mock(side_effect=AssertionError('recovery must not call source runner'))
        self.worker = CloudWorker(Path(self.temp.name), self.cloud, self.runner)
        self.ids = self.worker.outbox.stage_imported([{**row(), 'content_id':'bad-original'}], self.cloud.lease)
        self.worker._save({'phase':'delivering', 'lease':self.cloud.lease, 'outcome':'completed', 'api_attempts':1})
        self.assertEqual(self.worker.tick()['state'], 'delivery_pending')
        value = self.cloud.lease
        self.task = {'task_id':value['task_id'], 'desired_state':'running', 'children':[
            {'child_id':value['child_id'], 'worker_id':value['worker_id'], 'lease_epoch':value['lease_epoch'],
             'state':'delivery_pending', 'runs':[value['run_id']]}]}
        self.owner = SimpleNamespace(role='owner', call=Mock(return_value={'task':self.task}))
        self.app = Application.__new__(Application)
        self.app.cloud_client, self.app.cloud_worker = self.owner, self.worker

    def rows(self):
        with self.worker.outbox._db() as db:
            return db.execute('select id,run_id,envelope,digest from captures order by id').fetchall()

    def retry(self, ids=None):
        return self.app.cloud('retry_delivery', {'capture_ids':self.ids if ids is None else ids})

    def test_original_group_route_requeues_then_exact_ack_without_source_or_new_run(self):
        before = self.rows()
        value = self.app.cloud('delivery_status', {})
        self.assertEqual(value['groups'][0]['pending'], 1)
        self.assertEqual(value['groups'][0]['quarantined_capture_ids'], self.ids)
        self.assertNotIn('不访问真实来源', json.dumps(value, ensure_ascii=False))
        calls = len(self.cloud.calls)
        self.cloud.fixed = True
        queued = self.retry()
        self.assertEqual((queued['accepted'],queued['state'],queued['requeued_capture_ids']), (True,'queued',self.ids))
        self.assertEqual(len(self.cloud.calls), calls, 'Owner click only queues; never directly uploads')
        self.assertEqual(self.rows(), before)
        self.owner.call.assert_called_once_with('task_status', {'task_id':self.task['task_id']})
        value = self.worker.tick()
        self.assertEqual(value['state'], 'finished')
        self.assertEqual(self.worker.outbox.stats()['acknowledged'], 1)
        self.assertEqual(self.rows(), before)
        self.assertEqual(list(self.cloud.receipts), self.ids)
        self.assertEqual(self.cloud.receipts[self.ids[0]]['run_id'], before[0][1])
        self.assertFalse(any(action=='claim' for action,_ in self.cloud.calls))
        self.runner.assert_not_called()

    def test_pause_stop_and_foreign_owner_scope_do_not_reset_isolation(self):
        before = self.rows()
        for change in ({'desired_state':'paused'}, {'desired_state':'stopped'}, {'task_id':lease()['task_id']}):
            self.owner.call.return_value = {'task':{**self.task, **change}}
            with self.assertRaisesRegex(ValueError, 'delivery_retry_denied|task_paused|task_stopped'):
                self.retry()
            self.assertEqual(self.worker.outbox.stats()['quarantined'],1)
            self.assertEqual(self.rows(),before)
        self.owner.call.side_effect = CloudError('principal_denied')
        with self.assertRaisesRegex(ValueError, 'principal_denied'):self.retry()
        self.assertEqual(self.worker.outbox.stats()['quarantined'],1)
        self.runner.assert_not_called()

    def test_cross_run_payload_rejected_atomically(self):
        second = self.worker.outbox.stage_imported([{**row(),'content_id':'bad-other'}], lease())
        before = self.rows()
        with self.assertRaisesRegex(ValueError, 'delivery_retry_run_mismatch'):self.retry(self.ids+second)
        self.owner.call.assert_not_called()
        self.assertEqual(self.worker.outbox.stats()['quarantined'],1)
        self.assertEqual(self.rows(),before)

    def test_busy_worker_preserves_queue_and_duplicate_click_cannot_reset_inflight(self):
        before = self.rows()
        with open(self.worker.lock_path,'r+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, 'cloud_controller_busy'):self.retry()
        self.assertEqual(self.worker.outbox.stats()['quarantined'],1)
        self.retry()
        with self.assertRaisesRegex(ValueError, 'capture_not_quarantined'):self.retry()
        self.assertEqual(self.rows(),before)


if __name__ == '__main__': unittest.main()
