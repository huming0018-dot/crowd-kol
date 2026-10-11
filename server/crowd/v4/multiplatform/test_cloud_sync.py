import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, Mock
import uuid

from cloud_sync import CloudClient, CloudError, CloudOutbox, CloudOwnerAdapter, CloudWorker, canonical, _hash, _strict_json
import mc_runner


def uid():
    return str(uuid.uuid4())


def lease(basis='live_capture'):
    return {'task_id':uid(),'child_id':uid(),'worker_id':uid(),'run_id':uid(),'lease_epoch':1,
        'platform':'xhs','delivery_basis':basis,'may_dispatch':True,'state':'running','desired_state':'running',
        'request':{'platform':'xhs','mode':'detail','targets':['0123456789abcdef01234567'],
                   'max_items':1,'max_api_requests':5,'comments':False,'purpose':'noncommercial_research'},
        'record_refs':[{'content_id':'0123456789abcdef01234567','kind':'content'}]}


def row():
    return {'kind':'content','platform':'xiaohongshu','content_id':'0123456789abcdef01234567',
            'title':'隔离标题','body':'不访问真实来源','source_kind':'mediacrawler_api','reward_eligible':False}


class FakeCloud:
    def __init__(self, value=None):
        self.lease = value or lease()
        self.calls = []
        self.receipts = {}
        self.lose_capture = False
        self.lose_claim = False
        self.bad_ack = False
        self.fail_heartbeat = False

    def call(self, action, payload=None):
        payload = payload or {}
        self.calls.append((action, payload))
        if action == 'claim':
            if self.lose_claim:
                self.lose_claim = False
                raise CloudError('cloud_outcome_unknown')
            return {'lease':None if self.lease['platform'] in payload.get('unavailable_platforms',[]) else self.lease}
        if action == 'heartbeat':
            if self.fail_heartbeat:
                raise CloudError('cloud_outcome_unknown')
            return {'lease':self.lease}
        if action == 'receipt':
            return {'receipt':self.receipts.get(payload['capture_id'])}
        if action == 'capture':
            env=payload['envelope']
            ack={k:env[k] for k in ('capture_id','task_id','child_id','run_id','lease_epoch')}
            ack.update(envelope_hash=payload['envelope_hash'],status='received',source_kind='machine_api',reward_eligible=False)
            self.receipts[env['capture_id']]=ack
            if self.lose_capture:
                self.lose_capture=False
                raise CloudError('cloud_outcome_unknown')
            return {'receipt':{**ack,'envelope_hash':'0'*64} if self.bad_ack else ack}
        if action == 'finish':
            expected=dict(payload);expected.pop('finish_hash')
            assert payload['finish_hash']==_hash('crowd-machine-finish-v1', expected)
            assert all(i in self.receipts for i in payload['capture_ids'])
            return {'task':{'state':payload['outcome']}}
        if action == 'resume_login':
            self.lease = {**self.lease, 'run_id':uid(), 'lease_epoch':self.lease['lease_epoch']+1}
            return {'resumed':True}
        if action == 'task_status':
            return {'task':{'revision':2}}
        return {'task':payload,'tasks':[]}


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name).resolve()
        self.cloud=FakeCloud()
        self.actions=[]
        self.local_id=uid()

    def tearDown(self):
        self.temp.cleanup()

    def runner(self, action, payload):
        self.actions.append((action,payload))
        if action=='start':return {'ok':True,'result':{'run_id':self.local_id}}
        if action=='status':return {'ok':True,'result':{'state':'completed','api_attempts':2}}
        if action=='import':return {'ok':True,'result':{'records':[row()]}}
        if action=='stop':return {'ok':True,'result':{'state':'stopped'}}
        raise ValueError('unexpected_action')

    def test_delivery_renews_each_request_and_batches_without_expiring_or_redispatch(self):
        class SlowCloud(FakeCloud):
            clock = 0
            expires = 90
            def call(self, action, payload=None):
                if action == 'heartbeat':
                    self.expires = self.clock + 90
                elif action in ('receipt','capture','finish'):
                    self.clock += 20
                    if self.clock >= self.expires:
                        raise CloudError('cloud_outcome_unknown')
                return super().call(action,payload)
        cloud=SlowCloud();records=[{**row(),'content_id':str(i)} for i in range(9)]
        actions=[]
        def runner(action,payload):
            actions.append(action)
            self.assertEqual(action,'import')
            cloud.clock += 35
            return {'records':records}
        worker=CloudWorker(self.root,cloud,runner)
        worker._save({'phase':'importing','lease':cloud.lease,'local_run_id':self.local_id,
                      'outcome':'completed','api_attempts':3,'sequence':2})
        first=worker.tick();self.assertEqual(first['state'],'delivering')
        self.assertEqual((first['pending'],first['acknowledged']),(5,4))
        with worker.outbox._db() as db:
            original=db.execute('select id,envelope,digest from captures order by rowid').fetchall()
        self.assertEqual(worker.tick()['state'],'delivering')
        self.assertEqual(worker.tick()['state'],'finished')
        with worker.outbox._db() as db:
            self.assertEqual(original,db.execute('select id,envelope,digest from captures order by rowid').fetchall())
        self.assertEqual(actions,['import']);self.assertEqual(len(cloud.receipts),9)
        self.assertEqual(sum(a=='capture' for a,_ in cloud.calls),9)
        finish=next(p for a,p in cloud.calls if a=='finish')
        self.assertEqual(finish['api_attempts'],3);self.assertEqual(len(finish['capture_ids']),9)
        self.assertFalse(any(a in ('claim','resume_login') for a,_ in cloud.calls))
        sequences=[p['sequence'] for a,p in cloud.calls if a=='heartbeat']
        self.assertEqual(sequences,list(range(3,3+len(sequences))))
        for index,(action,payload) in enumerate(cloud.calls):
            if action in ('receipt','capture','finish'):
                self.assertEqual(cloud.calls[index-1][0],'heartbeat')
                self.assertEqual((payload['run_id'],payload['lease_epoch']),(cloud.lease['run_id'],1))

    def test_delivery_expired_or_owner_stopped_is_history_only_and_lost_ack_replays(self):
        for desired in ('running','stopped'):
            with self.subTest(desired=desired),tempfile.TemporaryDirectory() as directory:
                cloud=FakeCloud();cloud.lose_capture=True
                worker=CloudWorker(Path(directory),cloud,self.runner)
                worker.outbox.stage_imported([row()],cloud.lease)
                cloud.lease.update(may_dispatch=False,state='unknown',desired_state=desired)
                worker._save({'phase':'delivering','lease':cloud.lease,'local_run_id':self.local_id,
                              'outcome':'completed','api_attempts':3})
                self.assertEqual(worker.tick()['state'],'delivering')
                self.assertTrue(mc_runner.read(worker.path)['delivery_only'])
                restored=CloudWorker(Path(directory),cloud,self.runner)
                self.assertEqual(restored.tick()['state'],'finished')
                self.assertEqual(sum(a=='capture' for a,_ in cloud.calls),1)
                self.assertEqual(cloud.lease['state'],'unknown')
                self.assertFalse(any(a in ('claim','resume_login') for a,_ in cloud.calls))
        self.assertEqual(self.actions,[])

    def test_delivery_heartbeat_failure_blocks_remote_writes_and_recovers_same_outbox(self):
        worker=CloudWorker(self.root,self.cloud,self.runner)
        worker.outbox.stage_imported([row()],self.cloud.lease)
        worker._save({'phase':'delivering','lease':self.cloud.lease,'local_run_id':self.local_id,
                      'outcome':'completed','api_attempts':3})
        self.cloud.fail_heartbeat=True
        self.assertEqual(worker.tick()['error'],'cloud_delivery_lease_unavailable')
        self.assertFalse(any(a in ('capture','receipt','finish') for a,_ in self.cloud.calls))
        self.assertEqual(worker.outbox.stats()['pending'],1)
        self.cloud.fail_heartbeat=False
        restored=CloudWorker(self.root,self.cloud,self.runner)
        self.assertEqual(restored.tick()['state'],'finished');self.assertEqual(self.actions,[])

    def test_delivery_keepalive_renews_during_blocked_local_import(self):
        cloud=FakeCloud();renewed=threading.Event();original=cloud.call
        def call(action,payload=None):
            value=original(action,payload)
            if action=='heartbeat' and sum(a=='heartbeat' for a,_ in cloud.calls)>=2:
                renewed.set()
            return value
        cloud.call=call
        def runner(action,payload):
            self.assertEqual(action,'import')
            self.assertTrue(renewed.wait(2))
            return {'records':[row()]}
        worker=CloudWorker(self.root,cloud,runner)
        worker._save({'phase':'importing','lease':cloud.lease,'local_run_id':self.local_id,
                      'outcome':'completed','api_attempts':3})
        with patch('cloud_sync.DELIVERY_RENEW_SECONDS',0.01):
            self.assertEqual(worker.tick()['state'],'finished')
        self.assertFalse(any(t.name=='cloud-delivery-lease' for t in threading.enumerate()))

    def test_system_stop_callers_preserve_typed_cause_across_idle_and_restarts(self):
        for trigger,reason in [('error','cloud_controller_error'),('denied','cloud_dispatch_denied'),
                               ('close','cloud_worker_shutdown'),('owner','owner_stop_requested')]:
            with self.subTest(trigger=trigger),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);rid=uid();run=root/'runs'/rid;(run/'output').mkdir(parents=True)
                mc_runner.write(run/'manifest.json',{'request':{'timeout_seconds':180}})
                mc_runner.write(run/'status.json',{'state':'running','updated_at':time.time()})
                mc_runner.write(run/'phase.json',{'phase':'comments','api_attempts':2})
                cloud=FakeCloud();cloud.fail_heartbeat=trigger=='error'
                if trigger in ('denied','owner'):cloud.lease['may_dispatch']=False
                if trigger=='owner':cloud.lease['desired_state']='stopped'
                original=cloud.call
                def call(action,payload=None):
                    return {'lease':None} if action=='claim' else original(action,payload)
                cloud.call=call;actions=[]
                def runner(action,payload):
                    actions.append((action,payload))
                    if action=='stop':value=mc_runner.stop(root,payload)
                    elif action=='status':value=mc_runner.status(root,payload)
                    elif action=='import':value={'records':[row()]}
                    else:raise AssertionError('no source dispatch')
                    return {'ok':True,'result':value}
                worker=CloudWorker(root,cloud,runner)
                worker._save({'phase':'running','lease':cloud.lease,'local_run_id':rid,'sequence':2})
                worker.close() if trigger=='close' else worker.tick()
                marker=mc_runner.read(run/'stop.json');self.assertEqual(marker['reason'],reason)
                self.assertEqual(marker['origin'],'cloud_worker');self.assertEqual(marker['lease_epoch'],1)
                self.assertEqual(marker['heartbeat_sequence'],2 if trigger=='close' else 3)
                original_marker=(run/'stop.json').read_bytes()
                child=Mock();child.poll.return_value=None;child.wait.return_value=-15
                with patch.object(mc_runner.subprocess,'Popen',return_value=child),patch.object(mc_runner.os,'killpg'),patch.object(mc_runner.os,'close'):
                    mc_runner.worker(root,root,rid,99)
                cloud.fail_heartbeat=False;worker.tick();worker.tick()
                self.assertEqual(mc_runner.read(worker.path)['phase'],'idle')
                self.assertEqual(worker.status()['last_stop']['reason'],reason)
                restored=CloudWorker(root,cloud,runner)
                self.assertEqual(restored.status()['last_stop']['local_run_id'],rid)
                self.assertEqual(restored.status()['last_stop']['reason'],reason)
                self.assertFalse(any(a=='start' for a,_ in actions));self.assertEqual((run/'stop.json').read_bytes(),original_marker)

    def test_diagnostic_disk_failure_still_stops_and_transport_unknown_blocks_restart(self):
        for stop_fails in (False,True):
            with self.subTest(stop_fails=stop_fails):
                cloud=FakeCloud();cloud.fail_heartbeat=True;actions=[]
                def runner(action,payload):
                    actions.append((action,payload))
                    if action=='stop' and stop_fails:raise RuntimeError('secret_cookie_value')
                    return {'ok':True,'result':{'state':'running','stop_requested':action=='stop'}}
                worker=CloudWorker(self.root,cloud,runner)
                worker._save({'phase':'running','lease':cloud.lease,'local_run_id':self.local_id,'sequence':2})
                with patch.object(worker,'_save',side_effect=OSError('secret_cookie_value')):
                    result=worker.tick();self.assertEqual(len(actions),1)
                    self.assertEqual(actions[0][1]['run_id'],self.local_id)
                    self.assertEqual(actions[0][1]['reason'],'cloud_controller_error')
                    summary=worker.status();self.assertEqual(summary['last_stop']['persistence'],'write_failed')
                    if stop_fails:
                        self.assertEqual(result['state'],'local_stop_unknown')
                        self.assertEqual(summary['last_stop']['delivery'],'request_unknown')
                        worker.tick();self.assertEqual(len(actions),1)
                    self.assertNotIn('secret_cookie_value',json.dumps(summary));self.assertFalse(any(a=='start' for a,_ in actions))
                worker._save(mc_runner.read(worker.path))
                restored=CloudWorker(self.root,cloud,runner)
                self.assertEqual(restored.status()['last_stop']['persistence'],'write_failed')
                if stop_fails:self.assertEqual(mc_runner.read(worker.path)['phase'],'local_stop_unknown')

    def test_unknown_error_text_cannot_become_stop_diagnostic_or_ui_error(self):
        cloud=FakeCloud();worker=CloudWorker(self.root,cloud,self.runner)
        worker._save({'phase':'running','lease':cloud.lease,'local_run_id':self.local_id})
        with patch.object(cloud,'call',side_effect=ValueError('secret_cookie_value')):
            result=worker.tick()
        self.assertEqual(result['error'],'cloud_worker_failed')
        self.assertEqual(self.actions[-1][1]['error_code'],'cloud_worker_failed')
        self.assertNotIn('secret_cookie_value',json.dumps(mc_runner.read(worker.path)))
        self.assertNotIn('secret_cookie_value',json.dumps(worker.status()))

    def test_existing_user_marker_keeps_exact_context_without_stale_system_metadata(self):
        rid=uid();run=self.root/'runs'/rid;run.mkdir(parents=True)
        mc_runner.write(run/'status.json',{'state':'running','updated_at':time.time()})
        mc_runner.stop(self.root,{'run_id':rid});original=(run/'stop.json').read_bytes()
        def runner(action,payload):
            self.assertEqual(action,'stop');return {'ok':True,'result':mc_runner.stop(self.root,payload)}
        worker=CloudWorker(self.root,self.cloud,runner)
        state={'phase':'running','lease':self.cloud.lease,'local_run_id':rid,'sequence':4}
        worker._stop_local(state,'cloud_controller_error','cloud_outcome_unknown')
        value=worker.status()['last_stop'];self.assertEqual((value['origin'],value['reason']),('user','user_stop'))
        self.assertNotIn('error_code',value);self.assertNotIn('desired_state',value);self.assertNotIn('lease_epoch',value)
        self.assertEqual((run/'stop.json').read_bytes(),original)

    def test_canonical_cross_language_and_strict_numbers(self):
        self.assertEqual(canonical({'😀':1,'\ue000':2,'line':'\n\t','a':-0.0}),'{"a":0,"line":"\\u000a\\u0009","":2,"😀":1}')
        self.assertEqual(canonical(_strict_json('{"a":1.0}')), '{"a":1}')
        for text in ('{"x":1.0000000000000001}','{"x":9007199254740992}','{"x":1,"x":2}','{"x":"\\ud800"}'):
            with self.assertRaises(CloudError):_strict_json(text)
        many=json.dumps({'tasks':[{'children':[{'state':'completed','contents':1} for _ in range(7)]} for _ in range(200)]})
        self.assertEqual(len(_strict_json(many,max_nodes=100000)['tasks']),200)
        with self.assertRaises(CloudError):_strict_json(many)

    def test_validation_failure_finishes_without_source_or_stranding_worker(self):
        worker = CloudWorker(self.root, self.cloud, self.runner)
        with patch('cloud_sync.mc_runner.validate', side_effect=mc_runner.BridgeError('media_not_supported_by_upstream')):
            self.assertEqual(worker.tick()['state'], 'finished')
        self.assertEqual(self.actions, [])
        finish = next(p for a,p in self.cloud.calls if a == 'finish')
        self.assertEqual((finish['outcome'], finish['api_attempts'], finish['capture_ids']), ('failed', 0, []))
        state = mc_runner.read(worker.path)
        self.assertEqual(state['phase'], 'idle')
        self.assertEqual(state['last_validation_error'], 'invalid_local_task')

    def test_validation_finish_unknown_retries_finish_without_source(self):
        worker = CloudWorker(self.root, self.cloud, self.runner)
        original = self.cloud.call
        lost = [True]
        def call(action, payload=None):
            if action == 'finish' and lost:
                lost.pop()
                raise CloudError('cloud_outcome_unknown')
            return original(action, payload)
        self.cloud.call = call
        with patch('cloud_sync.mc_runner.validate', side_effect=mc_runner.BridgeError('invalid_budget')):
            self.assertEqual(worker.tick()['error'], 'cloud_outcome_unknown')
        self.assertEqual(mc_runner.read(worker.path)['phase'], 'finishing')
        self.assertEqual(worker.tick()['state'], 'finished')
        self.assertEqual(self.actions, [])

    def test_expired_pre_dispatch_reconciliation_survives_lost_ack(self):
        worker = CloudWorker(self.root, self.cloud, self.runner)
        state = {'phase':'authorized','claim_id':uid(),'lease':self.cloud.lease,'sequence':1,
                 'waiting_logins':[]}
        worker._save(state)
        self.cloud.lease.update(may_dispatch=False,state='unknown')
        original = self.cloud.call
        reconciliations = []
        def call(action, payload=None):
            if action == 'reconcile_no_dispatch':
                reconciliations.append(payload)
                if len(reconciliations) == 1:
                    self.cloud.lease['state'] = 'waiting'
                    raise CloudError('cloud_outcome_unknown')
                return {'reconciled':True,'replayed':True,
                        **{k:payload[k] for k in ('claim_id','run_id','lease_epoch')},
                        'worker_id':self.cloud.lease['worker_id']}
            return original(action,payload)
        self.cloud.call = call
        self.assertEqual(worker.tick()['error'],'cloud_outcome_unknown')
        self.assertEqual(mc_runner.read(worker.path)['phase'],'reconciling_no_dispatch')
        recreated = CloudWorker(self.root,self.cloud,self.runner)
        self.assertEqual(recreated.tick()['state'],'reconciled_no_dispatch')
        self.assertEqual(reconciliations[0],reconciliations[1])
        self.assertEqual(self.actions,[])
        self.assertFalse(any(action == 'finish' for action,_ in self.cloud.calls))

    def test_uncertain_dispatch_is_never_reconciled_as_no_dispatch(self):
        worker = CloudWorker(self.root,self.cloud,self.runner)
        worker._save({'phase':'dispatching','lease':self.cloud.lease,'sequence':1,'waiting_logins':[]})
        self.assertEqual(worker.tick()['error'],'source_outcome_unknown')
        self.assertEqual(self.cloud.calls,[])
        self.assertEqual(self.actions,[])

    def test_outbox_lost_ack_queries_receipt_without_retransmit(self):
        outbox=CloudOutbox(self.root,self.cloud)
        ids=outbox.stage_imported([row()],self.cloud.lease)
        self.cloud.lose_capture=True
        self.assertEqual(outbox.flush()['pending'],1)
        self.assertEqual(outbox.flush()['acknowledged'],1)
        self.assertEqual(sum(a=='capture' for a,_ in self.cloud.calls),1)
        self.assertEqual(outbox.stage_imported([row()],self.cloud.lease),ids)
        self.assertEqual(outbox.stats()['acknowledged'],1)
        self.assertEqual(outbox.path.stat().st_mode & 0o777,0o600)

    def test_bad_ack_remains_pending(self):
        outbox=CloudOutbox(self.root,self.cloud)
        outbox.stage_imported([row()],self.cloud.lease)
        self.cloud.bad_ack=True
        result=outbox.flush()
        self.assertEqual(result['pending'],1)
        self.assertEqual(result['errors'],['invalid_cloud_ack'])

    def test_projection_excludes_original_runtime_path_and_evaluations(self):
        outbox=CloudOutbox(self.root,self.cloud)
        outbox.stage_imported([{**row(),'source':{'path':'/private/local'},'owner_evaluations':['private']}],self.cloud.lease)
        with outbox._db() as db:encoded=db.execute('select envelope from captures').fetchone()[0]
        self.assertNotIn('/private/local',encoded)
        self.assertNotIn('owner_evaluations',encoded)
        with self.assertRaises(ValueError):outbox.stage_imported([{**row(),'metrics':{'token':'bad'}}],self.cloud.lease)

    def test_existing_saved_never_starts_source(self):
        self.cloud.lease=lease('existing_saved')
        worker=CloudWorker(self.root,self.cloud,self.runner,existing_reader=lambda _:[row()])
        self.assertEqual(worker.tick()['state'],'finished')
        self.assertEqual(self.actions,[])
        self.assertEqual(worker.outbox.stats()['acknowledged'],1)
        finish=next(p for a,p in self.cloud.calls if a=='finish')
        self.assertEqual(finish['api_attempts'],0)

    def test_existing_saved_rejects_other_content(self):
        self.cloud.lease=lease('existing_saved')
        worker=CloudWorker(self.root,self.cloud,self.runner,existing_reader=lambda _:[{**row(),'content_id':'other'}])
        self.assertEqual(worker.tick()['error'],'existing_saved_selection_mismatch')
        self.assertEqual(self.actions,[])

    def test_live_lifecycle_commits_before_start_and_delivers(self):
        def runner(action,payload):
            if action=='start':
                self.assertEqual(json.loads((self.root/'cloud-worker/state.json').read_text())['phase'],'dispatching')
            return self.runner(action,payload)
        worker=CloudWorker(self.root,self.cloud,runner)
        self.assertEqual(worker.tick()['state'],'finished')
        self.assertEqual([a for a,_ in self.actions],['start','status','import'])
        self.assertEqual(worker.outbox.stats()['acknowledged'],1)

    def test_lost_start_response_never_restarts(self):
        def runner(action,payload):
            self.actions.append((action,payload))
            if action=='start':raise OSError('response lost')
            return {'ok':True,'result':{}}
        worker=CloudWorker(self.root,self.cloud,runner)
        self.assertEqual(worker.tick()['error'],'runner_outcome_unknown')
        worker=CloudWorker(self.root,self.cloud,runner)
        self.assertEqual(worker.tick()['state'],'dispatching')
        self.assertEqual(sum(a=='start' for a,_ in self.actions),1)

    def test_lost_claim_uses_same_request_uuid(self):
        self.cloud.lose_claim=True
        worker=CloudWorker(self.root,self.cloud,self.runner)
        self.assertEqual(worker.tick()['error'],'cloud_outcome_unknown')
        self.assertEqual(worker.tick()['state'],'finished')
        claims=[p['claim_id'] for a,p in self.cloud.calls if a=='claim']
        self.assertEqual(claims[0],claims[1])

    def test_owner_stop_before_dispatch_never_starts(self):
        self.cloud.lease['may_dispatch']=False
        worker=CloudWorker(self.root,self.cloud,self.runner)
        self.assertEqual(worker.tick()['state'],'finished')
        self.assertEqual(self.actions,[])
        self.assertEqual(next(p for a,p in self.cloud.calls if a=='finish')['outcome'],'unknown')

    def test_lost_capture_response_does_not_repeat_source(self):
        self.cloud.lose_capture=True
        worker=CloudWorker(self.root,self.cloud,self.runner)
        self.assertEqual(worker.tick()['state'],'delivering')
        self.assertEqual(worker.tick()['state'],'finished')
        self.assertEqual(sum(a=='start' for a,_ in self.actions),1)
        self.assertEqual(sum(a=='capture' for a,_ in self.cloud.calls),1)

    def test_heartbeat_failure_stops_active_owned_run(self):
        def runner(action,payload):
            if action=='status':return {'ok':True,'result':{'state':'collecting'}}
            return self.runner(action,payload)
        worker=CloudWorker(self.root,self.cloud,runner)
        self.assertEqual(worker.tick()['state'],'running')
        self.cloud.fail_heartbeat=True
        self.assertEqual(worker.tick()['error'],'cloud_outcome_unknown')
        self.assertEqual(self.actions[-1][0],'stop')
        self.assertEqual(sum(a=='start' for a,_ in self.actions),1)

    def test_renewed_authorization_status_read_failure_never_stops_or_restarts_source(self):
        for failure in ('timeout', 'bad_shape', 'unknown_stage', 'non_string_stage'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder:
                cloud=FakeCloud(); actions=[]; local_id=uid(); reads=0
                cloud.lease['request']['max_api_requests']=11
                original_request=json.loads(json.dumps(cloud.lease['request']))
                def runner(action,payload):
                    nonlocal reads
                    actions.append((action,payload))
                    if action=='status':
                        reads+=1
                        if reads==1:
                            if failure=='timeout':raise TimeoutError('secret_cookie_value')
                            if failure=='bad_shape':return {'ok':True,'result':[]}
                            if failure=='non_string_stage':return {'ok':True,'result':{'state':['secret_state']}}
                            return {'ok':True,'result':{'state':'unexpected_secret_state'}}
                        return {'ok':True,'result':{'state':'completed','api_attempts':6}}
                    if action=='import':return {'ok':True,'result':{'records':[row()]}}
                    raise AssertionError('status observation must not dispatch or stop source')
                worker=CloudWorker(Path(folder),cloud,runner)
                worker._save({'phase':'running','lease':cloud.lease,'local_run_id':local_id,'sequence':2})
                result=worker.tick()
                self.assertEqual(result['state'],'running')
                self.assertEqual(result['error'],'runner_status_unavailable')
                self.assertEqual(worker.status()['last_error'],'runner_status_unavailable')
                state=mc_runner.read(worker.path)
                self.assertEqual(state['local_run_id'],local_id)
                self.assertEqual(state['status_read_error'],'runner_status_unavailable')
                self.assertEqual(state['sequence'],3)
                self.assertNotIn('secret',json.dumps(state))
                worker=CloudWorker(Path(folder),cloud,runner)
                self.assertEqual(worker.status()['last_error'],'runner_status_unavailable')
                self.assertEqual(worker.tick()['state'],'finished')
                self.assertIsNone(worker.status()['last_error'])
                self.assertEqual([a for a,_ in actions],['status','status','import'])
                self.assertGreaterEqual(sum(a=='heartbeat' for a,_ in cloud.calls),2)
                self.assertEqual(next(p for a,p in cloud.calls if a=='finish')['api_attempts'],6)
                self.assertEqual(cloud.lease['request'],original_request)
                self.assertFalse(any(a in ('claim','resume_login') for a,_ in cloud.calls))

    def test_status_read_failure_cannot_continue_after_next_renewal_denial(self):
        for revoked in ('unavailable','denied','owner_stop'):
            with self.subTest(revoked=revoked), tempfile.TemporaryDirectory() as folder:
                cloud=FakeCloud();actions=[];local_id=uid()
                def runner(action,payload):
                    actions.append((action,payload))
                    if action=='status':raise TimeoutError('secret_cookie_value')
                    if action=='stop':return {'ok':True,'result':{'stop_requested':True}}
                    raise AssertionError('must not start source')
                worker=CloudWorker(Path(folder),cloud,runner)
                worker._save({'phase':'running','lease':cloud.lease,'local_run_id':local_id,'sequence':2})
                self.assertEqual(worker.tick()['error'],'runner_status_unavailable')
                if revoked=='unavailable':cloud.fail_heartbeat=True
                else:
                    cloud.lease['may_dispatch']=False
                    if revoked=='owner_stop':cloud.lease['desired_state']='stopped'
                worker.tick()
                stop=next(p for a,p in actions if a=='stop')
                self.assertEqual(stop['run_id'],local_id)
                self.assertEqual(stop['reason'],{'unavailable':'cloud_controller_error','denied':'cloud_dispatch_denied','owner_stop':'owner_stop_requested'}[revoked])
                self.assertFalse(any(a=='start' for a,_ in actions))

    def test_login_recovery_binds_same_account_and_run(self):
        session=uid(); account={'generation':2,'account_ref':'f'*64,'identity_status':'authenticated_self_id','state':'logged_out','authorized_for_run':None,'login_verified':True,'verified_at':time.time()}
        def runner(action,payload):
            if action=='status':return {'ok':True,'result':{'state':'login_required','api_attempts':1}}
            if action=='account_status':return {'ok':True,'result':account}
            if action=='import':return {'ok':True,'result':{'records':[]}}
            return self.runner(action,payload)
        worker=CloudWorker(self.root,self.cloud,runner,session_selector=lambda _:session)
        self.assertEqual(worker.tick()['state'],'finished')
        self.assertEqual(worker.tick()['state'],'waiting_login')
        account.update(authorized_for_run=self.local_id,generation=3,state='resumed')
        self.assertEqual(worker.tick()['state'],'waiting_login')
        self.assertEqual(sum(a=='start' for a,_ in self.actions),1)
        account.update(generation=2,login_in_progress=True)
        worker.tick()
        self.assertFalse(any(a=='resume_login' for a,_ in self.cloud.calls))
        account['login_in_progress']=False
        worker.tick();self.assertTrue(any(a=='resume_login' for a,_ in self.cloud.calls))
        p=next(p for a,p in self.cloud.calls if a=='resume_login')
        self.assertEqual(p['local_run_id'],self.local_id)
        self.assertEqual(p['account_ref'],'f'*64)
        self.assertEqual(sum(a=='start' for a,_ in self.actions),2)

    def test_owner_adapter_has_existing_watch_contract(self):
        adapter=CloudOwnerAdapter(self.cloud)
        self.assertTrue(adapter.preview({'idempotency_key':'x'})['ok'])
        adapter.create({'idempotency_key':'x'});adapter.list();adapter.stop(uid());adapter.resume(uid());adapter.close()
        controls=[p for a,p in self.cloud.calls if a=='task_control']
        self.assertEqual([p['desired_state'] for p in controls],['stopped','running'])
        self.assertEqual([p['expected_revision'] for p in controls],[2,2])

    def test_zero_generation_resume_requires_fresh_manual_confirmation_of_original_scope(self):
        session = uid()
        account = {'generation':0, 'account_ref':None, 'state':'logged_out',
                   'identity_status':'unverified', 'authorized_for_run':None,
                   'login_verified':False, 'verified_at':time.time()}
        def runner(action,payload):
            if action=='status':return {'ok':True,'result':{'state':'login_required','api_attempts':1}}
            if action=='account_status':return {'ok':True,'result':account}
            if action=='import':return {'ok':True,'result':{'records':[]}}
            return self.runner(action,payload)
        worker = CloudWorker(self.root,self.cloud,runner,session_selector=lambda _:session)
        worker.tick()
        account.update(state='resumed',login_verified=True,authorized_for_run=self.local_id)
        for changes in ({'identity_status':'session_only_unverified'},
                        {'identity_status':'manually_confirmed_same_account','generation':1},
                        {'generation':0,'verified_at':time.time()-181},
                        {'verified_at':time.time(),'authorized_for_run':uid()},
                        {'authorized_for_run':self.local_id,'account_ref':'f'*64}):
            account.update(changes)
            worker.tick()
            self.assertFalse(any(a=='resume_login' for a,_ in self.cloud.calls))
        account.update(account_ref=None,verified_at=time.time())
        self.cloud.lease['desired_state']='stopped'
        worker.tick()
        self.assertFalse(any(a=='resume_login' for a,_ in self.cloud.calls))
        self.cloud.lease['desired_state']='running'
        worker.tick()
        payload=next(p for a,p in self.cloud.calls if a=='resume_login')
        self.assertEqual(payload['generation'],0)
        self.assertIsNone(payload['account_ref'])
        self.assertEqual(payload['identity_status'],'manually_confirmed_same_account')
        self.assertEqual(payload['local_run_id'],self.local_id)

    def test_waiting_login_persists_and_other_platform_is_dispatched(self):
        session=uid()
        account={'generation':2,'account_ref':'f'*64,'state':'logged_out','authorized_for_run':None}
        def runner(action,payload):
            if action=='status':return {'ok':True,'result':{'state':'login_required','api_attempts':1}}
            if action=='account_status':return {'ok':True,'result':account}
            if action=='import':return {'ok':True,'result':{'records':[]}}
            return self.runner(action,payload)
        worker=CloudWorker(self.root,self.cloud,runner,session_selector=lambda _:session)
        worker.tick()
        self.assertEqual(worker.tick()['state'],'waiting_login')
        worker=CloudWorker(self.root,self.cloud,runner,session_selector=lambda _:session)
        self.assertEqual(worker.tick()['state'],'waiting_login')
        pending=json.loads(worker.path.read_text())['waiting_logins']
        self.assertEqual(len(pending),1)
        self.assertEqual(pending[0]['local_run_id'],self.local_id)
        self.cloud.lease=lease();self.cloud.lease['platform']='dy'
        self.cloud.lease['request']={**self.cloud.lease['request'],'platform':'dy','targets':['1']}
        self.assertEqual(worker.tick()['state'],'finished')
        starts=[p['platform'] for a,p in self.actions if a=='start']
        self.assertEqual(starts,['xhs','dy'])
        self.assertEqual(len(json.loads(worker.path.read_text())['waiting_logins']),2)

    def test_supplemental_account_requires_original_session_generation_fresh_scope(self):
        source_run, session = uid(), uid()
        self.cloud.lease.update(platform='bili', supplemental_context={
            'source_local_run_id':source_run, 'source_worker_id':self.cloud.lease['worker_id'],
            'request_session_id':session})
        account={'generation':1,'account_ref':'f'*64,'state':'authenticated',
                 'login_verified':True,'verified_at':time.time(),'authorized_for_run':source_run}
        def runner(action,payload):
            if action=='status':return {'ok':True,'result':{'state':'failed','platform':'bili',
                    'session_id':session,'account_generation':1}}
            if action=='account_status':return {'ok':True,'result':account}
            return self.runner(action,payload)
        worker=CloudWorker(self.root,self.cloud,runner)
        state={'lease':self.cloud.lease}
        request={}
        self.assertTrue(worker._supplemental_account(state,request))
        self.assertEqual(request['session_id'],session)
        self.assertEqual(state['recovery_authorized_run'],source_run)
        original=dict(account)
        for changes in ({'generation':2},{'authorized_for_run':uid()},
                        {'verified_at':time.time()-181},{'login_in_progress':True},
                        {'state':'checking'},{'account_ref':None}):
            account.clear();account.update(original);account.update(changes)
            self.assertFalse(worker._supplemental_account(state,request))
        self.cloud.lease['supplemental_context']['source_worker_id']=uid()
        with self.assertRaisesRegex(CloudError,'supplemental_account_binding_denied'):
            worker._supplemental_account(state,request)
        self.assertFalse(any(a=='start' for a,_ in self.actions))

    def test_supplemental_login_after_dispatch_uses_explicit_latest_authorization(self):
        source_run, next_run, session = uid(), uid(), uid()
        self.cloud.lease.update(platform='bili', supplemental_context={
            'source_local_run_id':source_run, 'source_worker_id':self.cloud.lease['worker_id'],
            'authorization_local_run_id':next_run})
        states={source_run:{'state':'failed','session_id':session,'platform':'bili','account_generation':1},
                next_run:{'state':'login_required','session_id':session,'platform':'bili','account_generation':1}}
        account={'generation':1,'account_ref':'f'*64,'state':'resumed','login_verified':True,
                 'verified_at':time.time(),'authorized_for_run':next_run}
        def runner(action,payload):
            if action=='status':return {'ok':True,'result':states[payload['run_id']]}
            if action=='account_status':return {'ok':True,'result':account}
            return self.runner(action,payload)
        worker=CloudWorker(self.root,self.cloud,runner)
        state={'lease':self.cloud.lease}
        self.assertTrue(worker._supplemental_account(state,{}))
        self.assertEqual(state['recovery_authorized_run'],next_run)
        states[next_run]['session_id']=uid()
        with self.assertRaisesRegex(CloudError,'supplemental_account_binding_denied'):
            worker._supplemental_account(state,{})

    def test_config_permissions_role_header_and_no_fake_jwt(self):
        seen=[]
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                seen.append(dict(self.headers))
                self.rfile.read(int(self.headers['Content-Length']))
                body=b'{"ok":true,"result":{"tasks":[]}}'
                self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        config=self.root/'cloud-config.json'
        config.write_text(json.dumps({'endpoint':f'http://127.0.0.1:{server.server_port}/functions/v1/crowd-machine','project_key':'sb_publishable_test','owner_key':'a'*64,'worker_key':'b'*64}))
        os.chmod(config,0o644)
        try:
            with self.assertRaises(CloudError):CloudClient(config,allow_test_loopback=True)
            os.chmod(config,0o600)
            with self.assertRaises(CloudError):CloudClient(config)
            self.assertEqual(CloudClient(config,'owner',True).call('task_list'),{'tasks':[]})
            self.assertNotIn('Authorization',seen[0])
            self.assertEqual(seen[0]['X-Crowd-Owner-Key'],'a'*64)
            self.assertNotIn('X-Crowd-Worker-Key',seen[0])
        finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
