import asyncio
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from discovery import PAGES, configure_discovery, page_diagnostics, safe_observed_location


class DiagnosticTests(unittest.TestCase):
    def test_mobile_environment_alias_and_fixed_native_login_classification(self):
        self.assertEqual(PAGES['wb'],'https://m.weibo.cn/')
        for host in ['m.weibo.cn','weibo.com','www.weibo.com']:
            self.assertEqual(safe_observed_location('wb','https://'+host+'/')['origin'],'https://'+host)
        value=safe_observed_location('wb','https://passport.weibo.com/sso/signin?uid=SECRET')
        self.assertEqual(value,{'origin':'other','path':None,'location_kind':'official_login'})
        self.assertNotIn('SECRET',json.dumps(value))
        self.assertEqual(safe_observed_location('wb','https://passport.weibo.com/user/SECRET'),{'origin':'other','path':None})
        self.assertEqual(safe_observed_location('dy','about:blank')['location_kind'],'blank')
        self.assertEqual(safe_observed_location('dy','chrome-error://chromewebdata/?url=SECRET')['location_kind'],'browser_error')
    def test_url_dynamic_identity_query_and_foreign_host_never_saved(self):
        for url in ['https://www.douyin.com/user/123456?token=SECRET#SECRET',
                    'https://www.douyin.com/api/SECRET',
                    'https://www.douyin.com/api/%53ECRET']:
            value = safe_observed_location('dy', url)
            self.assertNotIn('SECRET', json.dumps(value))
            self.assertNotIn('123456', json.dumps(value))
            self.assertIn(':redacted', value['path'])
        self.assertEqual(safe_observed_location('dy', 'https://foreign.invalid/SECRET'), {'origin':'other','path':None})
        self.assertEqual(safe_observed_location('dy', 'https://www.douyin.com/aweme/v1/web/tab/feed/?token=SECRET')['path'], '/aweme/v1/web/tab/feed/')
        self.assertEqual(safe_observed_location('dy', 'https://SECRET@www.douyin.com/'), {'origin':'other','path':None})

    def test_page_signals_strict_fixed_enum_and_bounds(self):
        value = page_diagnostics({'visible_anchor_total':10**30,'visible_video_count':True,
             'title_present':'PERSONAL TITLE','login_visible':True,'verification_visible':False,
             'visible_data_e2e':['SECRET','feed-video'], 'personal_text':'SECRET'})
        self.assertEqual(value['visible_anchor_total'],10000)
        self.assertIsNone(value['visible_video_count'])
        self.assertIsNone(value['title_present'])
        self.assertEqual(value['visible_data_e2e'],['feed-video'])
        self.assertNotIn('SECRET',json.dumps(value))

    def test_failed_observation_bounded_metadata_only_and_cleanup(self):
        clock=[0.0];actions=[]
        class Response:
            status=200
            request=SimpleNamespace(resource_type='xhr')
            def __init__(self,index):self.url='https://www.douyin.com/api/SECRET/'+str(index)+'?token=SECRET'
            async def body(self):raise AssertionError('non-feed body must never be read')
            async def header_value(self,*args):raise AssertionError('non-feed headers must never be read')
        class Page:
            url='https://www.douyin.com/user/123456?token=SECRET'
            def on(self,event,callback):
                if not hasattr(self,'callbacks'):self.callbacks={}
                self.callbacks[event]=callback
            def remove_listener(self,event,callback):
                self.callbacks.pop(event);actions.append('cleanup')
            async def goto(self,*args,**kwargs):
                actions.append('goto')
                for index in range(50):self.callbacks['response'](Response(index))
                foreign=Response(0);foreign.url='https://foreign.invalid/SECRET';self.callbacks['response'](foreign)
                self.callbacks['requestfailed'](SimpleNamespace(resource_type='script',url='https://SECRET',failure='SECRET'))
                self.callbacks['pageerror'](Exception('SECRET'))
            async def eval_on_selector_all(self,*args):return ['/login','/user/123456']
            async def evaluate(self,script):
                actions.append('local_signals')
                return {'visible_anchor_total':19,'visible_video_count':0,'title_present':True,
                        'login_visible':False,'verification_visible':True,'visible_data_e2e':['SECRET','feed-video'],
                        'document_ready_state':'complete','script_element_count':3,'frame_element_count':0}
        class Crawler:
            context_page=Page()
            async def get_specified_awemes(self):raise AssertionError('empty discovery must not dispatch')
        async def sleep(seconds):clock[0]+=seconds
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            configure_discovery(SimpleNamespace(CrawlerFactory=SimpleNamespace(CRAWLERS={'dy':Crawler})),
                                {'platform':'dy','mode':'homefeed','max_items':1},root)
            with patch('discovery.time',SimpleNamespace(monotonic=lambda:clock[0])),patch('discovery.asyncio.sleep',side_effect=sleep):
                with self.assertRaisesRegex(ValueError,'discovery_empty_or_unavailable'):asyncio.run(Crawler().search())
            value=json.loads((root/'discovery-observation.json').read_text())
            self.assertEqual(len(value['official_response_paths']),30)
            self.assertEqual(value['responses'],[])
            self.assertEqual(value['legal_sampled_link_count'],0)
            self.assertEqual(value['visible_page']['verification_visible'],True)
            self.assertEqual(value['visible_page']['document_ready_state'],'complete')
            self.assertEqual(value['failed_request_counts']['script'],1)
            self.assertEqual(value['page_error_count'],1)
            self.assertNotIn('SECRET',json.dumps(value));self.assertNotIn('123456',json.dumps(value))
            self.assertEqual(actions,['goto','cleanup','cleanup','cleanup','local_signals'])
            self.assertFalse((root/'discovery.json').exists())


if __name__=='__main__':unittest.main()
