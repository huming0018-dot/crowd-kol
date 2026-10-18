import asyncio
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from discovery import PAGES, click_wb_recommendation, configure_discovery


class NavigationTests(unittest.TestCase):
    def test_visible_unique_navigation_only_not_body_or_follow(self):
        for mode,expected in [('unique',['推荐']),('hidden',[]),('body',[]),('ambiguous',[]),('following',[])]:
            with self.subTest(mode=mode):
                clicks=[]
                class Target:
                    async def is_visible(self):return mode!='hidden'
                    async def evaluate(self,*args):return mode!='body'
                    async def click(self,**kwargs):clicks.append('推荐')
                class Locator:
                    def __init__(self,label):self.label=label
                    async def count(self):
                        if mode=='following':return 1 if self.label=='关注' else 0
                        return (2 if mode=='ambiguous' else 1) if self.label=='推荐' else 0
                    def nth(self,index):return Target()
                page=SimpleNamespace(get_by_text=lambda label,exact:Locator(label))
                signals={'visible_labels':{'推荐':False,'热门':False,'关注':False},'clicked_label':None,'click_state':'not_attempted'}
                with patch('discovery.time',SimpleNamespace(monotonic=lambda:0)):
                    asyncio.run(click_wb_recommendation(page,15,signals))
                    asyncio.run(click_wb_recommendation(page,15,signals))
                self.assertEqual(clicks,expected)
                if mode=='unique':self.assertEqual(signals['click_state'],'completed')
                if mode=='following':self.assertTrue(signals['visible_labels']['关注'])

    def test_click_timeout_never_retried(self):
        calls=[]
        class Target:
            async def is_visible(self):return True
            async def evaluate(self,*args):return True
            async def click(self,**kwargs):calls.append('click');raise TimeoutError('private error text')
        class Locator:
            async def count(self):return 1
            def nth(self,index):return Target()
        page=SimpleNamespace(get_by_text=lambda label,exact:Locator())
        signals={'visible_labels':{},'clicked_label':None,'click_state':'not_attempted'}
        with patch('discovery.time',SimpleNamespace(monotonic=lambda:0)):
            asyncio.run(click_wb_recommendation(page,15,signals));asyncio.run(click_wb_recommendation(page,15,signals))
        self.assertEqual(calls,['click']);self.assertEqual(signals['click_state'],'failed_or_timeout')
        self.assertNotIn('private',json.dumps(signals))

    def test_actual_hook_click_native_response_then_existing_detail_once(self):
        calls=[];clock=[0.0];config=SimpleNamespace()
        class Response:
            status=200;url='https://m.weibo.cn/api/container/getIndex?containerid=102803'
            request=SimpleNamespace(resource_type='xhr')
            async def header_value(self,*args):return None
            async def body(self):return json.dumps({'ok':1,'data':{'cards':[{'mblog':{'idstr':'5293049158180589'}}]}}).encode()
        class Page:
            url=PAGES['wb']
            def __init__(self):self.callbacks={}
            def on(self,event,callback):self.callbacks[event]=callback
            def remove_listener(self,event,callback):self.callbacks.pop(event)
            async def goto(self,*args,**kwargs):calls.append('goto')
            async def eval_on_selector_all(self,*args):return []
            async def evaluate(self,*args):return {'visible_anchor_total':0,'title_present':True}
            def get_by_text(self,label,exact):
                page=self
                class Target:
                    async def is_visible(self):return True
                    async def evaluate(self,*args):return True
                    async def click(self,**kwargs):calls.append('click');page.callbacks['response'](Response())
                class Locator:
                    async def count(self):return 1 if label=='推荐' else 0
                    def nth(self,index):return Target()
                return Locator()
        class Crawler:
            context_page=Page()
            async def get_specified_notes(self):calls.append(config.WEIBO_SPECIFIED_ID_LIST)
        async def advance(seconds):clock[0]+=seconds
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            configure_discovery(SimpleNamespace(CrawlerFactory=SimpleNamespace(CRAWLERS={'wb':Crawler})),
                                {'platform':'wb','mode':'homefeed','max_items':1},root)
            with patch.dict(sys.modules,{'config':config}),patch('discovery.time',SimpleNamespace(monotonic=lambda:clock[0])),patch('discovery.asyncio.sleep',side_effect=advance):
                asyncio.run(Crawler().search())
            self.assertEqual(calls,['goto','click',['5293049158180589']])
            self.assertEqual(Crawler.context_page.callbacks,{})
            observation=json.loads((root/'discovery-observation.json').read_text())
            self.assertEqual(observation['homepage_navigation']['clicked_label'],'推荐')
            discovery=json.loads((root/'discovery.json').read_text())
            self.assertEqual(discovery['coverage'],'seen_response_sample')
            self.assertFalse(discovery['following_feed'])


if __name__=='__main__':unittest.main()
