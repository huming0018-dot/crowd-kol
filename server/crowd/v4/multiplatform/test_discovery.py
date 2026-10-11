import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from discovery import select_links, configure_discovery
import mc_runner
from owner_tasks import plan


class DiscoveryTests(unittest.TestCase):
    def test_link_scope_locator_limit_and_dedupe(self):
        note = 'a' * 24
        url = '/explore/' + note + '?xsec_token=normal-locator'
        chosen = select_links('xhs', [url, url, 'https://evil.invalid' + url,
                                     '/explore/' + 'b' * 24], 1)
        self.assertEqual(len(chosen), 1)
        self.assertEqual(chosen[0][0], note)
        self.assertIn('xsec_token=', chosen[0][1])
        self.assertEqual(select_links('bili', ['/video/BV1234567890/?spm=x',
                        'https://[broken/video/BV1234567890',
                        'https://www.bilibili.com:invalid/video/BV1234567890',
                        'https://evil.invalid/video/BV2345678901', '/video/av12'], 2),
                         [('BV1234567890', 'BV1234567890')])

    def test_request_contract_and_no_search_inflation(self):
        p = mc_runner.validate({'platform': 'bili', 'mode': 'homefeed', 'targets': [],
                               'max_items': 1, 'purpose': 'noncommercial_research'})
        argv = mc_runner.argv_for(p, Path('/tmp/output'))
        self.assertEqual(argv[argv.index('--type') + 1], 'search')
        self.assertEqual(p['max_items'], 1)
        result = plan({'platforms': ['bili'], 'mode': 'trending', 'desired_items': 1,
                       'max_api_requests': 5, 'purpose': 'noncommercial_research',
                       'idempotency_key': 'test-discovery'})
        self.assertEqual(result['children'][0]['state'], 'queued')
        self.assertEqual(result['children'][0]['request']['targets'], [])
        with self.assertRaises(ValueError):
            plan({'platforms': ['wb'], 'mode': 'homefeed', 'desired_items': 1,
                  'max_api_requests': 5, 'purpose': 'noncommercial_research',
                  'idempotency_key': 'unsupported-discovery'})

    def test_real_hook_contract_without_source_requests(self):
        class Page:
            async def goto(self, *args, **kwargs):
                self.goto_url = args[0]
            async def wait_for_selector(self, *args, **kwargs):
                pass
            async def eval_on_selector_all(self, *args):
                return ['https://www.bilibili.com/video/BV1234567890/']
        class Crawler:
            def __init__(self):
                self.context_page = Page()
            async def get_specified_videos(self, targets):
                self.targets = targets
        upstream = SimpleNamespace(CrawlerFactory=SimpleNamespace(CRAWLERS={'bili': Crawler}))
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            configure_discovery(upstream, {'platform': 'bili', 'mode': 'trending', 'max_items': 1}, run)
            crawler = Crawler()
            asyncio.run(crawler.search())
            self.assertEqual(crawler.targets, ['BV1234567890'])
            metadata = json.loads((run / 'discovery.json').read_text())
            self.assertEqual(metadata['discovery_kind'], 'trending')
            self.assertFalse(metadata['following_feed'])
            self.assertNotIn('token', json.dumps(metadata))


if __name__ == '__main__':
    unittest.main()
