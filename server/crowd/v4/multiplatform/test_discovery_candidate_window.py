"""Bounded page fixtures; no source requests, account or browser profile access."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from discovery import PAGES, configure_discovery, DiscoveryUnavailable

LINKS = {'xhs':'/explore/'+'a'*24+'?xsec_token=PRIVATELOCATOR',
         'bili':'/video/BV1234567890/', 'dy':'/video/7590708381897651318',
         'wb':'https://m.weibo.cn/detail/5293049158180589', 'tieba':'/p/6616648271',
         'zhihu':'/question/900/answer/12345', 'ks':'/short-video/3xabcdef1234567'}
VARIABLES = {'xhs':'XHS_SPECIFIED_NOTE_URL_LIST','dy':'DY_SPECIFIED_ID_LIST',
             'wb':'WEIBO_SPECIFIED_ID_LIST','zhihu':'ZHIHU_SPECIFIED_ID_LIST','ks':'KS_SPECIFIED_ID_LIST'}


class CandidateWindowTests(unittest.TestCase):
    def exercise(self, platform, delayed=False, empty=False, cancellation=False, diagnostic_error=False):
        clock=[0.0]; actions=[]; config=SimpleNamespace(); link=LINKS[platform]
        class Response:
            status=200;request=SimpleNamespace(resource_type='xhr')
            url=PAGES[platform]+'api/SECRET/123456?token=SECRET'
            async def body(self):raise AssertionError('not a recognized feed response')
            async def header_value(self,*args):raise AssertionError('no non-feed header read')
        class Page:
            url=PAGES[platform]+'?token=SECRET'
            def __init__(self):self.callbacks={};self.scans=0
            def on(self,event,fn):self.callbacks[event]=fn
            def remove_listener(self,event,fn):
                assert self.callbacks[event] is fn
                del self.callbacks[event];actions.append(('cleanup',event))
            async def goto(self,url,**kwargs):
                actions.append(('goto',url));self.callbacks['response'](Response())
            async def wait_for_selector(self,*a,**k):
                raise AssertionError('first hidden anchor must not gate all visible candidates')
            async def eval_on_selector_all(self,selector,script):
                self.scans+=1;actions.append(('scan',self.scans))
                self.callbacks['response'](Response())
                if cancellation:raise asyncio.CancelledError
                assert 'getClientRects' in script and 'visibility' in script
                return [] if empty or delayed and self.scans==1 else [link]
            async def evaluate(self,script):
                actions.append(('diagnostic',None))
                if diagnostic_error:raise ValueError('PRIVATE ERROR MUST NOT BE STORED')
                return {'visible_anchor_total':2,'visible_video_count':0,'document_ready_state':'complete',
                        'title_present':True,'login_visible':False,'verification_visible':False,
                        'visible_data_e2e':['SECRET'],'private_text':'SECRET'}
        class Crawler:
            context_page=Page()
            async def get_specified_notes(self,targets=None):actions.append(('detail',targets if platform=='tieba' else getattr(config,VARIABLES[platform])))
            async def get_specified_awemes(self):actions.append(('detail',config.DY_SPECIFIED_ID_LIST))
            async def get_specified_videos(self,targets=None):actions.append(('detail',targets if platform=='bili' else config.KS_SPECIFIED_ID_LIST))
        async def advance(seconds):clock[0]+=seconds
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            configure_discovery(SimpleNamespace(CrawlerFactory=SimpleNamespace(CRAWLERS={platform:Crawler})),
                                {'platform':platform,'mode':'homefeed','max_items':1},folder)
            with patch.dict(sys.modules,{'config':config}),patch('discovery.time',SimpleNamespace(monotonic=lambda:clock[0])),patch('discovery.asyncio.sleep',side_effect=advance):
                if cancellation:
                    with self.assertRaises(asyncio.CancelledError):asyncio.run(Crawler().search())
                elif empty:
                    with self.assertRaises(DiscoveryUnavailable):asyncio.run(Crawler().search())
                else:asyncio.run(Crawler().search())
            observation=json.loads((folder/'discovery-observation.json').read_text())
            metadata=json.loads((folder/'discovery.json').read_text()) if (folder/'discovery.json').exists() else None
            self.assertEqual(Crawler.context_page.callbacks,{})
            self.assertEqual(observation['source_requests_added'],0)
            self.assertNotIn('SECRET',json.dumps(observation));self.assertNotIn('PRIVATE',json.dumps(observation))
            self.assertNotIn('123456',json.dumps(observation))
            if metadata:self.assertNotIn('PRIVATELOCATOR',json.dumps(metadata))
            return actions,observation,metadata,clock[0]

    def test_all_seven_platforms_scan_visible_cards_without_first_match_wait(self):
        for platform in LINKS:
            with self.subTest(platform=platform):
                actions,observation,metadata,_=self.exercise(platform)
                self.assertEqual(len([x for x in actions if x[0]=='detail']),1)
                self.assertEqual(len([x for x in actions if x[0]=='goto']),0 if platform in ('xhs','bili') else 1)
                self.assertEqual(observation['legal_sampled_link_count'],1)
                self.assertEqual(observation['visible_page']['state'],'available')
                self.assertEqual(metadata['coverage'],'visible_page_sample')

    def test_delayed_empty_and_diagnostic_failure_do_not_add_navigation_or_fake_success(self):
        for platform in ('xhs','bili','tieba','zhihu','ks'):
            with self.subTest(platform=platform):
                actions,_,metadata,_=self.exercise(platform,delayed=True)
                self.assertEqual(len([x for x in actions if x[0]=='scan']),2);self.assertIsNotNone(metadata)
                actions,observation,metadata,elapsed=self.exercise(platform,empty=True,diagnostic_error=True)
                self.assertEqual(elapsed,15);self.assertIsNone(metadata)
                self.assertFalse(any(x[0]=='detail' for x in actions));self.assertEqual(observation['visible_page']['state'],'unavailable')

    def test_cancellation_keeps_cleanup_and_does_not_dispatch(self):
        for platform in LINKS:
            with self.subTest(platform=platform):
                actions,_,metadata,_=self.exercise(platform,cancellation=True)
                self.assertIsNone(metadata);self.assertFalse(any(x[0]=='detail' for x in actions))


if __name__=='__main__':unittest.main()
