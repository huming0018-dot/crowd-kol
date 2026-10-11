import asyncio
from datetime import datetime, timezone
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
        before = datetime.now(timezone.utc)
        class Page:
            async def goto(self, *args, **kwargs):
                self.goto_url = args[0]
            async def wait_for_selector(self, *args, **kwargs):
                pass
            async def eval_on_selector_all(self, *args):
                return ['https://www.bilibili.com/video/BV1234567890/',
                        'https://www.bilibili.com/video/BV1234567890/',
                        'https://evil.invalid/video/BV9999999999/',
                        'https://www.bilibili.com/video/BV2345678901/']
        class Crawler:
            def __init__(self):
                self.context_page = Page()
            async def get_specified_videos(self, targets):
                self.targets = targets
        upstream = SimpleNamespace(CrawlerFactory=SimpleNamespace(CRAWLERS={'bili': Crawler}))
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            configure_discovery(upstream, {'platform': 'bili', 'mode': 'trending', 'max_items': 2}, run)
            crawler = Crawler()
            asyncio.run(crawler.search())
            self.assertEqual(crawler.targets, ['BV1234567890', 'BV2345678901'])
            metadata = json.loads((run / 'discovery.json').read_text())
            self.assertEqual(metadata['discovery_kind'], 'trending')
            self.assertFalse(metadata['following_feed'])
            self.assertNotIn('token', json.dumps(metadata))
            observed_at = datetime.fromisoformat(metadata['observed_at'])
            self.assertEqual(observed_at.utcoffset().total_seconds(), 0)
            self.assertLessEqual(before, observed_at)
            self.assertLessEqual(observed_at, datetime.now(timezone.utc))
            self.assertEqual(metadata['position_basis'], 'deduplicated_visible_selection_order')
            self.assertEqual(metadata['candidates'], [
                {'content_id': 'BV1234567890', 'sample_position': 1, 'platform_rank': None},
                {'content_id': 'BV2345678901', 'sample_position': 2, 'platform_rank': None}])
            self.assertEqual(metadata['candidate_ids'], [c['content_id'] for c in metadata['candidates']])


if __name__ == '__main__':
    unittest.main()
