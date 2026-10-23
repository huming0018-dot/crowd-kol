"""Business entity selection and comment scope; fake local provider only."""
import copy
import json
import threading
import unittest
import urllib.error
from unittest.mock import patch

import analysis_contract as contract
import dashboard
import test_analysis as fixtures
from test_analysis import imported_fixture, model_fixture


def typed_fixture():
    records=[{'platform':'zhihu','kind':'content','content_id':'123','content_type':kind,
              'title':kind,'body':'同数字ID的'+kind+'原文'} for kind in ('answer','article')]
    for cid,fields in [('a',{'content_type':'answer'}),('b',{'platform_fields':{'content_type':'article'}}),
                       ('unknown',{}),('conflict',{'content_type':'answer','platform_fields':{'content_type':'article'}})]:
        records.append({'platform':'zhihu','kind':'comment','content_id':'123','comment_id':cid,
                        'text':'原评论'+cid,'parent_comment_id':None,**fields})
    return {'run_id':'00000000-0000-4000-8000-000000000001','records':records}


class EntityContractTests(unittest.TestCase):
    def test_reported_weibo_roots_preserve_parent_ids_and_unknown(self):
        rows=[{'platform':'weibo','kind':'content','content_id':'123','body':'原微博'}]
        rows += [{'platform':'weibo','kind':'comment','content_id':'123','comment_id':str(i),
                  'text':'根评论','parent_comment_id':str(i),'parent_status':'reported_root'} for i in range(1,4)]
        rows += [{'platform':'weibo','kind':'comment','content_id':'123','comment_id':'reply','text':'回复','parent_comment_id':'1'},
                 {'platform':'weibo','kind':'comment','content_id':'123','comment_id':'unknown','text':'未知','parent_comment_id':None,'parent_status':'reported_root'}]
        snapshot=contract.build_snapshot({'records':rows},'wb','123')
        self.assertEqual((snapshot['coverage']['roots'],snapshot['coverage']['replies'],snapshot['coverage']['unknown_parent']),(3,1,1))
        self.assertEqual([r['parent_comment_id'] for r in snapshot['comments']],['1','2','3','1',None])
        output=model_fixture(snapshot)
        for field in ('segments','claims','reusable_methods'):output['content_analysis'][field]=[]
        result=contract.validate_result(snapshot,output)
        self.assertEqual(result['comment_statistics']['coverage']['roots'],3)

    def test_typed_content_and_known_comment_scope_no_type_guess(self):
        imported=typed_fixture(); before=copy.deepcopy(imported)
        answer=contract.build_snapshot(imported,'zhihu','123','zhihu:content:123:answer')
        article=contract.build_snapshot(imported,'zhihu','123','zhihu:content:123:article')
        self.assertEqual([r['comment_id'] for r in answer['comments']],['a'])
        self.assertEqual([r['comment_id'] for r in article['comments']],['b'])
        self.assertEqual(answer['coverage']['excluded_reasons'],{'different_content_type':1,'unconfirmed_content_type':2})
        self.assertEqual(answer['content']['content_type'],'answer')
        self.assertNotEqual(answer['snapshot_hash'],article['snapshot_hash'])
        self.assertEqual(imported,before)
        prompt=json.loads(contract.make_prompt(answer).split('材料JSON：\n')[1])
        self.assertEqual(prompt['entity_ref'],'zhihu:content:123:answer')
        self.assertEqual([r['comment_id'] for r in prompt['comments']],['a'])

    def test_aggregate_ambiguous_even_when_text_equal_and_selectors_scoped(self):
        imported=typed_fixture()
        for row in imported['records'][:2]:row.update(title='same',body='same')
        with self.assertRaisesRegex(ValueError,'ambiguous_analysis_entity'):
            contract.build_snapshot(imported,'zhihu','123')
        for bad in ['weibo:content:123','zhihu:content:456:answer','zhihu:content:123:question',{},False]:
            with self.assertRaisesRegex(ValueError,'invalid_results_entity_ref'):
                contract.build_snapshot(imported,'zhihu','123',bad)
        with self.assertRaisesRegex(ValueError,'analysis_entity_not_found'):
            contract.build_snapshot(imported,'zhihu','123','zhihu:content:123:zvideo')

    def test_typed_colon_identifier_does_not_disable_comment_filter(self):
        imported=typed_fixture()
        for row in imported['records']:row['content_id']='a:b'
        snapshot=contract.build_snapshot(imported,'zhihu','a:b','zhihu:content:a:b:answer')
        self.assertEqual(snapshot['content']['content_type'],'answer')
        self.assertEqual([row['comment_id'] for row in snapshot['comments']],['a'])

    def test_dynamic_kind_retained_no_same_numeric_video_comments(self):
        imported={'records':[{'platform':'bilibili','kind':'dynamic','content_id':'123','body':'原动态文字'},
                              {'platform':'bilibili','kind':'content','content_id':'123','body':'另一个原视频'},
                              {'platform':'bilibili','kind':'comment','content_id':'123','comment_id':'c','text':'视频评论','parent_comment_id':'0'}]}
        dynamic=contract.build_snapshot(imported,'bili','123','bilibili:dynamic:123')
        self.assertEqual(dynamic['content']['kind'],'dynamic')
        self.assertEqual(dynamic['content']['text'],'原动态文字')
        self.assertEqual(dynamic['comments'],[])
        self.assertEqual(dynamic['coverage']['excluded_reasons'],{'dynamic_comments_not_supported':1})
        prompt=json.loads(contract.make_prompt(dynamic).split('材料JSON：\n')[1]);self.assertEqual(prompt['kind'],'dynamic')
        with self.assertRaisesRegex(ValueError,'ambiguous_analysis_entity'):
            contract.build_snapshot(imported,'bili','123')
        only={'records':[imported['records'][0]]}
        self.assertEqual(contract.build_snapshot(only,'bili','123')['content']['kind'],'dynamic')

    def test_non_zhihu_legacy_snapshot_and_root_id_semantics_unchanged(self):
        imported=imported_fixture(); a=contract.build_snapshot(imported,'bili','video1')
        self.assertNotIn('entity_ref',a['content']);self.assertNotIn('kind',a['content'])
        self.assertEqual((a['coverage']['roots'],a['coverage']['replies'],a['coverage']['unknown_parent']),(1,1,1))
        old=contract.build_snapshot({'records':[{'platform':'zhihu','kind':'content','content_id':'123','body':'旧裸ID正文'}, {'platform':'zhihu','kind':'comment','content_id':'123','comment_id':'unknown','text':'未知归属','parent_comment_id':None}]},'zhihu','123')
        self.assertEqual(len(old['comments']),1);self.assertNotIn('entity_ref',old['content'])


class EntityJobsTests(unittest.TestCase):
    setUp=fixtures.JobsTests.setUp
    tearDown=fixtures.JobsTests.tearDown
    wait=fixtures.JobsTests.wait
    def test_fake_provider_typed_cache_and_original_reports_are_isolated(self):
        imported=typed_fixture()
        answer=self.manager.start(imported,'zhihu','123',entity_ref='zhihu:content:123:answer'); a=self.wait(answer,'completed')
        folder=self.manager.folder(a['job_id']); before=(folder/'result.json').read_bytes()
        article=self.manager.start(imported,'zhihu','123',entity_ref='zhihu:content:123:article'); b=self.wait(article,'completed')
        self.assertNotEqual(a['job_id'],b['job_id']);self.assertNotEqual(a['cache_key'],b['cache_key'])
        self.assertEqual(a['result']['input_snapshot']['content']['content_type'],'answer')
        self.assertEqual(b['result']['input_snapshot']['content']['content_type'],'article')
        self.assertTrue(self.manager.start(imported,'zhihu','123',entity_ref='zhihu:content:123:answer')['cached'])
        self.assertEqual((folder/'result.json').read_bytes(),before)
        self.assertEqual(len((self.base/'calls.jsonl').read_text().splitlines()),2)


class EntityHTTPTests(unittest.TestCase):
    post=fixtures.AnalysisHTTPTests.post
    wait=fixtures.JobsTests.wait
    def setUp(self):
        fixtures.JobsTests.setUp(self)
        self.app=dashboard.Application(self.base/'http-runtime');self.app.owner_tasks.close();self.app.watchlists.close()
        self.app.analysis_jobs=self.manager
        self.server=dashboard.make_server(self.app,0);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url='http://127.0.0.1:'+str(self.server.server_port)
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();fixtures.JobsTests.tearDown(self)
    def test_http_selector_lookup_start_snapshot_gate_and_cache(self):
        imported=typed_fixture();payload={'run_id':imported['run_id'],'platform':'zhihu','content_id':'123','entity_ref':'zhihu:content:123:answer'}
        with patch.object(self.app,'run',return_value={'ok':True,'result':imported}):
            lookup=self.post('lookup',payload);self.assertEqual(lookup['input_summary']['comments'],1)
            self.assertEqual(lookup['input_summary']['entity_ref'],payload['entity_ref'])
            wrong={**payload,'entity_ref':'zhihu:content:123:article','snapshot_hash':lookup['snapshot_hash'],'allow_model_transfer':True}
            with self.assertRaises(urllib.error.HTTPError) as e:self.post('start',wrong)
            self.assertEqual(json.load(e.exception)['error'],'analysis_snapshot_changed')
            self.assertFalse((self.base/'calls.jsonl').exists())
            request={**payload,'snapshot_hash':lookup['snapshot_hash'],'allow_model_transfer':True}
            job=self.post('start',request);done=self.wait(job,'completed')
            self.assertEqual(done['result']['input_snapshot']['content']['content_type'],'answer')
            self.assertEqual(self.post('lookup',payload)['job_id'],job['job_id'])
            self.assertTrue(self.post('start',request)['cached'])
            with self.assertRaises(urllib.error.HTTPError) as e:self.post('lookup',{k:v for k,v in payload.items() if k!='entity_ref'})
            self.assertEqual(json.load(e.exception)['error'],'ambiguous_analysis_entity')
    def test_http_wrong_selector_rejects_without_fake_provider(self):
        imported=typed_fixture();payload={'run_id':imported['run_id'],'platform':'zhihu','content_id':'123'}
        with patch.object(self.app,'run',return_value={'ok':True,'result':imported}):
            for ref in ['weibo:content:123','zhihu:content:456:answer',True,[],'zhihu:content:123:zvideo']:
                with self.assertRaises(urllib.error.HTTPError) as e:self.post('lookup',{**payload,'entity_ref':ref})
                self.assertEqual(e.exception.code,400)
        self.assertFalse((self.base/'calls.jsonl').exists())

    def test_http_dynamic_preview_and_fake_report_keep_kind_and_scope(self):
        imported={'run_id':'00000000-0000-4000-8000-000000000001','records':[
            {'platform':'bilibili','kind':'dynamic','content_id':'123','body':'原动态文字'},
            {'platform':'bilibili','kind':'content','content_id':'123','body':'同数字视频正文'},
            {'platform':'bilibili','kind':'comment','content_id':'123','comment_id':'c','text':'视频评论','parent_comment_id':'0'}]}
        payload={'run_id':imported['run_id'],'platform':'bilibili','content_id':'123','entity_ref':'bilibili:dynamic:123'}
        with patch.object(self.app,'run',return_value={'ok':True,'result':imported}):
            preview=self.post('lookup',payload)
            self.assertEqual(preview['input_summary']['kind'],'dynamic')
            self.assertEqual(preview['input_summary']['comments'],0)
            self.assertEqual(preview['input_summary']['coverage']['excluded_reasons'],{'dynamic_comments_not_supported':1})
            self.assertFalse((self.base/'calls.jsonl').exists())
            job=self.post('start',{**payload,'snapshot_hash':preview['snapshot_hash'],'allow_model_transfer':True})
            done=self.wait(job,'completed')
            snapshot=done['result']['input_snapshot']
            self.assertEqual(snapshot['content']['kind'],'dynamic')
            self.assertEqual(snapshot['content']['text'],'原动态文字')
            self.assertEqual(snapshot['comments'],[])
            self.assertEqual(self.post('status',{'job_id':job['job_id']})['state'],'completed')


if __name__=='__main__':unittest.main()
