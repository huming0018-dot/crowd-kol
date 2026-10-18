import hashlib
import tempfile
import unittest
import uuid
from pathlib import Path
import mc_runner
from participant_pro import ParticipantOutbox, ParticipantError, ParticipantProWorker

UID=lambda:str(uuid.uuid4())
class RPC:
    def __init__(self):self.calls=[];self.unknown=True;self.receipts={};self.received=20
    def __call__(self,action,p):
        self.calls.append((action,p.copy()))
        if action=='pro_receipt':return {'found':p['p_request'] in self.receipts,'request':p['p_request'],'receipt':self.receipts.get(p['p_request'])}
        if action=='pro_submit':
            rid=p['p_request'];record=p['p_payload']['record']
            if rid not in self.receipts:
                self.received+=1
                self.receipts[rid]={'request':rid,'gate':'received','inserted':True,'duplicate':False,'task_received':self.received,'proof_id':100+self.received,'source_kind':'mediacrawler_pro','reward_eligible':False,'record_hash':record['record_hash']}
            if self.unknown:self.unknown=False;raise RuntimeError('network unknown')
            return self.receipts[rid]
        raise AssertionError(action)

def record(note='a'*24):
    r={'kind':'content','platform':'xiaohongshu','content_id':note,'title':'fixture','body':'fixture正文','source_kind':'mediacrawler_api','reward_eligible':False}
    r['record_hash']=hashlib.sha256(mc_runner.canonical(r).encode()).hexdigest();return r

class Tests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.rpc=RPC();self.box=ParticipantOutbox(self.root,self.rpc);self.lease={'task_id':19,'lease':UID(),'installation_id':UID()};self.run=UID()
    def tearDown(self):self.tmp.cleanup()
    def stage(self,r=None):return self.box.stage(r or record(),self.lease,{'local_run_id':self.run,'upstream_commit':'d'*40,'request_sha256':'e'*64,'captured_at':'2026-10-18T10:00:00Z'})
    def test_unknown_reconciles_original_uuid_without_resubmit(self):
        rid=self.stage();self.assertEqual(self.box.flush(),'unknown');before=[x for x in self.rpc.calls if x[0]=='pro_submit'];self.assertEqual(self.box.flush(),'delivered');after=[x for x in self.rpc.calls if x[0]=='pro_submit'];self.assertEqual(before,after);self.assertEqual(self.box.receipts()[0]['request'],rid)
    def test_repeat_stage_identical_and_conflict_refused(self):
        rid=self.stage();self.assertEqual(rid,self.stage());r=record();r['body']='changed';r['record_hash']=hashlib.sha256(mc_runner.canonical({k:v for k,v in r.items() if k!='record_hash'}).encode()).hexdigest()
        with self.assertRaises(ParticipantError):self.stage(r)
    def test_bad_receipt_does_not_ack(self):
        self.rpc.unknown=False;rid=self.stage();self.rpc.receipts[rid]={'request':rid,'gate':'received','inserted':True,'duplicate':False,'task_received':21,'proof_id':1,'source_kind':'mediacrawler_pro','reward_eligible':False,'record_hash':'0'*64}
        self.assertEqual(self.box.flush(),'unknown');self.assertEqual(self.box.receipts(),[])
    def test_confirmed_foreign_duplicate_is_terminal_not_new_proof(self):
        rid=self.stage();self.rpc.unknown=False
        self.rpc.receipts[rid]={'request':rid,'gate':'received','inserted':False,'duplicate':True,'task_received':20,'proof_id':None,'source_kind':'mediacrawler_pro','reward_eligible':False,'record_hash':record()['record_hash']}
        self.assertEqual(self.box.flush(),'delivered');self.assertIsNone(self.box.receipts()[0]['proof_id'])
    def test_known_rejection_is_not_unknown_or_retried(self):
        rid=self.stage();calls=[]
        def rpc(action,p):
            calls.append(action)
            return {'found':False,'request':rid,'receipt':None} if action=='pro_receipt' else {'error':'unrelated_note'}
        self.box.client=rpc
        self.assertEqual(self.box.flush(),'rejected');before=list(calls)
        self.assertEqual(self.box.flush(),'rejected');self.assertEqual(calls,before)
    def test_restart_preserves_original_generation_before_scope_or_delivery(self):
        import json
        subject,install,sid=UID(),UID(),UID()
        binding={'profile':'/original','subject':subject,'installation_id':install,'generation':7}
        context={'binding':binding}
        with self.box._db() as db:db.execute('INSERT INTO participant_runs VALUES(?,?,?,?)',(19,'running',self.run,json.dumps(context)))
        calls=[]
        class Transport:
            node='/node'
            def __init__(self):self.binding={**binding,'generation':None}
            def scope(self):
                calls.append(('scope',self.binding['generation']))
                if self.binding['generation']!=8:raise ParticipantError('participant_scope_changed')
            def __call__(self,*a):raise AssertionError('no RPC after Stop')
        worker=ParticipantProWorker(self.root,Transport(),lambda *a:self.fail('no source'),task_id=19,installation_id=install,subject=subject,session_id=sid,known_ids=[])
        with self.assertRaises(ParticipantError):worker.tick({})
        self.assertEqual(calls,[('scope',7)])
    def test_bad_record_never_staged(self):
        for patch in ({'reward_eligible':True},{'record_hash':'0'*64},{'platform':'douyin'}):
            r=record();r.update(patch)
            with self.assertRaises(ParticipantError):self.stage(r)
    def test_explicit_pro_small_search_only(self):
        p={'platform':'xhs','mode':'search','targets':['fixture'],'max_items':2,'source_executor':'pro','purpose':'noncommercial_research'}
        self.assertEqual(mc_runner.validate(p)['max_items'],2)
        p['source_executor']='mc'
        with self.assertRaises(mc_runner.BridgeError):mc_runner.validate(p)


class WorkerWhole(unittest.TestCase):
    def test_claim_original_sdk_results_unknown_ack_reopen_stops_no_second_source(self):
        from pro_executor import PINNED_COMMIT
        with tempfile.TemporaryDirectory() as temp:
            uid,install,sid,lease,grant,run=[UID() for _ in range(6)]
            rpc=RPC();rpc.binding={'profile':'/synthetic/original','subject':uid,'installation_id':install,'generation':7};rpc.node='/synthetic/node';base_call=rpc.__call__
            class Transport:
                binding=rpc.binding;node=rpc.node
                def scope(self):return {'subject':uid,'installation_id':install}
                def __call__(self,a,p):
                    if a=='pro_claim':return {'source_executor':'mediacrawler_pro','reward_eligible':False,'known_note_ids':['a'*24],'task':{'id':19,'lease_token':lease,'received':20,'target':22,'query':'fixture','comments_capture':False},'acceptance_supplement':{'schema':'crowd-acceptance-batch-v1','id':grant,'task_id':19,'installation_id':install,'baseline_received':2,'extra_limit':20,'remaining':2,'target':22}}
                    if a=='pro_finish':return {'status':'complete','received':22}
                    if a=='pro_status':return {'task':{'id':19,'received':22,'target':22,'status':'complete','source_executor':'mediacrawler_pro'}}
                    return base_call(a,p)
            calls=[]
            def runner(a,p):
                calls.append(a)
                if a=='start':
                    self.assertEqual(p['request']['max_items'],2);self.assertEqual(p['participant_context']['known_ids'],['a'*24]);return {'run_id':run}
                if a=='status':return {'state':'completed'}
                if a=='import':return {'records':[record('b'*24),record('c'*24)],'manifest':{'source':{'commit':PINNED_COMMIT}},'summary':{'coverage':'unverified'}}
                raise AssertionError(a)
            worker=ParticipantProWorker(Path(temp),Transport(),runner,task_id=19,installation_id=install,subject=uid,session_id=sid,known_ids=['a'*24])
            request={'platform':'xhs','source_executor':'pro','session_id':sid,'mode':'search','targets':['fixture'],'purpose':'noncommercial_research','comments':False,'replies':False}
            self.assertEqual(worker.tick(request)['state'],'delivery_unknown')
            # Crash/reopen: persisted source operation and exact UUIDs survive.
            worker=ParticipantProWorker(Path(temp),Transport(),runner,task_id=19,installation_id=install,subject=uid,session_id=sid,known_ids=['a'*24])
            self.assertEqual(worker.tick(request)['state'],'complete');self.assertEqual(worker.tick(request)['state'],'complete')
            self.assertEqual(calls.count('start'),1);self.assertEqual(rpc.received,22);self.assertEqual(len(worker.outbox.receipts()),2)
            self.assertEqual(len({r['request'] for r in worker.outbox.receipts()}),2)


class KnownFailureRecovery(unittest.TestCase):
    def test_failed_zero_does_not_finish_and_explicit_retry_keeps_budget_and_uuid_ancestry(self):
        from pro_executor import PINNED_COMMIT
        with tempfile.TemporaryDirectory() as temp:
            subject,install,sid,lease,grant,oldrun,newrun=[UID() for _ in range(7)]
            trace=[];received=[20];attempt=[0]
            binding={'profile':'/original','subject':subject,'installation_id':install,'generation':7}
            def batch():return {'schema':'crowd-acceptance-batch-v1','id':grant,'task_id':19,'installation_id':install,'baseline_received':2,'extra_limit':20,'remaining':22-received[0],'target':22}
            class Transport:
                node='/node'
                def __init__(self):self.binding=dict(binding)
                def scope(self):return {'subject':subject,'installation_id':install}
                def __call__(self,a,p):
                    trace.append(a)
                    if a=='pro_claim':return {'source_executor':'mediacrawler_pro','reward_eligible':False,'known_note_ids':['a'*24],'task':{'id':19,'lease_token':lease,'received':received[0],'target':22,'query':'fixture','comments_capture':False},'acceptance_supplement':batch()}
                    if a=='pro_status':return {'task':{'id':19,'received':received[0],'target':22,'status':'complete' if received[0]==22 else 'open','source_executor':'mediacrawler_pro'},'acceptance_supplement':batch()}
                    if a=='pro_guard':return {'allowed':True,'reason':None,'counts':{'detail':174}}
                    if a=='pro_receipt':return {'found':False,'request':p['p_request'],'receipt':None}
                    if a=='pro_submit':
                        received[0]+=1
                        return {'request':p['p_request'],'gate':'received','inserted':True,'duplicate':False,'task_received':received[0],'proof_id':received[0],'source_kind':'mediacrawler_pro','reward_eligible':False,'record_hash':p['p_payload']['record']['record_hash']}
                    if a=='pro_finish':return {'status':'complete','received':22}
                    raise AssertionError(a)
            def runner(a,p):
                if a=='start':
                    attempt[0]+=1
                    if attempt[0]==2:
                        self.assertEqual(p['request']['max_api_requests'],14)
                        self.assertEqual(p['participant_context']['recovery']['old_run_id'],oldrun)
                    return {'run_id':oldrun if attempt[0]==1 else newrun}
                if a=='inspect':return {'state':'failed','observation_count':0,'used_requests':6,'total_limit':20,'saved_files_sha256':{}}
                if a=='status':return {'state':'failed' if p['run_id']==oldrun else 'completed'}
                if a=='import':return {'records':[] if p['run_id']==oldrun else [record('b'*24),record('c'*24)],'manifest':{'source':{'commit':PINNED_COMMIT}}}
                raise AssertionError(a)
            worker=ParticipantProWorker(Path(temp),Transport(),runner,task_id=19,installation_id=install,subject=subject,session_id=sid,known_ids=['a'*24])
            request={'platform':'xhs','source_executor':'pro','session_id':sid,'mode':'search','targets':['fixture'],'purpose':'noncommercial_research','comments':False,'replies':False,'max_api_requests':20}
            self.assertEqual(worker.tick(request)['state'],'source_failed');self.assertNotIn('pro_finish',trace)
            self.assertEqual(worker.tick(request)['state'],'source_failed');self.assertEqual(attempt[0],1)
            result=worker.recover_known_failed_once(oldrun,expected_used_requests=6,expected_detail_count=174,expected_received=20)
            self.assertEqual(result['remaining_source_requests'],14);self.assertEqual(attempt[0],1)
            with self.assertRaises(ParticipantError):worker.recover_known_failed_once(oldrun,expected_used_requests=6,expected_detail_count=174,expected_received=20)
            self.assertEqual(worker.tick(request)['state'],'complete');self.assertEqual(received[0],22)
            self.assertEqual(worker.tick(request)['state'],'complete');self.assertEqual(attempt[0],2)


class RecoveryDenials(unittest.TestCase):
    def test_unknown_observed_or_budget_mismatch_never_prepares_retry(self):
        import json
        for state,observations,used in [('source_unknown',0,6),('source_failed',1,6),('source_failed',0,7)]:
            with tempfile.TemporaryDirectory() as temp:
                subject,install,sid,run=UID(),UID(),UID(),UID()
                binding={'profile':'/original','subject':subject,'installation_id':install,'generation':7}
                class Transport:
                    node='/node'
                    def __init__(self):self.binding=dict(binding)
                    def scope(self):return {'subject':subject,'installation_id':install}
                    def __call__(self,*a):raise AssertionError('no write/RPC after rejected saved evidence')
                def runner(a,p):return {'state':'failed','observation_count':observations,'used_requests':used,'total_limit':20}
                w=ParticipantProWorker(Path(temp),Transport(),runner,task_id=19,installation_id=install,subject=subject,session_id=sid,known_ids=[])
                context={'binding':binding,'target':22}
                with w.outbox._db() as db:db.execute('INSERT INTO participant_runs VALUES(?,?,?,?)',(19,state,run,json.dumps(context)))
                with self.assertRaises(ParticipantError):w.recover_known_failed_once(run,expected_used_requests=6,expected_detail_count=174,expected_received=20)
                with w.outbox._db() as db:self.assertEqual(db.execute('SELECT state FROM participant_runs').fetchone()[0],state)

if __name__=='__main__':unittest.main()
