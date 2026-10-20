"""Temporary original-run accounting tests; no actual cloud/SDK/source calls."""
import copy
import fcntl
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch

import mc_runner
from cloud_sync import CloudWorker, CloudError, canonical
from terminal_import_recovery import handle


def uid(): return str(uuid.uuid4())


class Cloud:
    role = 'owner'
    def __init__(self, original):
        self.original = original
        self.calls = []
        self.lose_ack = False
        lease = original['lease']
        self.child = {'child_id': lease['child_id'], 'worker_id': lease['worker_id'],
            'lease_epoch': lease['lease_epoch'], 'local_run_id': original['local_run_id'],
            'runs': [lease['run_id']], 'received_captures': 0, 'request_quota': 30,
            'requests_spent': 0, 'requests_reserved': 30, 'finish_hash': None,
            'state': 'running', 'lease_until': '2099-01-01T00:00:00Z',
            'attempts': [{**{k: lease[k] for k in ('worker_id','run_id','lease_epoch')},
                'claim_id': original['claim_id'], 'local_run_id': original['local_run_id']}]}
        self.task = {'task_id': lease['task_id'], 'revision': 1,
                     'desired_state': 'running', 'children': [self.child]}
    def expire(self):
        self.child.update(state='unknown', lease_until='2000-01-01T00:00:00Z')
    def call(self, action, payload=None):
        self.calls.append((action, copy.deepcopy(payload)))
        if action == 'task_status': return {'task': copy.deepcopy(self.task)}
        if action == 'task_reconcile':
            assert 'canonical_audit' not in payload and 'audit_hash' not in payload
            semantic={k:v for k,v in payload.items() if k!='expected_revision'}
            payload={**payload,'canonical_audit':canonical(semantic),
                'audit_hash':hashlib.sha256(('crowd-machine-terminal-audit-v1\n'+canonical(semantic)).encode()).hexdigest()}
            assert payload['proof']['local_state'] == 'failed'
            assert payload['proof']['exit_code'] == 1
            assert payload['proof']['api_attempts'] is None
            assert payload['capture_count'] == 0
            assert payload['capture_digest'] == hashlib.sha256(b'crowd-machine-capture-audit-v1\n').hexdigest()
            assert payload['expected_revision'] == self.task['revision']
            assert self.child['state'] == 'unknown'
            assert payload['audit_hash'] == hashlib.sha256(('crowd-machine-terminal-audit-v1\n'+payload['canonical_audit']).encode()).hexdigest()
            audit = {'audit_id': uid(), 'mode': 'terminal_unknown', 'outcome': 'unknown',
                     'charged_requests': 30, 'released_requests': 0, 'audit_hash': payload['audit_hash']}
            self.child.update(state='failed', reason_code='audited_terminal_unknown',
                              requests_spent=30, requests_reserved=0, terminal_audit=audit)
            self.task['revision'] += 1
            if self.lose_ack: raise CloudError('cloud_outcome_unknown')
            return {'reconciled': True, 'audit_hash': payload['audit_hash'],
                    **{k:payload[k] for k in ('worker_id','claim_id','run_id','lease_epoch')}}
        raise AssertionError('unexpected cloud action '+action)


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve(); self.collector = self.root/'collector'
        self.sid, self.local = uid(), uid()
        session = self.collector/'sessions'/self.sid; session.mkdir(parents=True)
        (session/'active.lock').touch(mode=0o600)
        run = self.collector/'runs'/self.local; run.mkdir(parents=True); self.run = run
        request = mc_runner.validate({'platform':'xhs','mode':'detail',
            'targets':['0123456789abcdef01234567'],'max_items':1,'max_api_requests':30,
            'comments':False,'source_executor':'pro','media':True,
            'session_id':self.sid,'purpose':'noncommercial_research'})
        lease = {'task_id':uid(),'child_id':uid(),'worker_id':uid(),'run_id':uid(),
            'lease_epoch':1,'platform':'xhs','delivery_basis':'live_capture','request':request}
        self.original = {'phase':'importing','outcome':'failed','api_attempts':0,
            'lease':lease,'claim_id':uid(),'local_run_id':self.local,'session_id':self.sid,'sequence':1}
        self.manifest = {'run_id':self.local,'request':request,'executor':{'backend':'pro'}}
        self.status = {'run_id':self.local,'state':'failed','phase':'failed','exit_code':1}
        for n,v in [('manifest.json',self.manifest),('status.json',self.status)]:
            (run/n).write_text(json.dumps(v)); (run/n).chmod(0o600)
        self.before = {p.name:p.read_bytes() for p in run.iterdir()}
        self.cloud = Cloud(self.original)
        self.runner = lambda *a: (_ for _ in ()).throw(AssertionError('NO_RUNNER_ACTION'))
        self.worker = CloudWorker(self.root, self.cloud, self.runner)
        self.addCleanup(self.worker.close); self.worker._save(copy.deepcopy(self.original))
        self.app = SimpleNamespace(cloud_worker=self.worker,cloud_client=self.cloud,
                                   _registered_run_root=lambda run:self.collector)
    def status_read(self): return handle(self.app,{'recovery_action':'status'})
    def action(self, name):
        state = self.status_read()
        return handle(self.app,{'recovery_action':name,'expected_state_hash':state['state_hash'],'expected_revision':state['cloud_revision']})
    def test_explicit_park_stops_renewal_preserves_original_and_then_fullquota(self):
        self.assertTrue(self.status_read()['can_park'])
        before_state=mc_runner.read(self.worker.path)
        parked = self.action('park'); self.assertEqual(parked['state'],'parked')
        state = mc_runner.read(self.worker.path)
        self.assertEqual(state['terminal_recovery']['original_state'],before_state)
        self.assertEqual(state['terminal_recovery']['original_state']['phase'],'importing')
        before=len(self.cloud.calls)
        for _ in range(2): self.assertEqual(self.worker.tick()['state'],'terminal_recovery_parked')
        self.assertEqual(len(self.cloud.calls),before)
        with self.assertRaisesRegex(ValueError,'waiting_expiry'):self.action('reconcile')
        self.cloud.expire(); result=self.action('reconcile')
        self.assertEqual(result['state'],'accounted_unknown');self.assertIsNone(result['api_attempts'])
        after=mc_runner.read(self.worker.path);self.assertEqual(after['phase'],'idle')
        saved=after['terminal_recoveries'][self.original['lease']['run_id']]
        self.assertEqual(saved['original_state']['lease'],self.original['lease'])
        self.assertEqual(saved['audit']['released_requests'],0)
        self.assertEqual({p.name:p.read_bytes() for p in self.run.iterdir()},self.before)
        self.assertEqual([a for a,_ in self.cloud.calls].count('task_reconcile'),1)
    def test_lost_ack_never_resends_and_readonly_audit_verifies(self):
        self.action('park');self.cloud.expire();self.cloud.lose_ack=True
        with self.assertRaisesRegex(CloudError,'cloud_outcome_unknown'):self.action('reconcile')
        self.assertEqual(self.worker.tick()['state'],'terminal_recovery_unknown')
        with self.assertRaisesRegex(ValueError,'waiting_expiry'):self.action('reconcile')
        self.assertEqual(self.action('verify')['state'],'accounted_unknown')
        self.assertEqual([a for a,_ in self.cloud.calls].count('task_reconcile'),1)
    def test_same_hash_cas_and_foreign_session_lock(self):
        value=self.status_read();state=mc_runner.read(self.worker.path);state['sequence']+=1;self.worker._save(state)
        with self.assertRaisesRegex(ValueError,'state_changed'):
            handle(self.app,{'recovery_action':'park','expected_state_hash':value['state_hash'],'expected_revision':value['cloud_revision']})
        with open(self.collector/'sessions'/self.sid/'active.lock','r+') as f:
            fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):self.status_read()
        self.assertEqual(mc_runner.read(self.worker.path)['phase'],'importing')
    def test_cloud_revision_cas_and_stop_preserved(self):
        self.cloud.task['desired_state']='stopped';self.cloud.task['revision']=2
        info=self.status_read();self.cloud.task['revision']=3
        with self.assertRaisesRegex(ValueError,'revision_changed'):
            handle(self.app,{'recovery_action':'park','expected_state_hash':info['state_hash'],'expected_revision':info['cloud_revision']})
        self.action('park');self.assertEqual(self.cloud.task['desired_state'],'stopped')
    def test_foreign_scope_pending_or_known_budget_fail_closed(self):
        for field,value in [('local_run_id',uid()),('lease_epoch',2)]:
            before=self.cloud.child[field];self.cloud.child[field]=value
            with self.assertRaises(ValueError):self.status_read()
            self.cloud.child[field]=before
        for value in [0,1,False]:
            s={**self.status,'api_attempts':value};(self.run/'status.json').write_text(json.dumps(s))
            with self.assertRaises(ValueError):self.status_read()
        (self.run/'status.json').write_text(json.dumps(self.status))
        with patch.object(self.worker.outbox,'stats',return_value={'pending':1,'capture_ids':[]}):
            with self.assertRaises(ValueError):self.status_read()
    def test_artifact_drift_no_mutation_or_accounting_call(self):
        self.action('park');self.cloud.expire()
        self.status['reason']='changed';(self.run/'status.json').write_text(json.dumps(self.status))
        with self.assertRaisesRegex(ValueError,'artifacts_changed'):self.action('reconcile')
        self.assertNotIn('task_reconcile',[a for a,_ in self.cloud.calls])
    def test_normal_existing_tasks_reconcile_route_and_owner_only(self):
        from dashboard import Application
        value=Application.tasks(self.app,'reconcile',{'recovery_action':'status'})
        self.assertTrue(value['available'])
        self.cloud.role='worker'
        with self.assertRaises(ValueError):Application.tasks(self.app,'reconcile',{'recovery_action':'status'})
        self.cloud.role='owner'
        with self.assertRaisesRegex(ValueError,'invalid_terminal_recovery_request'):
            Application.tasks(self.app,'reconcile',{'recovery_action':'status','root':'/foreign'})
    def test_unknown_audit_mismatch_and_history_survive_future_save(self):
        self.action('park');self.cloud.expire();self.cloud.lose_ack=True
        with self.assertRaises(CloudError):self.action('reconcile')
        original=self.cloud.child['terminal_audit']['audit_hash']
        self.cloud.child['terminal_audit']['audit_hash']='0'*64
        with self.assertRaises(ValueError):self.action('verify')
        self.cloud.child['terminal_audit']['audit_hash']=original;self.action('verify')
        self.worker._save({'phase':'claiming','claim_id':uid()})
        self.assertIn(self.original['lease']['run_id'],mc_runner.read(self.worker.path)['terminal_recoveries'])


if __name__=='__main__':unittest.main()
