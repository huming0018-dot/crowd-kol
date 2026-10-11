"""Offline native-call contracts; these tests do not prove live feed availability."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from discovery import PAGES, SUPPORT, configure_discovery, select_links
import mc_runner
from owner_tasks import plan


SAMPLES = {
    'dy': ('/video/7590708381897651318?from=feed', '7590708381897651318'),
    'wb': ('https://m.weibo.cn/detail/5293049158180589', '5293049158180589'),
    'tieba': ('/p/10234567890?fr=home', '10234567890'),
    'zhihu': ('https://zhuanlan.zhihu.com/p/2010393405658793620', '2010393405658793620'),
    'ks': ('/short-video/3xabcdef1234567?from=home', '3xabcdef1234567'),
}


class FiveDiscoveryTests(unittest.TestCase):
    def test_link_contract_and_host_isolation(self):
        for platform, (link, identity) in SAMPLES.items():
            with self.subTest(platform=platform):
                wrong_host = 'https://evil.invalid' + (link if link.startswith('/') else '/p/' + identity)
                chosen = select_links(platform, [wrong_host, link, link], 2)
                self.assertEqual(len(chosen), 1)
                self.assertEqual(chosen[0][0], identity)
                self.assertEqual(select_links(platform, ['https://user:password@' + PAGES[platform].split('/')[2] + '/p/12345',
                    'https://[invalid/', 'https://www.douyin.com:bad/video/12345'], 1), [])
        self.assertEqual(select_links('dy', ['/?modal_id=7590708381897651318', '/?modal_id=not-id', '/search?modal_id=12345'], 2),
                         [('7590708381897651318', '7590708381897651318')])
        self.assertEqual(select_links('wb', ['https://m.weibo.cn/status/ABCDE12345', '/12345/ABCDE12345',
                                           '/u/12345', 'https://m.weibo.cn/detail/12345#login'], 3), [('ABCDE12345', 'ABCDE12345')])
        with self.assertRaisesRegex(ValueError, 'invalid_discovery_request'):
            select_links('dy', '/video/12345', 1)

    def test_typed_zhihu_collisions_and_noncontent_rejection(self):
        chosen = select_links('zhihu', ['/question/900/answer/12345', 'https://zhuanlan.zhihu.com/p/12345',
                                      '/zvideo/12345', '/question/900', '/people/12345',
                                      'https://www.zhihu.com/p/12345', '/question/900/answer/12345?utm=1'], 10)
        self.assertEqual(chosen, [('12345', 'https://www.zhihu.com/question/900/answer/12345'),
                                 ('12345', 'https://zhuanlan.zhihu.com/p/12345'),
                                 ('12345', 'https://www.zhihu.com/zvideo/12345')])

    def test_same_native_detail_comments_media_pipeline_and_public_metadata(self):
        config = SimpleNamespace()
        variables = {'dy': 'DY_SPECIFIED_ID_LIST', 'wb': 'WEIBO_SPECIFIED_ID_LIST',
                     'zhihu': 'ZHIHU_SPECIFIED_ID_LIST', 'ks': 'KS_SPECIFIED_ID_LIST'}
        for platform, (link, identity) in SAMPLES.items():
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as directory:
                calls = []
                class Page:
                    async def goto(self, url, **kwargs):
                        calls.append(('goto', url))
                    async def wait_for_selector(self, selector, **kwargs):
                        calls.append(('selector', selector))
                    async def eval_on_selector_all(self, selector, script):
                        self.script = script
                        return [link, link]
                class Crawler:
                    context_page = Page()
                    async def get_specified_notes(self, targets=None):
                        calls.append(('detail', targets if platform == 'tieba' else getattr(config, variables[platform])))
                    async def get_specified_awemes(self):
                        calls.append(('detail', config.DY_SPECIFIED_ID_LIST))
                    async def get_specified_videos(self):
                        calls.append(('detail', config.KS_SPECIFIED_ID_LIST))
                upstream = SimpleNamespace(CrawlerFactory=SimpleNamespace(CRAWLERS={platform: Crawler}))
                with patch.dict(sys.modules, {'config': config}):
                    configure_discovery(upstream, {'platform':platform, 'mode':'homefeed', 'max_items':1}, Path(directory))
                    asyncio.run(Crawler().search())
                self.assertEqual(calls[0], ('goto', PAGES[platform]))
                self.assertEqual(calls[-1], ('detail', [select_links(platform, [link], 1)[0][1]]))
                self.assertEqual(len([x for x in calls if x[0] == 'detail']), 1)
                metadata = json.loads((Path(directory) / 'discovery.json').read_text())
                self.assertEqual(metadata['candidate_ids'], [identity])
                self.assertFalse(metadata['following_feed'])
                self.assertEqual(metadata['coverage'], 'visible_page_sample')
                self.assertEqual(metadata['candidates'][0]['sample_position'], 1)
                self.assertIsNone(metadata['candidates'][0]['platform_rank'])
                self.assertNotIn('xsec_token', json.dumps(metadata))
                if platform == 'zhihu':
                    self.assertEqual(metadata['candidates'][0]['source_content_type'], 'article')

    def test_empty_page_does_not_fallback_to_search_or_details(self):
        class Page:
            async def goto(self, *args, **kwargs): pass
            async def wait_for_selector(self, *args, **kwargs): pass
            async def eval_on_selector_all(self, *args): return ['/search?q=demo']
        class Crawler:
            context_page = Page()
            async def get_specified_awemes(self): raise AssertionError('unexpected detail')
        with tempfile.TemporaryDirectory() as directory:
            configure_discovery(SimpleNamespace(CrawlerFactory=SimpleNamespace(CRAWLERS={'dy': Crawler})),
                                {'platform':'dy','mode':'homefeed','max_items':1}, Path(directory))
            clock = iter((0, 0, 15, 15))
            with patch('discovery.time', SimpleNamespace(monotonic=lambda:next(clock))):
                with self.assertRaisesRegex(ValueError, 'discovery_empty_or_unavailable'):
                    asyncio.run(Crawler().search())
            self.assertFalse((Path(directory) / 'discovery.json').exists())

    def test_asynchronous_cards_wait_for_legal_candidates_in_one_bounded_window(self):
        for delayed in (True, False):
            with self.subTest(delayed=delayed), tempfile.TemporaryDirectory() as directory:
                clock = [0.0]; evaluations = []; navigations = []; calls = []
                async def advance(seconds):
                    clock[0] += seconds
                class Page:
                    async def goto(self, url, **kwargs): navigations.append(url)
                    async def wait_for_selector(self, *args, **kwargs): pass
                    async def eval_on_selector_all(self, *args):
                        evaluations.append(clock[0])
                        return ['https://m.weibo.cn/detail/5293049158180589'] if delayed and len(evaluations) > 1 else ['/login', '/hot/recommend']
                class Crawler:
                    context_page = Page()
                    async def get_specified_notes(self): calls.append(config.WEIBO_SPECIFIED_ID_LIST)
                config = SimpleNamespace()
                configure_discovery(SimpleNamespace(CrawlerFactory=SimpleNamespace(CRAWLERS={'wb': Crawler})),
                                    {'platform':'wb','mode':'homefeed','max_items':1}, Path(directory))
                with patch.dict(sys.modules, {'config': config}), patch('discovery.time', SimpleNamespace(monotonic=lambda:clock[0])), patch('discovery.asyncio.sleep', side_effect=advance):
                    if delayed:
                        asyncio.run(Crawler().search())
                        self.assertEqual(calls, [['5293049158180589']])
                        self.assertEqual(len(evaluations), 2)
                    else:
                        with self.assertRaisesRegex(ValueError, 'discovery_empty_or_unavailable'):
                            asyncio.run(Crawler().search())
                        self.assertEqual(calls, [])
                        self.assertFalse((Path(directory) / 'discovery.json').exists())
                        self.assertEqual(clock[0], 15)
                self.assertEqual(navigations, [PAGES['wb']])

    def test_owner_total_budget_no_per_platform_inflation_and_trending_stays_bili(self):
        request = {'platforms': list(SAMPLES), 'mode':'homefeed', 'desired_items':5,
                   'max_api_requests':25, 'purpose':'noncommercial_research', 'idempotency_key':'five-feed-offline'}
        value = plan(request)
        self.assertEqual(sum(c['item_quota'] for c in value['children']), 5)
        self.assertEqual(sum(c['request']['max_api_requests'] for c in value['children']), 25)
        for c in value['children']:
            self.assertEqual(c['request']['targets'], [])
            self.assertEqual(c['request']['max_items'], 1)
            argv = mc_runner.argv_for(c['request'], Path('/tmp/isolated-output'))
            self.assertEqual(argv[argv.index('--type') + 1], 'search')
        for platform in SAMPLES:
            with self.subTest(platform=platform), self.assertRaises(ValueError):
                plan({**request, 'platforms':[platform], 'mode':'trending', 'desired_items':1})

    def test_import_new_homefeed_tag_preserves_native_body_hash_and_old_unknown(self):
        for platform, (_, identity) in SAMPLES.items():
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); run_id = str(uuid.uuid4()); run = root / 'runs' / run_id
                folder = run / 'output' / platform / 'jsonl'; folder.mkdir(parents=True)
                row = {mc_runner.ID_KEYS[platform]:identity, 'content':'original body', 'title':'original title'}
                (folder / 'detail_contents_test.jsonl').write_text(json.dumps(row) + '\n')
                manifest = {'run_id':run_id, 'request':{'platform':platform, 'mode':'homefeed'}, 'source':{}}
                mc_runner.write(run / 'manifest.json', manifest)
                mc_runner.write(run / 'status.json', {'state':'completed'})
                with patch.object(mc_runner, 'status', return_value={'state':'completed'}):
                    old = mc_runner.import_output(root, {'run_id':run_id})['records'][0]
                    manifest['discovery_contract_version'] = 1
                    mc_runner.write(run / 'manifest.json', manifest)
                    new = mc_runner.import_output(root, {'run_id':run_id})['records'][0]
                self.assertNotIn('discovery_kind', old)
                self.assertEqual(new['discovery_kind'], 'homefeed')
                self.assertEqual(new['record_hash'], old['record_hash'])
                self.assertEqual(new['body'], old['body'])


if __name__ == '__main__':
    unittest.main()
