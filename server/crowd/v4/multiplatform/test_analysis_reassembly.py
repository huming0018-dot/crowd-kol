"""Reassemble immutable saved batches without provider or source calls."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import urllib.error
import urllib.request
import unittest
import uuid
from unittest.mock import patch

from analysis_contract import _hash, validate_result
from analysis_jobs import AnalysisJobs
from full_analysis import build_analysis_snapshot, combine_results
from mc_runner import read, write
from test_analysis import imported_fixture, model_fixture
from test_full_analysis import item
import dashboard


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
        self.jobs=AnalysisJobs(self.base,executable='/missing-offline-provider')
        self.job_id=str(uuid.uuid4());self.folder=self.jobs.root/self.job_id;self.folder.mkdir()
        self.snapshot=build_analysis_snapshot(imported_fixture(),'bili','video1',derived_inputs=[item()])
        self.results=[]
        for index,batch in enumerate(self.snapshot['analysis_batches']):
            value=model_fixture(batch['snapshot'])
            if index:
                value['content_analysis']['segments'].append({'paragraph':batch['snapshot']['paragraphs'][-1]['paragraph'],'role':'候选','observation':'保留原句'})
            checked=validate_result(batch['snapshot'],value);self.results.append(checked)
            write(self.folder/('batch-%04d.json'%index),{'snapshot_hash':batch['snapshot']['snapshot_hash'],'result':checked})
        self.state={'job_id':self.job_id,'state':'completed','platform':'bili','content_id':'video1','run_id':imported_fixture()['run_id'],
            'snapshot_hash':self.snapshot['snapshot_hash'],'prompt_version':'old-full-v1','provider':'codex_cli','provider_version':'old-cli',
            'total_batches':3,'completed_batches':3,'created_at':1,'completed_at':2,'review_status':'unreviewed_model_analysis','cache_key':'old-key'}
        result=combine_results(self.snapshot,self.results)
        # Represent the published old assembly, whose base rows were repeated.
        result['content_analysis']=copy.deepcopy(self.results[0]['content_analysis'])
        result['content_analysis']['segments']+=copy.deepcopy(self.results[1]['content_analysis']['segments'])
        result.update(input_snapshot=self.snapshot,snapshot_hash=self.state['snapshot_hash'],prompt_version=self.state['prompt_version'],provider=self.state['provider'],provider_version=self.state['provider_version'])
        write(self.folder/'snapshot.json',self.snapshot);write(self.folder/'state.json',self.state);write(self.folder/'result.json',result)
    def tearDown(self):self.jobs.close();self.temp.cleanup()
    def fingerprints(self):return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.folder.iterdir()}
    def test_new_report_preserves_old_bytes_and_replays_without_calls(self):
        before=self.fingerprints()
        with patch.object(self.jobs,'_work',side_effect=AssertionError('no model')):
            new=self.jobs.reassemble(self.job_id);again=self.jobs.reassemble(self.job_id)
        self.assertNotEqual(new['job_id'],self.job_id);self.assertEqual(again['job_id'],new['job_id']);self.assertTrue(again['cached'])
        self.assertEqual(before,self.fingerprints());self.assertEqual(new['model_calls'],0);self.assertEqual(new['source_requests'],0)
        self.assertEqual(new['result']['full_analysis_coverage']['selected_segments'],1110)
        self.assertEqual(len(new['result']['content_analysis']['segments']),3)
        self.assertEqual(new['provider_version'],'old-cli');self.assertEqual(len(new['reassembly']['batches']),3)
        self.assertEqual(new['result']['review_status'],'unreviewed_model_analysis')
        self.assertEqual(read(self.jobs.folder(new['job_id'])/'snapshot.json'),self.snapshot)
    def test_incomplete_and_mutated_files_refused_without_creating_report(self):
        changes=[('state.json',lambda value:value.update(state='failed')),
                 ('state.json',lambda value:value.update(completed_batches=2)),
                 ('state.json',lambda value:value.update(entity_ref='bilibili:dynamic:video1')),
                 ('snapshot.json',lambda value:value['paragraphs'][-1].update(text='changed')),
                 ('result.json',lambda value:value['full_analysis_coverage'].update(selected_segments=1000)),
                 ('batch-0002.json',lambda value:value['result']['content_analysis']['segments'][-1].update(source_ref='derived:wrong:0'))]
        for filename,change in changes:
            with self.subTest(filename=filename):
                path=self.folder/filename;original=path.read_bytes();value=read(path);change(value);write(path,value)
                with self.assertRaises(ValueError):self.jobs.reassemble(self.job_id)
                self.assertEqual(len(list(self.jobs.root.iterdir())),1);path.write_bytes(original)
    def test_rehashed_wrong_partition_text_refused(self):
        piece=self.snapshot['analysis_batches'][-1]['snapshot'];piece['derived_inputs'][0]['segments'][-1]['text']='changed'
        piece['paragraphs'][-1]['text']='changed';piece['snapshot_hash']=_hash({k:v for k,v in piece.items() if k!='snapshot_hash'})
        self.snapshot['snapshot_hash']=_hash({k:v for k,v in self.snapshot.items() if k!='snapshot_hash'})
        self.state['snapshot_hash']=self.snapshot['snapshot_hash'];write(self.folder/'state.json',self.state);write(self.folder/'snapshot.json',self.snapshot)
        old=read(self.folder/'result.json');old.update(input_snapshot=self.snapshot,snapshot_hash=self.snapshot['snapshot_hash']);write(self.folder/'result.json',old)
        batch=read(self.folder/'batch-0002.json');batch['snapshot_hash']=piece['snapshot_hash'];write(self.folder/'batch-0002.json',batch)
        with self.assertRaisesRegex(ValueError,'partition_changed'):self.jobs.reassemble(self.job_id)
    def test_symlink_ancestor_and_hardlink_file_rejected(self):
        snapshot=self.folder/'snapshot.json';other=self.base/'other';os.link(snapshot,other)
        with self.assertRaisesRegex(ValueError,'unsafe_analysis_artifact_file'):self.jobs.reassemble(self.job_id)
        other.unlink();root=self.jobs.root;backup=self.base/'saved-analysis';root.rename(backup);root.symlink_to(backup,target_is_directory=True)
        try:
            with self.assertRaisesRegex(ValueError,'unsafe_analysis_artifact_file'):self.jobs.reassemble(self.job_id)
        finally:root.unlink();backup.rename(root)
    def test_modified_cached_report_not_reused(self):
        new=self.jobs.reassemble(self.job_id);path=self.jobs.folder(new['job_id'])/'result.json';value=read(path)
        value['content_analysis']['summary']='changed';write(path,value)
        with self.assertRaisesRegex(ValueError,'result_changed'):self.jobs.reassemble(self.job_id)

    def test_future_full_start_uses_new_assembly_cache_key(self):
        from test_analysis import JobsTests
        fixture=JobsTests();fixture.setUp()
        try:
            derived=item();imported=imported_fixture()
            first=fixture.wait(fixture.manager.start(imported,'bili','video1',derived_inputs=[derived]),'completed')
            state=read(fixture.manager.folder(first['job_id'])/'state.json')
            state['cache_key']=_hash({'snapshot':state['snapshot_hash'],'prompt':state['prompt_version'],'provider_version':state['provider_version']})
            write(fixture.manager.folder(first['job_id'])/'state.json',state)
            second=fixture.wait(fixture.manager.start(imported,'bili','video1',derived_inputs=[derived]),'completed')
            self.assertNotEqual(first['job_id'],second['job_id']);self.assertEqual(len((fixture.base/'calls.jsonl').read_text().splitlines()),6)
            self.assertTrue(fixture.manager.start(imported,'bili','video1',derived_inputs=[derived])['cached'])
        finally:fixture.tearDown()


class HTTPTests(unittest.TestCase):
    def setUp(self):
        Tests.setUp(self);self.app=dashboard.Application(self.base/'http-root');self.app.analysis_jobs=self.jobs
        self.server=dashboard.make_server(self.app,0);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url='http://127.0.0.1:'+str(self.server.server_port)
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();Tests.tearDown(self)
    def post(self,payload,token=None):
        request=urllib.request.Request(self.url+'/api/analysis',data=json.dumps({'action':'reassemble','payload':payload}).encode(),headers={'Content-Type':'application/json','Origin':self.url,'X-Crowd-CSRF':token or self.app.token})
        with urllib.request.urlopen(request,timeout=5) as response:return json.load(response)
    def test_normal_route_completed_and_strict_payload_denied_without_provider(self):
        with patch.object(self.app,'run',side_effect=AssertionError('no source')):
            result=self.post({'job_id':self.job_id});self.assertNotEqual(result['job_id'],self.job_id);self.assertEqual(result['model_calls'],0)
            for payload in ({'job_id':self.job_id,'allow_model_transfer':True},{'job_id':None},{'job_id':self.job_id,'source_refs':[]},{}):
                with self.subTest(payload=payload),self.assertRaises(urllib.error.HTTPError) as caught:self.post(payload)
                self.assertEqual(caught.exception.code,400);self.assertIsInstance(json.load(caught.exception)['error'],str)
            self.state['state']='failed';write(self.folder/'state.json',self.state)
            (self.folder/'result.json').unlink()
            with self.assertRaises(urllib.error.HTTPError) as caught:self.post({'job_id':self.job_id})
            self.assertEqual(json.load(caught.exception)['error'],'analysis_reassembly_not_completed')
            with self.assertRaises(urllib.error.HTTPError) as caught:self.post({'job_id':self.job_id},'invalid')
            self.assertEqual(caught.exception.code,403)

if __name__=='__main__':unittest.main()
