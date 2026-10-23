import asyncio
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from discovery import PAGES, configure_discovery


class ResponseSizeTests(unittest.TestCase):
    def run_response(self, platform='dy', declared=None, body=None, failure=None):
        calls=[]; clock=[0.0]; config=SimpleNamespace()
        identity='7590708381897651318'
        if body is None:
            body=json.dumps({'status_code':0,'aweme_list':[{'aweme_id':identity}],
                             'padding':'x'*(2*1024*1024)}).encode()
        class Response:
            status=200
            request=SimpleNamespace(resource_type='fetch')
            url=('https://www.douyin.com/aweme/v2/web/module/feed/?private=SECRET'
                 if platform=='dy' else 'https://weibo.com/ajax/feed/hottimeline?private=SECRET')
            async def header_value(self,*args):
                if failure=='header':raise RuntimeError('PRIVATE HEADER')
                return declared
            async def body(self):
                calls.append('read_existing_body')
                if failure=='body':raise RuntimeError('PRIVATE BODY')
                return body
        class Page:
            url=PAGES[platform]
            def __init__(self):self.callbacks={}
            def on(self,event,callback):self.callbacks[event]=callback
            def remove_listener(self,event,callback):self.callbacks.pop(event)
            async def goto(self,*args,**kwargs):calls.append('goto');self.callbacks['response'](Response())
            async def eval_on_selector_all(self,*args):return []
            async def evaluate(self,*args):return {'visible_anchor_total':0,'title_present':True}
        class Crawler:
            context_page=Page()
            async def get_specified_awemes(self):calls.append(config.DY_SPECIFIED_ID_LIST)
            async def get_specified_notes(self):calls.append(config.WEIBO_SPECIFIED_ID_LIST)
        async def advance(seconds):clock[0]+=seconds
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            configure_discovery(SimpleNamespace(CrawlerFactory=SimpleNamespace(CRAWLERS={platform:Crawler})),
                                {'platform':platform,'mode':'homefeed','max_items':1},root)
            with patch.dict(sys.modules,{'config':config}),patch('discovery.time',SimpleNamespace(monotonic=lambda:clock[0])),patch('discovery.asyncio.sleep',side_effect=advance):
                try:asyncio.run(Crawler().search())
                except ValueError as error:self.assertEqual(str(error),'discovery_empty_or_unavailable')
            self.assertEqual(Crawler.context_page.callbacks,{})
            observation=json.loads((root/'discovery-observation.json').read_text())
            self.assertNotIn('SECRET',json.dumps(observation))
            self.assertNotIn('PRIVATE',json.dumps(observation))
            return calls,observation['responses'][0],(root/'discovery.json').exists(),clock[0]

    def test_dy_received_two_mib_body_is_accepted_and_records_only_byte_counts(self):
        calls,summary,success,_=self.run_response()
        self.assertTrue(success)
        self.assertEqual(calls,['goto','read_existing_body',['7590708381897651318']])
        self.assertEqual(summary['parser_limit_bytes'],8*1024*1024)
        self.assertGreater(summary['actual_body_bytes'],2*1024*1024)
        self.assertIsNone(summary['declared_body_bytes'])
        self.assertEqual(summary['status'],'matched')

    def test_exact_eight_mib_boundary_is_accepted(self):
        prefix=b'{"status_code":0,"aweme_list":[{"aweme_id":"7590708381897651318"}],"padding":"'
        body=prefix+b'x'*(8*1024*1024-len(prefix)-2)+b'"}'
        _,summary,success,_=self.run_response(declared=str(len(body)),body=body)
        self.assertTrue(success)
        self.assertEqual(summary['declared_body_bytes'],8*1024*1024)
        self.assertEqual(summary['actual_body_bytes'],8*1024*1024)

    def test_declared_oversize_dy_and_unchanged_wb_limit_do_not_read_body(self):
        for platform,size,limit in [('dy',8*1024*1024+1,8*1024*1024),('wb',1048577,1048576)]:
            with self.subTest(platform=platform):
                calls,summary,success,_=self.run_response(platform=platform,declared=str(size))
                self.assertEqual(calls,['goto']);self.assertFalse(success)
                self.assertEqual(summary['declared_body_bytes'],size)
                self.assertIsNone(summary['actual_body_bytes'])
                self.assertEqual(summary['parser_limit_bytes'],limit)
                self.assertEqual(summary['failure_kind'],'declared_size_exceeds_limit')

    def test_actual_oversize_and_decode_failures_remain_bounded_failed(self):
        for body,kind in [(b'x'*(8*1024*1024+1),'actual_size_exceeds_limit'),
                          (b'not-json-PRIVATE','invalid_json'),(b'\xff','invalid_encoding')]:
            with self.subTest(kind=kind):
                calls,summary,success,elapsed=self.run_response(body=body)
                self.assertFalse(success);self.assertEqual(summary['failure_kind'],kind)
                self.assertEqual(summary['actual_body_bytes'],len(body))
                self.assertLessEqual(elapsed,15)

    def test_read_errors_and_invalid_header_never_include_error_text(self):
        for failure,declared,kind in [('header',None,'header_read_failed'),
                                     ('body',None,'body_read_failed'),
                                     (None,'PRIVATE','invalid_content_length'),
                                     (None,'9'*1000,'invalid_content_length'),
                                     (None,'١٢٣','invalid_content_length')]:
            with self.subTest(kind=kind):
                _,summary,success,_=self.run_response(failure=failure,declared=declared)
                self.assertFalse(success);self.assertEqual(summary['failure_kind'],kind)


if __name__=='__main__':unittest.main()
