import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from tieba_browser_requests import install


class Tests(unittest.TestCase):
    def test_debits_original_browser_fetch_and_preserves_result_without_payload(self):
        with tempfile.TemporaryDirectory() as t:
            events = []
            result = {'private': 'must not persist'}
            class Native:
                async def _fetch_json_by_browser(self, uri, **kwargs):
                    events.append('fetch'); return result
            install(Native, t, lambda: events.append('debit'))
            self.assertIs(asyncio.run(Native()._fetch_json_by_browser('/c/f/pb/page_pc', data={'secret': 'private'})), result)
            self.assertEqual(events, ['debit', 'fetch'])
            saved = Path(t, 'phase.json').read_text()
            self.assertNotIn('private', saved)
            self.assertEqual(json.loads(saved)['tieba_browser_request'], {'endpoint': 'post_detail', 'state': 'returned', 'reason': None})

    def test_failure_survives_native_catch_and_unknown_is_not_retried(self):
        with tempfile.TemporaryDirectory() as t:
            events = []
            class Native:
                async def _fetch_json_by_browser(self, uri):
                    events.append('fetch'); raise ValueError('Cookie=never log this')
            install(Native, t, lambda: events.append('debit'))
            with self.assertRaises(ValueError):
                asyncio.run(Native()._fetch_json_by_browser('/c/s/pc/sync'))
            self.assertEqual(events, ['debit', 'fetch'])
            saved = Path(t, 'phase.json').read_text()
            self.assertNotIn('Cookie', saved)
            self.assertEqual(json.loads(saved)['tieba_browser_request']['state'], 'failed')

    def test_sync_then_detail_debits_each_native_call(self):
        with tempfile.TemporaryDirectory() as t:
            calls = []
            class Native:
                async def _fetch_json_by_browser(self, uri): return {'ok': True}
                async def _get_pc_page_data(self):
                    await self._fetch_json_by_browser('/c/s/pc/sync')
                    return await self._fetch_json_by_browser('/c/f/pb/page_pc')
            install(Native, t, lambda: calls.append('attempt'))
            self.assertEqual(asyncio.run(Native()._get_pc_page_data()), {'ok': True})
            self.assertEqual(len(calls), 2)

    def test_budget_exit_happens_before_native_fetch(self):
        with tempfile.TemporaryDirectory() as t:
            class Native:
                async def _fetch_json_by_browser(self, uri): raise AssertionError('must not dispatch')
            def debit(): raise SystemExit(73)
            install(Native, t, debit)
            with self.assertRaises(SystemExit):
                asyncio.run(Native()._fetch_json_by_browser('/c/f/pb/page_pc'))
            self.assertFalse(Path(t, 'phase.json').exists())


if __name__ == '__main__': unittest.main()
