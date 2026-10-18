import ast
import asyncio
import copy
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Optional, Callable
import sys
import unittest
from unittest.mock import patch
from urllib.parse import urlparse, parse_qs

from zhihu_comments import install_hook

MC = Path('/Users/hubowen/WorkBuddy/2026-10-08-22-53-19/MediaCrawler')


def native_methods(path, class_name, names, namespace):
    tree = ast.parse(path.read_text())
    original = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    selected = [node for node in original.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    assert len(selected) == len(names)
    cls = ast.ClassDef(name=class_name, bases=[], keywords=[], body=selected, decorator_list=[])
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), str(path), 'exec'), namespace)
    return namespace[class_name]


class ZhihuComments(unittest.IsolatedAsyncioTestCase):
    def fixture(self, pages, limit=3, replies=True):
        ns = {'Dict': Dict, 'List': List, 'Optional': Optional, 'Callable': Callable, 'ZhihuContent': SimpleNamespace,
              'ZhihuComment': SimpleNamespace, 'extract_text_from_html': lambda value: value,
              'urlparse': urlparse, 'parse_qs': parse_qs}
        client = native_methods(MC/'media_platform/zhihu/client.py', 'ZhiHuClient', {'get_root_comments','get_child_comments'}, ns)
        extractor = native_methods(MC/'media_platform/zhihu/help.py', 'ZhihuExtractor', {'extract_comments','_extract_comment','extract_offset'}, ns)
        extractor._extract_content_or_comment_author = lambda self, value: SimpleNamespace(creator_hash='fixture',user_nickname='fixture')
        calls, saved, observed = [], [], []
        class Native(client):
            _extractor = extractor()
            async def get(self, uri, params):
                calls.append((uri, dict(params)))
                value = pages[len(calls)-1]
                if isinstance(value, BaseException): raise value
                return value
        install_hook(Native, limit, replies, observed.append)
        async def sink(rows): saved.extend(rows)
        return Native(), calls, saved, observed, sink

    def rows(self, ids, parent='0', children=0):
        return [{'id':identity,'type':'comment','reply_comment_id':parent,'child_comment_count':children,
                 'content':'exact fixture '+str(identity),'created_time':1,'author':{}} for identity in ids]

    def page(self, rows, offset='more', ended=False):
        return {'data':rows,'paging':{'is_end':ended,'next':'https://www.zhihu.com/api/v4/comment?offset='+offset}}

    async def test_real_sdk_transport_and_extractor_strict_root_reply_caps(self):
        pages=[self.page(self.rows(range(10,20),children=100)),self.page(self.rows(range(30,40),parent='10'))]
        before=copy.deepcopy(pages);native,calls,saved,observed,sink=self.fixture(pages)
        roots=await native.get_note_all_comments(SimpleNamespace(content_id='123',content_type='answer'),crawl_interval=0,callback=sink)
        self.assertEqual([r.comment_id for r in roots],['10','11','12'])
        self.assertEqual([r.comment_id for r in saved],['10','11','12','30','31','32'])
        self.assertEqual([r.parent_comment_id for r in saved],['0','0','0','10','10','10'])
        self.assertTrue(all(r.content_type=='answer' and r.content_id=='123' for r in saved))
        self.assertEqual(calls,[('/api/v4/comment_v5/answers/123/root_comment',{'order':'score','offset':'','limit':3}),('/api/v4/comment_v5/comment/10/child_comment',{'order':'sort','offset':'','limit':3})])
        self.assertEqual(pages,before)
        self.assertEqual((observed[0]['roots'],observed[0]['replies']),(3,3));self.assertFalse(observed[0]['source_complete'])

    async def test_native_offsets_preserved_and_duplicates_bounded(self):
        pages=[self.page(self.rows([10]),'cursor-a'),self.page(self.rows([10,11]),'cursor-b'),self.page(self.rows([12]),'cursor-c')]
        native,calls,saved,observed,sink=self.fixture(pages,replies=False)
        await native.get_note_all_comments(SimpleNamespace(content_id='123',content_type='article'),0,sink)
        self.assertEqual([r.comment_id for r in saved],['10','11','12'])
        self.assertEqual([r[1]['offset'] for r in calls],['','cursor-a','cursor-b'])
        self.assertEqual([r[1]['limit'] for r in calls],[3,2,1]);self.assertEqual(observed[0]['root_pages'],3)

    async def test_ended_and_stalled_cursor_do_not_request_extra_page(self):
        for page in [self.page(self.rows([10]),ended=True),self.page(self.rows([10]),offset='')]:
            native,calls,saved,observed,sink=self.fixture([page],replies=False)
            await native.get_note_all_comments(SimpleNamespace(content_id='123',content_type='answer'),0,sink)
            self.assertEqual(len(calls),1)

    async def test_budget_systemexit_and_cancel_propagate_with_safe_observation(self):
        for error in [SystemExit(73),SystemExit(76),SystemExit(77),asyncio.CancelledError()]:
            native,calls,saved,observed,sink=self.fixture([error])
            with self.assertRaises(type(error)):
                await native.get_note_all_comments(SimpleNamespace(content_id='123',content_type='answer'),0,sink)
            self.assertEqual(len(calls),1);self.assertEqual(saved,[]);self.assertEqual(observed[0]['roots'],0)

    async def test_invalid_shape_is_error_not_empty_but_actual_empty_is_valid(self):
        for response in [None,[],{}, {'data':None}, {'data':{}}, {'error':'fake failure'}]:
            native,calls,saved,observed,sink=self.fixture([response])
            with self.assertRaisesRegex(ValueError,'^invalid_zhihu_comment_response$'):
                await native.get_note_all_comments(SimpleNamespace(content_id='123',content_type='answer'),0,sink)
            self.assertEqual(len(calls),1);self.assertEqual(saved,[]);self.assertFalse(observed[0]['source_complete'])
        native,calls,saved,observed,sink=self.fixture([self.page([],ended=True)])
        self.assertEqual(await native.get_note_all_comments(SimpleNamespace(content_id='123',content_type='answer'),0,sink),[])
        self.assertEqual(len(calls),1);self.assertEqual(saved,[])
        native,calls,saved,observed,sink=self.fixture([self.page(self.rows([10],children=1),ended=True),{}])
        with self.assertRaisesRegex(ValueError,'^invalid_zhihu_comment_response$'):
            await native.get_note_all_comments(SimpleNamespace(content_id='123',content_type='answer'),0,sink)
        self.assertEqual([row.comment_id for row in saved],['10']);self.assertEqual(observed[0]['replies'],0)

    async def test_zero_limit_no_request_and_bool_float_limits_rejected(self):
        native,calls,saved,observed,sink=self.fixture([],limit=0)
        self.assertEqual(await native.get_note_all_comments(SimpleNamespace(content_id='123',content_type='answer'),0,sink),[])
        self.assertEqual(calls,[])
        for limit in [True,3.0,-1,201]:
            with self.assertRaises(ValueError):install_hook(type('Empty',(),{}),limit,True)
        with self.assertRaises(ValueError):install_hook(type('Empty',(),{}),3,1)

    async def test_runner_installs_hook_only_explicit_zhihu_comments(self):
        from mc_runner import configure_platform_hooks
        import zhihu_comments
        native=type('Native',(),{})
        with patch.dict(sys.modules,{'media_platform.zhihu.client':SimpleNamespace(ZhiHuClient=native)}),patch.object(zhihu_comments,'install_hook') as hook:
            configure_platform_hooks(None,{'platform':'zhihu','mode':'detail','comments':True,'media':False,'max_comments':3,'replies':True})
            self.assertEqual(hook.call_args.args[:3],(native,3,True))
            configure_platform_hooks(None,{'platform':'zhihu','mode':'detail','comments':False,'media':False})
            self.assertEqual(hook.call_count,1)


if __name__=='__main__':unittest.main()
