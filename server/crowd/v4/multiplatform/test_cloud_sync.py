import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
import uuid

from cloud_sync import CloudClient, CloudError, CloudOutbox, CloudOwnerAdapter, CloudWorker, canonical, _hash, _strict_json


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

    def test_canonical_cross_language_and_strict_numbers(self):
        self.assertEqual(canonical({'😀':1,'\ue000':2,'line':'\n\t','a':-0.0}),'{"a":0,"line":"\\u000a\\u0009","":2,"😀":1}')
        self.assertEqual(canonical(_strict_json('{"a":1.0}')), '{"a":1}')
        for text in ('{"x":1.0000000000000001}','{"x":9007199254740992}','{"x":1,"x":2}','{"x":"\\ud800"}'):
            with self.assertRaises(CloudError):_strict_json(text)
        many=json.dumps({'tasks':[{'children':[{'state':'completed','contents':1} for _ in range(7)]} for _ in range(200)]})
        self.assertEqual(len(_strict_json(many,max_nodes=100000)['tasks']),200)
        with self.assertRaises(CloudError):_strict_json(many)

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
        account['generation']=2
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
