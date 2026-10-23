import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import uuid
import urllib.error
from unittest.mock import patch

from analysis_contract import build_snapshot, make_prompt, validate_result
from analysis_jobs import AnalysisJobs
from mc_runner import write
import dashboard
import test_analysis as fixtures


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.jobs=AnalysisJobs(self.root,executable='/nonexistent-offline-provider')
        self.run=str(uuid.uuid4());self.job=str(uuid.uuid4());self.asset=b'owned-source'
        self.folder=self.root/'media-processing'/self.job;self.folder.mkdir(parents=True)
        self.imported={'run_id':self.run,'records':[{'platform':'douyin','kind':'content','content_id':'123','title':'原标题','body':'原文'}]}
        self.state={'job_id':self.job,'run_id':self.run,'platform':'douyin','content_id':'123','state':'completed','kind':'asr','asset_sha256':hashlib.sha256(self.asset).hexdigest(),'model_manifest_sha256':'a'*64,'processor_files':{'local_asr.py':'b'*64}}
        self.result=[{'platform':'douyin','content_id':'123','kind':'transcript','evidence':{'asset_sha256':self.state['asset_sha256'],'source_kind':'authorized_local_file','truncated':False,'processor':'faster_whisper_local_segmented','duration_seconds':129.,'timeline':'absolute_seconds','segments':[{'start':53.,'end':56.,'text':'原转写候选'}]}}]
        (self.folder/'input.mp4').write_bytes(self.asset);self.save()
    def save(self):
        write(self.folder/'state.json',self.state);write(self.folder/'result.json',self.result)
    def tearDown(self):
        self.jobs.close();self.temp.cleanup()
    def snapshot(self):return build_snapshot(self.imported,'douyin','123')
    def choices(self,refs=None):return self.jobs.media_inputs(self.imported,self.snapshot(),self.run,refs)
    def ref(self):
        item=self.choices()['options'][0];return {k:item[k] for k in ('job_id','result_sha256','asset_sha256')}
    def test_explicit_selection_preserves_old_hash_prompt_and_adds_real_time_citations(self):
        old=self.snapshot();option=self.choices();self.assertEqual(option['selected'],[])
        self.assertEqual(old,build_snapshot(self.imported,'douyin','123',derived_inputs=[]))
        self.assertNotIn('derived_inputs',make_prompt(old))
        selected=self.choices([self.ref()])['selected'];new=build_snapshot(self.imported,'douyin','123',derived_inputs=selected)
        self.assertNotEqual(new['snapshot_hash'],old['snapshot_hash'])
        self.assertEqual(new['paragraphs'][-1]['start'],53.)
        self.assertEqual(new['paragraphs'][-1]['source_ref'],'derived:'+self.job+':0')
        self.assertIn('原转写候选',make_prompt(new));self.assertNotIn(str(self.root),make_prompt(new))
        title_only=json.loads(json.dumps(self.imported));title_only['records'][0]['body']=''
        title_snapshot=build_snapshot(title_only,'douyin','123',derived_inputs=selected)
        self.assertIn('仍可分析用户明确提供的derived_inputs候选',make_prompt(title_snapshot))
        self.assertNotIn('scope=title_only时只能分析标题；',make_prompt(title_snapshot))
        output={'content_analysis':{'summary':'模型摘要','segments':[{'paragraph':new['paragraphs'][-1]['paragraph'],'role':'候选','observation':'尚未核对'}],'claims':[],'reusable_methods':[],'limitations':[]},'comment_labels':[]}
        self.assertEqual(validate_result(new,output)['content_analysis']['segments'][0]['source_ref'],'derived:'+self.job+':0')
    def test_stale_result_asset_and_wrong_target_reject(self):
        ref=self.ref();self.result[0]['evidence']['segments'][0]['text']='改过的候选';self.save()
        with self.assertRaisesRegex(ValueError,'analysis_media_selection_invalid'):self.choices([ref])
        self.state['run_id']=str(uuid.uuid4());self.save()
        with self.assertRaisesRegex(ValueError,'analysis_media_selection_invalid'):self.choices([ref])
        self.state['run_id']=self.run;self.state['platform']='weibo';self.save()
        self.assertEqual(self.choices()['options'],[])
    def test_symlink_hardlink_and_asset_hash_reject(self):
        ref=self.ref();path=self.folder/'result.json';outside=self.root/'outside.json';outside.write_bytes(path.read_bytes());path.unlink();path.symlink_to(outside)
        with self.assertRaisesRegex(ValueError,'analysis_media_selection_invalid'):self.choices([ref])
        path.unlink();os.link(outside,path)
        self.assertEqual(self.choices()['options'],[])
        path.unlink();self.save();(self.folder/'input.mp4').write_bytes(b'changed')
        self.assertEqual(self.choices()['options'],[])
    def test_missing_snapshot_media_hash_requires_same_proven_entity(self):
        (self.folder/'input.mp4').unlink()
        row={'platform':'weibo','content_id':'OTHER','sha256':self.state['asset_sha256'],'path':'output/weibo/media/OTHER/video.mp4'}
        self.imported['media']=[row];self.assertEqual(self.choices()['options'],[])
        self.imported['media']=[{**row,'platform':'dy','content_id':'123'}]
        self.assertEqual(len(self.choices()['options']),1)
        self.imported['media']=[{**row,'platform':'dy','content_id':'OTHER'}]
        self.assertEqual(self.choices()['options'],[])
        self.imported['media']=[{**row,'content_id':'123'}]
        self.assertEqual(self.choices()['options'],[])
    def test_truncated_nonfinite_limit_and_secret_fail_closed(self):
        evidence=self.result[0]['evidence']
        for change in ({'truncated':True},{'segments':[{'start':0,'end':130,'text':'候选'}]},{'segments':[{'start':0,'end':10**1000,'text':'候选'}]},{'segments':[{'start':0,'end':1,'text':'x'*24001}]},{'segments':[{'start':0,'end':1,'text':'Cookie: sensitive=value'}]}):
            original=json.loads(json.dumps(evidence));evidence.update(change);self.save();self.assertEqual(self.choices()['options'],[]);evidence.clear();evidence.update(original)
        self.save()
        with self.assertRaisesRegex(ValueError,'invalid_analysis_media_reference'):self.choices([dict(self.ref(),job_id='../../private')])
        with self.assertRaisesRegex(ValueError,'invalid_analysis_media_reference'):self.choices([self.ref()]*2)
    def test_ocr_independent_kind_and_no_fake_audio_axis(self):
        self.state['kind']='ocr';self.state.pop('model_manifest_sha256');self.result[0]['kind']='ocr'
        self.result[0]['evidence'].update(raw_text='画面文字候选');self.result[0]['evidence'].pop('processor');self.save()
        selected=self.choices([self.ref()])['selected'][0]
        self.assertEqual(selected['segments'],[{'text':'画面文字候选'}]);self.assertEqual(selected['processor'],'apple_vision_local')
    def test_zhihu_and_dynamic_require_exact_proven_entity(self):
        self.imported['records']=[{'platform':'zhihu','kind':'content','content_id':'123','content_type':'answer','title':'问答','body':'正文'}]
        snapshot=build_snapshot(self.imported,'zhihu','123',entity_ref='zhihu:content:123:answer')
        self.state['platform']='zhihu';self.result[0]['platform']='zhihu';self.save()
        self.assertEqual(self.jobs.media_inputs(self.imported,snapshot,self.run)['options'],[])
        self.state['entity_ref']='zhihu:content:123:article';self.save()
        self.assertEqual(self.jobs.media_inputs(self.imported,snapshot,self.run)['options'],[])
        self.state['entity_ref']='zhihu:content:123:answer';self.save()
        self.assertEqual(len(self.jobs.media_inputs(self.imported,snapshot,self.run)['options']),1)


class HTTPTests(unittest.TestCase):
    post=fixtures.AnalysisHTTPTests.post
    def setUp(self):
        self.fixture=Tests();self.fixture.setUp();self.base=self.fixture.root
        self.app=dashboard.Application(self.base/'app');self.app.owner_tasks.close();self.app.watchlists.close()
        self.app.analysis_jobs=self.fixture.jobs
        self.server=dashboard.make_server(self.app,0);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url='http://127.0.0.1:'+str(self.server.server_port)
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.fixture.tearDown()
    def test_actual_http_explicit_preview_stale_selection_and_transfer_gate(self):
        fixture=self.fixture;payload={'run_id':fixture.run,'platform':'douyin','content_id':'123'}
        before=(fixture.folder/'result.json').read_bytes()
        with patch.object(self.app,'run',return_value={'ok':True,'result':fixture.imported}):
            old=self.post('lookup',payload);self.assertNotIn('derived_inputs',old['input_summary'])
            self.assertEqual(old['derived_options'][0]['segments'][0]['start'],53.)
            ref={k:old['derived_options'][0][k] for k in ('job_id','result_sha256','asset_sha256')}
            selected=self.post('lookup',{**payload,'derived_refs':[ref]})
            self.assertNotEqual(old['snapshot_hash'],selected['snapshot_hash'])
            self.assertEqual(selected['input_summary']['derived_inputs'][0]['asset_sha256'],fixture.state['asset_sha256'])
            with self.assertRaises(urllib.error.HTTPError) as e:self.post('start',{**payload,'derived_refs':[ref],'snapshot_hash':selected['snapshot_hash'],'allow_model_transfer':False})
            self.assertEqual(json.load(e.exception)['error'],'analysis_transfer_authorization_required')
            self.assertEqual((fixture.folder/'result.json').read_bytes(),before)
            fixture.result[0]['evidence']['segments'][0]['text']='changed';fixture.save()
            with self.assertRaises(urllib.error.HTTPError) as e:self.post('lookup',{**payload,'derived_refs':[ref]})
            self.assertEqual(json.load(e.exception)['error'],'analysis_media_selection_invalid')
    def test_typed_binding_is_server_derived_not_client_claim(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        starter=Mock(return_value={'state':'queued'});self.app.media_jobs=SimpleNamespace(start=starter,close=lambda:None)
        file={'platform':'zhihu','content_id':'123','source_content_type':'answer','path':'output/zhihu/media/123/answer/001.jpg'}
        record={'kind':'content','platform':'zhihu','content_id':'123','content_type':'answer','body':'原文'}
        payload={'run_id':self.fixture.run,'path':file['path'],'content_id':'123','kind':'ocr'}
        with patch.object(self.app,'media_file',return_value=self.base/'image.jpg'),patch.object(self.app,'run',return_value={'ok':True,'result':{'records':[record],'media':[file]}}):
            self.app.process_media('start',payload)
            self.assertEqual(starter.call_args.kwargs['entity_ref'],'zhihu:content:123:answer')
            with self.assertRaisesRegex(ValueError,'invalid_media_processing_action'):self.app.process_media('start',{**payload,'entity_ref':'zhihu:content:123:article'})


class CacheTests(unittest.TestCase):
    setUp=fixtures.JobsTests.setUp
    tearDown=fixtures.JobsTests.tearDown
    wait=fixtures.JobsTests.wait
    def test_fake_provider_selected_snapshot_and_old_cache_are_separate(self):
        imported=fixtures.imported_fixture()
        first=self.wait(self.manager.start(imported,'bili','video1'),'completed')
        before=(self.manager.folder(first['job_id'])/'result.json').read_bytes()
        item={'job_id':str(uuid.uuid4()),'kind':'asr','result_sha256':'a'*64,'asset_sha256':'b'*64,'processor':'faster_whisper_local_segmented','model_manifest_sha256':'c'*64,'processor_files':{'local_asr.py':'d'*64},'review_status':'not_reviewed','segments':[{'start':53.,'end':56.,'text':'派生候选非真人核对'}]}
        new=self.wait(self.manager.start(imported,'bili','video1',derived_inputs=[item]),'completed')
        self.assertNotEqual(new['cache_key'],first['cache_key'])
        self.assertEqual(new['result']['input_snapshot']['derived_inputs'][0]['segments'][0]['start'],53.)
        cached=self.manager.start(imported,'bili','video1');self.assertEqual(cached['job_id'],first['job_id']);self.assertTrue(cached['cached'])
        self.assertEqual((self.manager.folder(first['job_id'])/'result.json').read_bytes(),before)

if __name__=='__main__':unittest.main()
