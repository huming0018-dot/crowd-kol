"""Future typed early failure only; old G73 has no witness and stays unknown."""
import copy
import fcntl
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch

import mc_runner as m
import pro_executor as producer
from cloud_sync import CloudWorker
from test_cloud_sync import FakeCloud, lease


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.sid=str(uuid.uuid4());self.rid=str(uuid.uuid4())
        self.run=self.root/'runs'/self.rid;self.run.mkdir(parents=True);(self.run/'output').mkdir()
        self.session=self.root/'sessions'/self.sid;self.session.mkdir(parents=True);(self.session/'active.lock').touch(mode=0o600)
        request=m.validate({'platform':'xhs','mode':'detail','targets':['0123456789abcdef01234567'],
            'max_items':1,'max_api_requests':30,'comments':False,'media':True,'source_executor':'pro',
            'session_id':self.sid,'purpose':'noncommercial_research'})
        self.manifest={'run_id':self.rid,'request':request,'executor':{'backend':'pro'},'source':{}}
        self.status={'run_id':self.rid,'state':'failed','phase':'failed','exit_code':1,
            'executor':'pro','session_id':self.sid,'platform':'xhs','updated_at':time.time()}
        self.put('manifest.json',self.manifest);self.put('status.json',self.status)
        producer._media_preflight_failure(self.run,self.manifest,'node_import','portable_node_unavailable')
    def put(self,name,value):
        p=self.run/name
        if name=='pro-media-preflight.json':
            from shared_request_budget import canonical
            p.write_text(canonical(value))
        else:p.write_text(json.dumps(value))
        p.chmod(0o600)
    def status_read(self):return m.status(self.root,{'run_id':self.rid})
    def imported(self):return m.import_output(self.root,{'run_id':self.rid})
    def worker(self):
        value=lease();value['request']=self.manifest['request'];cloud=FakeCloud(value);actions=[]
        def runner(action,payload):
            actions.append(action)
            if action=='status':return {'ok':True,'result':self.status_read()}
            if action=='import':return {'ok':True,'result':self.imported()}
            raise AssertionError('NO_SOURCE_ACTION')
        w=CloudWorker(self.root,cloud,runner);self.addCleanup(w.close)
        w._save({'phase':'running','lease':value,'local_run_id':self.rid,'session_id':self.sid,'sequence':1})
        return w,cloud,actions
    def invalid(self):
        self.assertIs(self.status_read().get('api_attempts_unverified'),True)
        with self.assertRaises(m.BridgeError):self.imported()
    def test_exact_future_witness_empty_failed_import_no_sdk(self):
        current=self.status_read();self.assertEqual(current['api_attempts'],0)
        self.assertIs(current['media_preflight_verified'],True)
        with patch.object(producer,'bridge',side_effect=AssertionError('SDK_FORBIDDEN')):
            result=self.imported()
        self.assertEqual(result['records'],[]);self.assertEqual(result['run_state'],'failed')
        self.assertEqual(result['coverage'],'not_started');self.assertIs(result['media_preflight_verified'],True)
    def test_old_missing_witness_never_becomes_zero_or_finishes(self):
        (self.run/'pro-media-preflight.json').unlink();w,cloud,actions=self.worker()
        self.assertEqual(w.tick()['error'],'runner_budget_unavailable')
        self.assertNotIn('import',actions);self.assertNotIn('finish',[a for a,_ in cloud.calls])
    def test_typed_hash_scope_stage_extra_field_rejections(self):
        original=json.loads((self.run/'pro-media-preflight.json').read_text())
        for changed in [{'api_attempts':False},{'source_started':0},{'request_hash':'a'*64},
                        {'run_id':str(uuid.uuid4())},{'stage':'later'},{'reason':'other'},
                        {'extra':'not allowed'}]:
            self.put('pro-media-preflight.json',{**original,**changed});self.invalid()
        self.put('pro-media-preflight.json',original)
    def test_any_source_artifact_or_output_refuses_zero(self):
        for name in ['request-budget.json','phase.json','pro-observations.sqlite3',
                     'mc-source-steps.sqlite3','pro-pagination.json','xhs-pro-media-intent.json','output/item']:
            p=self.run/name;p.write_bytes(b'{}');self.invalid();p.unlink()
    def test_terminal_status_and_inactive_session_required(self):
        for changed in [{'state':'completed','exit_code':0},{'exit_code':True},{'api_attempts':0}]:
            self.put('status.json',{**self.status,**changed});self.invalid()
        self.put('status.json',self.status)
        with open(self.session/'active.lock','r+')as f:
            fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);self.invalid()
    def test_empty_import_failure_finishes_once_zero_not_success(self):
        w,cloud,actions=self.worker();self.assertEqual(w.tick()['state'],'finished')
        finish=next(p for a,p in cloud.calls if a=='finish')
        self.assertEqual((finish['outcome'],finish['api_attempts'],finish['capture_ids']),('failed',0,[]))
        self.assertEqual(actions,['status','import'])
        self.assertNotIn('capture',[a for a,_ in cloud.calls])
    def test_saved_outbox_conflict_never_imports_or_finishes(self):
        w,cloud,actions=self.worker()
        with patch.object(w.outbox,'stats',return_value={'capture_ids':[str(uuid.uuid4())],'pending':0}):
            self.assertEqual(w.tick()['error'],'runner_budget_unavailable')
        self.assertNotIn('import',actions);self.assertNotIn('finish',[a for a,_ in cloud.calls])
    def test_no_resultsstore_creation_for_verified_empty_failure(self):
        from dashboard import Application
        result=self.imported();app=SimpleNamespace(mc_root=self.root,
            _registered_run_root=lambda _:self.root,_call_runner=lambda *_:{'ok':True,'result':result})
        with patch('results_store.ResultsStore',side_effect=AssertionError('NO_EMPTY_LIBRARY_WRITE')):
            self.assertEqual(Application.run(app,'import',{'run_id':self.rid})['result'],result)


if __name__=='__main__':unittest.main()
