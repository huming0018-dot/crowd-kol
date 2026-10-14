"""Source slot release regressions: private temporary SQLite and deterministic substitutes."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import mc_runner
from cloud_sync import CloudError,CloudWorker
from test_cloud_sync import FakeCloud,lease,row,uid
from test_cloud_outbox_retry import PoisonCloud


class DeferredCloud(PoisonCloud):
    lose_defer=False
    role='worker'
    def call(self,action,payload=None):
        if action=='claim':
            self.calls.append((action,payload));return {'lease':None}
        result=super().call(action,payload)
        if action=='delivery_defer' and self.lose_defer:
            self.lose_defer=False;raise CloudError('cloud_outcome_unknown')
        return result


class PendingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.cloud=DeferredCloud();self.actions=[]
        self.worker=CloudWorker(self.root,self.cloud,lambda action,payload:self.actions.append(action))
        self.ids=self.worker.outbox.stage_imported([{**row(),'content_id':'bad0'},{**row(),'content_id':'good'}],self.cloud.lease)
        self.worker._save({'phase':'delivering','lease':self.cloud.lease,'local_run_id':uid(),'outcome':'completed','api_attempts':3})
    def tearDown(self):self.temp.cleanup()
    def owner(self,desired='running',**changes):
        outer=self
        class Owner:
            role='owner'
            calls=[]
            def call(self,action,payload):
                self.calls.append((action,payload))
                outer.assertEqual(action,'task_status')
                l=outer.cloud.lease
                return {'task':{'task_id':l['task_id'],'desired_state':desired,'children':[{'child_id':l['child_id'],'worker_id':l['worker_id'],'lease_epoch':l['lease_epoch'],'state':'delivery_pending','runs':[l['run_id']],**changes}]}}
        return Owner()
    def immutable(self):
        with self.worker.outbox._db() as db:return db.execute('select id,run_id,envelope,digest from captures order by id').fetchall()
    def test_known_terminal_parks_restarts_polls_next_slot_and_owner_repairs_same_bytes(self):
        original=self.immutable();first=self.worker.tick();self.assertEqual(first['state'],'delivery_pending')
        state=mc_runner.read(self.worker.path);self.assertEqual(state['phase'],'idle');self.assertEqual(len(state['pending_deliveries']),1)
        self.assertEqual(self.worker.outbox.stats()['pending'],1)
        restored=CloudWorker(self.root,self.cloud,lambda action,payload:self.actions.append(action));self.assertEqual(restored.tick()['state'],'idle')
        status=restored.delivery_status();self.assertEqual(status['schema'],'crowd-delivery-status-v1');self.assertTrue(status['groups'][0]['retry_allowed'])
        self.assertNotIn('lease',str(status));self.assertNotIn('envelope',str(status))
        calls=len(self.cloud.calls);self.cloud.fixed=True
        response=restored.retry_delivery([self.ids[0]],self.owner())
        self.assertEqual(response,{'schema':'crowd-delivery-retry-v1','accepted':True,'state':'queued','requeued_capture_ids':[self.ids[0]]})
        self.assertEqual(len(self.cloud.calls),calls);self.assertEqual(self.immutable(),original)
        self.assertEqual(restored.tick()['state'],'finished');self.assertEqual(restored.outbox.stats()['pending'],0)
        self.assertEqual(self.immutable(),original);self.assertEqual(self.actions,[])
        self.assertEqual(sum(a=='delivery_defer' for a,_ in self.cloud.calls),1)
        self.assertEqual(sum(a=='finish' for a,_ in self.cloud.calls),1)
    def test_unknown_defer_ack_replays_exact_manifest_and_never_claims_before_confirmation(self):
        self.cloud.lose_defer=True;self.assertEqual(self.worker.tick()['error'],'cloud_outcome_unknown')
        saved=mc_runner.read(self.worker.path);self.assertEqual(saved['phase'],'deferring_delivery')
        restored=CloudWorker(self.root,self.cloud,lambda *args:self.fail('source'))
        self.assertEqual(restored.tick()['state'],'delivery_pending')
        payloads=[p for a,p in self.cloud.calls if a=='delivery_defer'];self.assertEqual(payloads[0],payloads[1])
        self.assertFalse(any(a in ('claim','finish') for a,_ in self.cloud.calls));self.assertEqual(self.actions,[])
    def test_unknown_source_is_never_parked_or_retryable(self):
        state=mc_runner.read(self.worker.path);state['outcome']='unknown';self.worker._save(state)
        self.assertEqual(self.worker.tick()['state'],'delivering')
        self.assertFalse(self.worker.delivery_status()['groups'][0]['retry_allowed'])
        with self.assertRaisesRegex(CloudError,'delivery_retry_denied'):self.worker.retry_delivery([self.ids[0]],self.owner())
        self.assertFalse(any(a in ('delivery_defer','claim','finish') for a,_ in self.cloud.calls))
    def test_owner_pause_stop_and_wrong_binding_preserve_quarantine(self):
        self.worker.tick();before=self.immutable()
        for desired in ('paused','stopped'):
            with self.assertRaisesRegex(CloudError,'task_'+desired):self.worker.retry_delivery([self.ids[0]],self.owner(desired))
            self.assertFalse(self.worker.delivery_status()['groups'][0]['retry_allowed'])
            self.assertEqual(self.worker.delivery_status()['groups'][0]['reason'],'task_'+desired)
        for changes in ({'worker_id':uid()},{'lease_epoch':2},{'lease_epoch':True},{'runs':[]}):
            with self.assertRaisesRegex(CloudError,'delivery_retry_denied'):self.worker.retry_delivery([self.ids[0]],self.owner(**changes))
        self.assertEqual(self.immutable(),before);self.assertEqual(self.worker.outbox.stats()['quarantined'],1)
    def test_already_ack_requested_still_schedules_original_finish_not_new_capture(self):
        self.worker.tick();self.cloud.fixed=True;self.worker.outbox.retry_quarantined([self.ids[0]])
        self.worker.outbox.flush();captures=sum(a=='capture' for a,_ in self.cloud.calls)
        response=self.worker.retry_delivery([self.ids[0]],self.owner());self.assertEqual(response['requeued_capture_ids'],[])
        self.assertEqual(self.worker.tick()['state'],'finished')
        self.assertEqual(sum(a=='capture' for a,_ in self.cloud.calls),captures)
    def test_malformed_cross_run_and_non_owner_retry_fail_before_network(self):
        self.worker.tick();other=lease();more=self.worker.outbox.stage_imported([row()],other)
        for ids in ([],[None],[self.ids[0],self.ids[0]]):
            with self.assertRaisesRegex(CloudError,'invalid_capture_retry'):self.worker.retry_delivery(ids,self.owner())
        with self.assertRaisesRegex(CloudError,'delivery_retry_run_mismatch'):self.worker.retry_delivery([self.ids[0],more[0]],self.owner())
        with self.assertRaisesRegex(CloudError,'principal_denied'):self.worker.retry_delivery([self.ids[0]],self.cloud)
        self.assertEqual(self.worker.outbox.stats()['quarantined'],1)
    def test_ready_parked_delivery_never_replaces_current_source_context(self):
        self.worker.tick();self.worker.retry_delivery([self.ids[0]],self.owner())
        state=mc_runner.read(self.worker.path);current=lease();state.update(phase='running',lease=current,local_run_id=uid());self.worker._save(state)
        with patch.object(self.worker,'_heartbeat',return_value=current),patch.object(self.worker,'_runner',return_value={'state':'running'}):
            self.assertEqual(self.worker.tick()['state'],'running')
        after=mc_runner.read(self.worker.path);self.assertEqual(after['lease']['run_id'],current['run_id']);self.assertEqual(len(after['pending_deliveries']),1)
        self.assertFalse(any(a=='finish' for a,_ in self.cloud.calls))

    def test_paused_delivery_waits_thirty_seconds_then_continues_original_when_owner_resumes(self):
        with patch('cloud_sync.time.time',return_value=1000) as clock:
            self.cloud.lease.update(desired_state='paused',may_dispatch=False)
            self.assertEqual(self.worker.tick()['state'],'delivery_pending')
            # Known terminal source can release its slot even while Owner pauses delivery.
            self.assertEqual(self.worker.tick()['state'],'delivery_pending')
            calls=len(self.cloud.calls)
            self.assertEqual(self.worker.tick()['state'],'idle')
            self.assertEqual(len(self.cloud.calls)-calls,1)  # claim only; no useless renewal
            self.cloud.fixed=True;self.cloud.lease['desired_state']='running';clock.return_value=1031
            self.assertEqual(self.worker.tick()['state'],'delivery_pending')
            self.assertTrue(self.worker.delivery_status()['groups'][0]['retry_allowed'])
            self.worker.retry_delivery([self.ids[0]],self.owner())
            self.assertEqual(self.worker.tick()['state'],'finished')
        self.assertEqual(self.actions,[])

    def test_quarantined_tail_does_not_starve_unattempted_good_record_after_parking(self):
        self.worker.outbox.stage_imported([{**row(),'content_id':value} for value in ('bad1','bad2','bad3','good2','good3')],self.cloud.lease)
        first=self.worker.tick();self.assertEqual(first['state'],'delivery_pending')
        for _ in range(3):self.worker.tick()
        stats=self.worker.outbox.stats();self.assertEqual((stats['quarantined'],stats['pending'],stats['acknowledged']),(4,4,3))
        before=len(self.cloud.calls)
        for _ in range(3):self.worker.tick()
        self.assertFalse(any(a in ('heartbeat','delivery_resume','finish') for a,_ in self.cloud.calls[before:]))

    def test_lost_finish_ack_replays_original_finish_after_cloud_is_terminal(self):
        self.worker.tick();self.cloud.fixed=True;self.worker.retry_delivery([self.ids[0]],self.owner())
        original=self.cloud.call;lost=[False]
        def call(action,payload=None):
            result=original(action,payload)
            if action=='finish' and not lost[0]:
                lost[0]=True;self.cloud.lease['state']='completed';raise CloudError('cloud_outcome_unknown')
            if action=='delivery_resume' and self.cloud.lease['state']=='completed':result['may_deliver']=False
            return result
        with patch.object(self.cloud,'call',side_effect=call):
            self.assertEqual(self.worker.tick()['error'],'cloud_outcome_unknown')
            restored=CloudWorker(self.root,self.cloud,lambda *args:self.fail('source'))
            self.assertEqual(restored.tick()['state'],'finished')
        finishes=[p for a,p in self.cloud.calls if a=='finish'];self.assertEqual(len(finishes),2);self.assertEqual(finishes[0],finishes[1])
        self.assertEqual(self.worker.outbox.stats()['pending'],0)

    def test_empty_or_wrong_finish_ack_retains_original_finishing_context(self):
        self.worker.tick();self.cloud.fixed=True;self.worker.retry_delivery([self.ids[0]],self.owner())
        original=self.cloud.call
        for invalid in ({},{'task':{}},{'task':{'task_id':uid(),'children':[]}}):
            with patch.object(self.cloud,'call',side_effect=lambda action,payload=None: invalid if action=='finish' else original(action,payload)):
                self.assertEqual(self.worker.tick()['error'],'invalid_cloud_ack')
                saved=mc_runner.read(self.worker.path);self.assertEqual(saved['phase'],'finishing');self.assertIn('delivery_manifest',saved)
        self.assertEqual(self.worker.tick()['state'],'finished')
        self.assertEqual(self.actions,[])

    def test_deferring_delivery_is_visible_health_phase_with_no_lease_disclosure(self):
        self.cloud.lose_defer=True;self.worker.tick()
        events=self.worker.workflow_events.status()
        self.assertTrue(any(v.get('phase')=='deferring_delivery' for v in events['events']))
        self.assertNotIn('manifest_hash',str(events));self.assertNotIn('capture_refs',str(events))


if __name__=='__main__':unittest.main()
