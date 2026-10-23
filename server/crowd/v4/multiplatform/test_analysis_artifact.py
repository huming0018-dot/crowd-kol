import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import uuid

from analysis_artifact import prepare_analysis_artifact,publish_analysis_artifact
from analysis_contract import _hash
from mc_runner import canonical


class ArtifactTests(unittest.TestCase):
    def fixture(self,root):
        job,local,task,child,run,derived=[str(uuid.uuid4()) for _ in range(6)]
        folder=Path(root)/'analysis'/job;folder.mkdir(parents=True)
        snapshot={'platform':'bilibili','content_id':'123','content':{'title':'原题','text':'原正文'},'comments':[],
                  'derived_inputs':[{'job_id':derived,'segments':[{'text':'转写'+str(i)} for i in range(3)]}],'analysis_batches':[{},{}]}
        snapshot['snapshot_hash']=_hash(snapshot)
        coverage={'state':'all_selected_segments_analyzed','batches_completed':2,'batches_total':2,'selected_segments':3,'selected_characters':9,
                  'source_refs':['derived:'+derived+':'+str(i) for i in range(3)],'semantic_review':'not_reviewed','automatic_retry':False}
        state={'job_id':job,'run_id':local,'state':'completed','platform':'bilibili','content_id':'123','snapshot_hash':snapshot['snapshot_hash'],'provider':'codex_cli','provider_version':'codex-cli test','completed_batches':2,'total_batches':2}
        result={'snapshot_hash':snapshot['snapshot_hash'],'provider':'codex_cli','provider_version':'codex-cli test','content_analysis':{'summary':'完整分析'},'review_status':'unreviewed_model_analysis','full_analysis_coverage':coverage,'input_snapshot':snapshot}
        for name,value in [('state.json',state),('snapshot.json',snapshot),('result.json',result)]: (folder/name).write_text(json.dumps(value,ensure_ascii=False))
        jobs=SimpleNamespace(root=folder.parent,folder=lambda identity:folder if identity==job else (_ for _ in ()).throw(ValueError('invalid_analysis_job_id')))
        scope={'task_id':task,'child_id':child,'run_id':run,'lease_epoch':1,'local_run_id':local}
        class Client:
            role='owner';endpoint='https://offline.invalid/functions/v1/crowd-machine'
            calls=[];bad_ack=False
            listing={'tasks':[{'task_id':task,'children':[{'child_id':child,'attempts':[{'run_id':run,'lease_epoch':1,'local_run_id':local}]}]}]}
            items=[{'record':{'platform':'bilibili','content_id':'123','kind':'content','title':'原题','body':'原正文','origin':{'run_id':local}},'receipt':{**{k:v for k,v in scope.items() if k!='local_run_id'},'status':'received','reward_eligible':False,'capture_id':str(uuid.uuid4()),'envelope_hash':'a'*64}}]
            def call(self,action,payload=None):
                self.calls.append((action,payload))
                if action=='task_list':return self.listing
                if action=='results':return {'items':self.items}
                if action=='artifact_put':
                    receipt={k:payload[k] for k in ('task_id','child_id','run_id','lease_epoch','local_run_id','local_job_id','source_refs','input_snapshot_hash','full_result_file_sha256','report_sha256','coverage')}
                    receipt.update(artifact_id=str(uuid.uuid4()),artifact_hash=hashlib.sha256(('crowd-analysis-artifact-v1\n'+canonical(payload)).encode()).hexdigest(),artifact_kind='analysis_report',status='received',reward_eligible=False)
                    if self.bad_ack:receipt['coverage']={**receipt['coverage'],'batches_completed':True}
                    return {'receipt':receipt,'replayed':False}
                raise AssertionError(action)
        return job,jobs,Client(),folder,result

    def test_publish_completed_full_report_keeps_originals_and_exact_hash(self):
        with tempfile.TemporaryDirectory() as root:
            job,jobs,client,folder,result=self.fixture(root)
            before={p.name:p.read_bytes() for p in folder.iterdir()}
            answer=publish_analysis_artifact(jobs,client,job)
            self.assertEqual([action for action,_ in client.calls],['task_list','results','artifact_put'])
            payload=client.calls[-1][1];self.assertNotIn('input_snapshot',json.loads(payload['report_json']))
            self.assertEqual(payload['full_result_file_sha256'],hashlib.sha256(before['result.json']).hexdigest())
            self.assertEqual(payload['report_sha256'],hashlib.sha256(payload['report_json'].encode()).hexdigest())
            self.assertEqual(answer['source_requests'],0);self.assertEqual(answer['model_calls'],0)
            self.assertEqual(before,{p.name:p.read_bytes() for p in folder.iterdir()})
            path=Path(root)/'analysis-artifact-receipts'/(job+'.json');self.assertTrue(path.exists())

    def test_no_cloud_worker_principal_or_not_completed_cannot_publish(self):
        with tempfile.TemporaryDirectory() as root:
            job,jobs,client,folder,_=self.fixture(root)
            for other in [None,SimpleNamespace(role='worker')]:
                with self.assertRaises(ValueError):prepare_analysis_artifact(jobs,other,job)
            state=json.loads((folder/'state.json').read_text());state['state']='running';(folder/'state.json').write_text(json.dumps(state))
            with self.assertRaisesRegex(ValueError,'not_completed'):prepare_analysis_artifact(jobs,client,job)
            self.assertEqual(client.calls,[])

    def test_bad_source_binding_never_artifact_put(self):
        for field,value in [('origin',{'run_id':str(uuid.uuid4())}),('body','错正文'),('content_id','999')]:
            with tempfile.TemporaryDirectory() as root:
                job,jobs,client,_,_=self.fixture(root)
                client.items=copy.deepcopy(client.items);client.items[0]['record'][field]=value
                with self.assertRaisesRegex(ValueError,'source_binding_denied'):publish_analysis_artifact(jobs,client,job)
                self.assertNotIn('artifact_put',[x[0] for x in client.calls])

    def test_incomplete_or_changed_result_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            job,jobs,client,folder,result=self.fixture(root)
            result['full_analysis_coverage']['source_refs'].pop();(folder/'result.json').write_text(json.dumps(result))
            with self.assertRaisesRegex(ValueError,'coverage_incomplete'):prepare_analysis_artifact(jobs,client,job)
            self.assertEqual(client.calls,[])
        with tempfile.TemporaryDirectory() as root:
            job,jobs,client,folder,result=self.fixture(root)
            result['input_snapshot']['content']['title']='修改';(folder/'result.json').write_text(json.dumps(result))
            with self.assertRaisesRegex(ValueError,'snapshot_changed'):prepare_analysis_artifact(jobs,client,job)

    def test_unknown_ack_not_cached_and_bool_metric_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            job,jobs,client,_,_=self.fixture(root);client.bad_ack=True
            with self.assertRaisesRegex(ValueError,'receipt_mismatch'):publish_analysis_artifact(jobs,client,job)
            self.assertFalse((Path(root)/'analysis-artifact-receipts').exists())

    def test_symlink_hardlink_result_rejected_before_network(self):
        import os
        for link in ['symlink','hardlink']:
            with tempfile.TemporaryDirectory() as root:
                job,jobs,client,folder,_=self.fixture(root);path=folder/'result.json';real=folder/'retained.json';path.rename(real)
                if link=='symlink':path.symlink_to(real)
                else:os.link(real,path)
                with self.assertRaisesRegex(ValueError,'unsafe_analysis_artifact_file'):prepare_analysis_artifact(jobs,client,job)
                self.assertEqual(client.calls,[])

    def test_ancestor_symlink_rejected_before_network(self):
        from analysis_jobs import AnalysisJobs
        with tempfile.TemporaryDirectory() as root:
            job,_,client,folder,_=self.fixture(root)
            manager=AnalysisJobs(root,executable='/nonexistent-offline')
            original=folder.parent;outside=Path(root)/'outside';original.rename(outside);original.symlink_to(outside,target_is_directory=True)
            with self.assertRaisesRegex(ValueError,'unsafe_analysis_artifact_file'):prepare_analysis_artifact(manager,client,job)
            self.assertEqual(client.calls,[])
            manager.close()

    def test_same_id_different_body_kind_or_type_rejected(self):
        for change in [{'kind':'dynamic'},{'content_type':'article'}]:
            with tempfile.TemporaryDirectory() as root:
                job,jobs,client,_,_=self.fixture(root)
                client.items=copy.deepcopy(client.items)
                other=copy.deepcopy(client.items[0]);other['record'].update(change)
                other['receipt']['capture_id']=str(uuid.uuid4());other['receipt']['envelope_hash']='b'*64
                client.items.append(other)
                with self.assertRaisesRegex(ValueError,'source_binding_denied'):prepare_analysis_artifact(jobs,client,job)
                self.assertNotIn('artifact_put',[x[0] for x in client.calls])


if __name__=='__main__':unittest.main()
