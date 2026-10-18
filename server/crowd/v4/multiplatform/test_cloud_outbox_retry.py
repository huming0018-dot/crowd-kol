"""D1 regressions: temporary SQLite and deterministic cloud substitutes only."""
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from cloud_sync import CloudOutbox, CloudError, CloudWorker, DeliveryLeaseError
from test_cloud_sync import FakeCloud, lease, row


class PoisonCloud(FakeCloud):
    fixed = False
    def call(self, action, payload=None):
        if action == 'capture' and payload['envelope']['record']['content_id'].startswith('bad') and not self.fixed:
            self.calls.append((action, payload))
            raise CloudError('invalid_capture_record')
        return super().call(action, payload)


class RetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.cloud = PoisonCloud()
        self.box = CloudOutbox(self.root, self.cloud)
    def tearDown(self): self.temp.cleanup()
    def stage(self, ids):
        return self.box.stage_imported([{**row(), 'content_id':value} for value in ids], self.cloud.lease)
    def snapshot(self):
        with self.box._db() as db:
            return db.execute('select id,run_id,envelope,digest from captures order by rowid').fetchall()

    def test_four_permanent_poison_rows_do_not_starve_fifth_and_explicit_repair_keeps_ids(self):
        ids = self.stage(['bad0','bad1','bad2','bad3','good']);before = self.snapshot()
        first = self.box.flush(limit=4)
        self.assertEqual((first['pending'], first['quarantined'], first['acknowledged']), (5,4,0))
        second = CloudOutbox(self.root,self.cloud).flush(limit=4)
        self.assertEqual((second['pending'], second['quarantined'], second['acknowledged']), (4,4,1))
        calls = len(self.cloud.calls)
        for _ in range(10): self.box.flush(limit=4)
        self.assertEqual(len(self.cloud.calls), calls)
        self.cloud.fixed = True
        response = self.box.retry_quarantined(ids[:4])
        self.assertEqual(response['pending'],4);self.assertEqual(response['quarantined'],0)
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(len(self.cloud.calls),calls)
        self.assertEqual(self.box.flush(limit=4)['pending'],0)
        self.assertEqual(self.box.stats()['acknowledged'],5)
        with self.box._db() as db:
            meta=db.execute('select requeues,total_attempts,last_error from capture_delivery where id=?',(ids[0],)).fetchone()
        self.assertEqual(meta,(1,2,'invalid_capture_record'))
        self.assertEqual(self.snapshot(),before)

    def test_old_seven_column_database_and_repeated_initialization_keep_insert_contract(self):
        self.stage(['good']);before=self.snapshot()
        with self.box._db() as db:db.execute('drop table capture_delivery')
        one=CloudOutbox(self.root,self.cloud);two=CloudOutbox(self.root,self.cloud)
        self.assertEqual(self.snapshot(),before)
        with two._db() as db:
            self.assertEqual(len(db.execute('pragma table_info(captures)').fetchall()),7)
        self.stage(['another-good'])
        self.assertEqual(two.flush()['acknowledged'],2)
        self.assertEqual(self.snapshot()[:1],before)

    def test_unknown_writes_check_same_receipt_before_any_retransmit(self):
        self.stage(['good','good2']);before=self.snapshot();self.cloud.lose_capture=True
        self.assertEqual(self.box.flush()['pending'],2)
        restarted=CloudOutbox(self.root,self.cloud)
        self.assertEqual(restarted.flush()['acknowledged'],2)
        self.assertEqual(sum(action=='capture' for action,_ in self.cloud.calls),2)
        first_capture=next(value['envelope']['capture_id'] for action,value in self.cloud.calls if action=='capture')
        self.assertEqual(sum(action=='capture' and value['envelope']['capture_id']==first_capture for action,value in self.cloud.calls),1)
        self.assertEqual(self.snapshot(),before)

    def test_transient_retry_ceiling_backoff_and_explicit_requeue(self):
        ids=self.stage(['good'])
        class Temporary(FakeCloud):
            def call(self,action,payload=None):
                self.calls.append((action,payload));raise CloudError('cloud_outcome_unknown')
        transient=Temporary(self.cloud.lease);self.box.client=transient
        with patch('cloud_sync.time.time',return_value=1000) as clock:
            self.box.flush();self.box.flush()
            self.assertEqual(len(transient.calls),2)
            self.assertEqual(self.box.stats()['next_retry_at'],1005)
            for _ in range(10):self.box.flush()
            self.assertEqual(len(transient.calls),2)
            for due in (1005,1015,1035):clock.return_value=due;self.box.flush()
            self.assertEqual(len(transient.calls),5)
            self.assertEqual((self.box.stats()['pending'],self.box.stats()['quarantined']),(1,1))
            clock.return_value=10000;self.box.flush();self.assertEqual(len(transient.calls),5)
        self.box.client=self.cloud;self.box.retry_quarantined(ids)
        self.assertEqual(self.box.flush()['pending'],0)

    def test_both_lease_guards_deny_without_exhausting_payload_attempts(self):
        ids=self.stage(['good']);before=self.snapshot()
        for deny_at in (1,2):
            for _ in range(7):
                calls=[]
                def guard():
                    calls.append(1)
                    if len(calls)==deny_at:raise DeliveryLeaseError('cloud_delivery_lease_denied')
                with self.assertRaises(DeliveryLeaseError):self.box.flush(before_send=guard)
            with self.box._db() as db:
                value=db.execute('select attempts,quarantined from capture_delivery where id=?',(ids[0],)).fetchone()
            self.assertIn(value,(None,(0,0)))
        self.assertFalse(any(action=='capture' for action,_ in self.cloud.calls))
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(self.box.flush()['acknowledged'],1)

    def test_corrupt_local_row_is_isolated_not_batch_exception(self):
        ids=self.stage(['bad0','good'])
        with self.box._db() as db:db.execute('update captures set envelope=? where id=?',('{broken',ids[0]))
        response=self.box.flush()
        self.assertEqual((response['pending'],response['quarantined'],response['acknowledged']),(1,1,1))
        self.assertIn('invalid_local_capture',response['errors'])
        self.assertFalse(any(value.get('capture_id')==ids[0] for action,value in self.cloud.calls))

    def test_false_or_float_epoch_ack_is_not_confirmation(self):
        self.stage(['good'])
        for epoch in (True,1.0):
            class Wrong(FakeCloud):
                def call(self,action,payload=None):
                    value=super().call(action,payload)
                    if value.get('receipt'):value['receipt']={**value['receipt'],'lease_epoch':epoch}
                    return value
            self.box.client=Wrong(self.cloud.lease)
            self.assertEqual(self.box.flush()['acknowledged'],0)
            self.assertEqual(self.box.stats()['pending'],1)

    def test_requeue_validation_is_atomic_and_acknowledged_is_never_reset(self):
        ids=self.stage(['bad0','good']);self.box.flush();before=self.snapshot()
        for invalid in ([],[ids[0],ids[0]],[None],[ids[0],ids[1]]):
            with self.assertRaises(CloudError):self.box.retry_quarantined(invalid)
        self.assertEqual(self.box.stats()['quarantined'],1);self.assertEqual(self.box.stats()['acknowledged'],1)
        self.assertEqual(self.snapshot(),before)

    def test_late_old_error_after_hold_expiry_cannot_poison_ack(self):
        ids=self.stage(['good']);entered=threading.Event();release=threading.Event();failures=[]
        class Delayed(FakeCloud):
            def call(self,action,payload=None):
                if action=='capture':
                    entered.set();release.wait(3);raise CloudError('invalid_capture_record')
                return super().call(action,payload)
        old=CloudOutbox(self.root,Delayed(self.cloud.lease))
        with patch('cloud_sync.time.time',return_value=1000) as clock:
            def first():
                try:old.flush()
                except BaseException as error:failures.append(error)
            thread=threading.Thread(target=first);thread.start();self.assertTrue(entered.wait(3))
            self.assertEqual(self.box.flush()['acknowledged'],0)
            clock.return_value=1091
            self.assertEqual(self.box.flush()['acknowledged'],1)
            release.set();thread.join(3);self.assertFalse(thread.is_alive());self.assertEqual(failures,[])
        self.assertEqual((self.box.stats()['pending'],self.box.stats()['quarantined'],self.box.stats()['errors']),(0,0,[]))
        with self.box._db() as db:
            self.assertEqual(db.execute('select state,error from captures where id=?',(ids[0],)).fetchone(),('acknowledged',None))

    def test_worker_never_finishes_or_dispatches_when_isolated_records_remain(self):
        self.stage(['bad0','bad1','bad2','bad3','good']);actions=[]
        def runner(action,payload):actions.append(action);raise AssertionError('source must not dispatch')
        worker=CloudWorker(self.root,self.cloud,runner)
        worker._save({'phase':'delivering','lease':self.cloud.lease,'outcome':'completed','api_attempts':3,'sequence':1,'local_run_id':__import__('uuid').uuid4().__str__()})
        result=worker.tick()
        self.assertEqual(result['state'],'delivery_pending')
        self.assertEqual((result['pending'],result['quarantined']),(5,4))
        # The released slot may poll new claims, without finishing the old pending run.
        with patch.object(self.cloud,'call',side_effect=lambda action,payload=None: {'lease':None} if action=='claim' else FakeCloud.call(self.cloud,action,payload)):
            self.assertEqual(worker.tick()['state'],'delivery_pending')
            self.assertEqual(worker.outbox.stats()['acknowledged'],1)
            for _ in range(3):self.assertEqual(worker.tick()['state'],'idle')
        self.assertFalse(actions);self.assertFalse(any(action=='finish' for action,_ in self.cloud.calls))
        self.cloud.fixed=True;worker.outbox.retry_quarantined(result['quarantined_capture_ids'])
        self.assertEqual(worker.tick()['state'],'finished')
        self.assertEqual(sum(action=='finish' for action,_ in self.cloud.calls),1)
        self.assertFalse(actions)


if __name__=='__main__':unittest.main()
