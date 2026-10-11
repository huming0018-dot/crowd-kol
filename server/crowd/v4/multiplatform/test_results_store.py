"""Offline business result contract tests. No model or source requests."""
import copy
import csv
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from results_store import ResultsStore


def imported(run='run-1', body='Original text', likes=1):
    return {'run_id': run, 'source_kind': 'mediacrawler_api', 'coverage': 'unverified',
            'source': {'adapter_version': 'test'}, 'records': [
                {'kind': 'content', 'platform': 'xiaohongshu', 'content_id': 'n1',
                 'author_id': 'a1', 'title': 'Title', 'body': body,
                 'published_at_reported': 1704067200000,
                 'metrics': {'liked_count': {'reported_value': likes}},
                 'origin': {'run_id': run, 'line': 1}},
                {'kind': 'comment', 'platform': 'xiaohongshu', 'content_id': 'n1',
                 'comment_id': 'c1', 'parent_comment_id': '0', 'text': 'Root'},
                {'kind': 'comment', 'platform': 'xiaohongshu', 'content_id': 'n1',
                 'comment_id': 'c2', 'parent_comment_id': 'c1', 'text': 'Reply'},
                {'kind': 'author', 'platform': 'xiaohongshu', 'author_id': 'a1',
                 'display_name': 'Author'}],
            'media': [{'content_id': 'n1', 'path': 'output/xhs/media/n1.jpg',
                       'bytes': 10, 'status': 'downloaded_by_external_executor'}]}


class ResultsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = ResultsStore(self.temporary.name)

    def test_idempotent_import_and_restart(self):
        first = self.store.ingest(imported())
        self.assertEqual(first['added_versions'], 5)
        again = ResultsStore(self.temporary.name).ingest(imported())
        self.assertTrue(again['duplicate_import'])
        self.assertEqual(again['results_revision'], first['results_revision'])
        self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)

    def test_metrics_are_observations_not_body_versions(self):
        first = self.store.ingest(imported())
        second = self.store.ingest(imported('run-2', likes=9))
        self.assertEqual(second['added_versions'], 0)
        detail = self.store.detail('xhs', 'n1')
        self.assertEqual(len(detail['versions']), 1)
        self.assertEqual(len(detail['observations']), 2)
        self.assertEqual(detail['contents'][0]['metrics']['liked_count']['reported_value'], 9)
        before = self.store.detail('xhs', 'n1', first['results_revision'])
        self.assertEqual(before['contents'][0]['metrics']['liked_count']['reported_value'], 1)

    def test_content_changes_and_revert_preserve_versions(self):
        self.store.ingest(imported())
        self.store.ingest(imported('run-2', body='Changed'))
        self.store.ingest(imported('run-3'))
        result = self.store.detail('xhs', 'n1')
        self.assertEqual(len(result['versions']), 2)
        self.assertEqual(result['contents'][0]['body'], 'Original text')
        self.assertEqual(len({v['body_hash'] for v in result['versions']}), 2)

    def test_exact_platform_relationships_and_media_manifest(self):
        data = imported()
        data['records'].append({'kind': 'content', 'platform': 'weibo', 'content_id': 'n1', 'body': 'Elsewhere'})
        data['media'][0]['platform'] = 'xiaohongshu'
        self.store.ingest(data)
        result = self.store.detail('xhs', 'n1')
        self.assertEqual(result['stats']['comments'], 2)
        self.assertEqual(result['stats']['root_comments'], 1)
        self.assertEqual(result['stats']['orphan_replies'], 0)
        self.assertEqual(result['authors'][0]['display_name'], 'Author')
        self.assertEqual(len(result['media']), 1)
        self.assertFalse(result['media'][0]['reward_eligible'])

    def test_unmapped_media_is_not_guessed_as_attached(self):
        data = imported()
        del data['media'][0]['content_id']
        self.store.ingest(data)
        self.assertEqual(self.store.detail('xhs', 'n1')['media'], [])
        media = self.store.list_results({'kind': 'media'})['items'][0]
        self.assertIn('content_id', media['missing_fields'])

    def test_missing_parent_and_orphan_not_counted_as_roots(self):
        data = imported()
        data['records'][1]['parent_comment_id'] = None
        data['records'][2]['parent_comment_id'] = 'unknown-comment'
        self.store.ingest(data)
        stats = self.store.detail('xhs', 'n1')['stats']
        self.assertEqual((stats['root_comments'], stats['unknown_parent_comments'], stats['orphan_replies']), (0, 1, 1))

    def test_dynamic_supported(self):
        data = imported()
        data['records'][0]['kind'] = 'dynamic'
        self.store.ingest(data)
        self.assertEqual(self.store.detail('xhs', 'n1')['contents'][0]['kind'], 'dynamic')

    def test_owner_evaluation_is_version_bound_and_not_reward(self):
        before = self.store.ingest(imported())['results_revision']
        evaluation = self.store.evaluate('xhs', 'n1', 4, ['useful', 'food'])
        self.assertFalse(evaluation['reward_eligible'])
        self.assertEqual(self.store.list_results({'tags': ['useful']})['total'], 1)
        self.assertEqual(self.store.list_results({'tags': ['useful']}, revision=before)['total'], 0)
        self.store.ingest(imported('run-2', body='New text'))
        self.assertEqual(self.store.detail('xhs', 'n1')['contents'][0]['owner_evaluations'], [])
        with sqlite3.connect(self.store.path) as db:
            names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertFalse({'rewards', 'ratings', 'participants'} & names)

    def test_business_tags_use_latest_evaluation_without_erasing_history(self):
        self.store.ingest(imported())
        previous = self.store.evaluate('xhs', 'n1', 2, ['old'])['results_revision']
        self.store.evaluate('xhs', 'n1', 4, ['new'])
        self.assertEqual(self.store.list_results({'tags': ['old']})['total'], 0)
        self.assertEqual(self.store.list_results({'tags': ['old']}, revision=previous)['total'], 1)
        self.assertEqual(len(self.store.detail('xhs', 'n1')['contents'][0]['owner_evaluations']), 2)

    def test_filter_by_author_platform_and_reported_time(self):
        self.store.ingest(imported())
        result = self.store.list_results({'platform': 'xhs', 'author_id': 'a1', 'kind': 'content',
             'published_after': '2024-01-01T00:00:00+00:00', 'published_before': '2024-01-01T08:00:00+08:00'})
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['items'][0]['published_at_utc'], '2024-01-01T00:00:00Z')
        self.assertEqual(self.store.list_results({'published_after': '2025-01-01T00:00:00Z'})['total'], 0)

    def test_unknown_source_time_not_fabricated(self):
        data = imported()
        data['records'][0]['published_at_reported'] = '2024-01-01 12:00:00'
        self.store.ingest(data)
        row = self.store.detail('xhs', 'n1')['contents'][0]
        self.assertIsNone(row['published_at_utc'])
        self.assertIn('published_at_utc', row['missing_fields'])
        self.assertEqual(self.store.list_results({'published_after': '2023-01-01T00:00:00Z'})['total'], 0)

    def test_cursor_freezes_revision_after_concurrent_import(self):
        self.store.ingest(imported())
        first = self.store.list_results(limit=2)
        data = imported('run-2')
        data['records'].append({'kind': 'content', 'platform': 'xiaohongshu', 'content_id': 'n2', 'body': 'Another'})
        self.store.ingest(data)
        second = self.store.list_results(limit=2, cursor=first['next_cursor'])
        self.assertEqual(first['results_revision'], second['results_revision'])
        self.assertEqual(second['total'], 5)
        self.assertFalse({v['entity_ref'] for v in first['items']} & {v['entity_ref'] for v in second['items']})
        with self.assertRaisesRegex(ValueError, 'invalid_results_cursor'):
            self.store.list_results({'kind': 'comment'}, cursor=first['next_cursor'])

    def test_json_jsonl_csv_fixed_revision_and_formula_escape(self):
        data = imported(body=' =HYPERLINK("https://example.com")')
        data['records'][0]['title'] = '\t+SUM(1,2)'
        revision = self.store.ingest(data)['results_revision']
        exported = self.store.export('json', revision=revision)
        self.assertEqual(json.loads(exported['data'])['row_count'], 5)
        self.assertEqual(json.loads(self.store.export('jsonl')['data'].splitlines()[0])['kind'], 'export_manifest')
        rows = list(csv.DictReader(io.StringIO(self.store.export('csv')['data'].decode('utf-8-sig'))))
        content = next(row for row in rows if row['kind'] == 'content')
        self.assertTrue(content['title'].startswith("'\t+"))
        self.assertTrue(content['body'].startswith("' ="))
        self.store.ingest(imported('run-2', body='Updated'))
        self.assertEqual(exported['data'], self.store.export('json', revision=revision)['data'])
        self.assertIn('missing_field_counts', self.store.export('csv')['manifest'])

    def test_sensitive_input_rejected_without_partial_commit(self):
        data = imported()
        data['records'].append({'kind': 'content', 'platform': 'xiaohongshu', 'content_id': 'n2', 'body': 'Cookie=private-value'})
        with self.assertRaisesRegex(ValueError, 'results_sensitive'):
            self.store.ingest(data)
        self.assertEqual(self.store.list_results()['total'], 0)
        data = imported()
        data['records'][0]['author'] = {'access_token': 'fake'}
        with self.assertRaisesRegex(ValueError, 'results_sensitive_field'):
            self.store.ingest(data)

    def test_malformed_text_and_anonymous_media_rejected(self):
        data = imported()
        data['records'][0]['body'] = 123
        with self.assertRaisesRegex(ValueError, 'invalid_results_text_field'):
            self.store.ingest(data)
        data = imported()
        data['media'] = [{'bytes': 2}]
        with self.assertRaisesRegex(ValueError, 'missing_media_identity'):
            self.store.ingest(data)

    def test_validation_errors_are_typed(self):
        self.store.ingest(imported())
        calls = [lambda: self.store.list_results({'unknown': 1}),
                 lambda: self.store.list_results({'published_after': '2024-01-01'}),
                 lambda: self.store.list_results({'tags': 'food'}),
                 lambda: self.store.list_results(limit=True),
                 lambda: self.store.list_results(offset=1),
                 lambda: self.store.list_results(cursor='%%%'),
                 lambda: self.store.list_results(revision=True),
                 lambda: self.store.evaluate('xhs', 'n1', True),
                 lambda: self.store.evaluate('xhs', 'n1', 6),
                 lambda: self.store.evaluate('xhs', 'n1', 4, tags=''),
                 lambda: self.store.export('html')]
        for call in calls:
            with self.subTest(call=call), self.assertRaises(ValueError):
                call()

    def test_parallel_import_is_single_logical_commit(self):
        results, errors = [], []
        def run():
            try:
                results.append(ResultsStore(self.temporary.name).ingest(imported()))
            except Exception as exc:
                errors.append(exc)
        threads = [threading.Thread(target=run) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(sum(not row['duplicate_import'] for row in results), 1)
        self.assertEqual(self.store.list_results()['results_revision'], 1)

    def test_symlink_database_rejected(self):
        another = Path(self.temporary.name) / 'other'
        another.mkdir()
        results = another / 'results'
        results.mkdir()
        (results / 'results.sqlite3').symlink_to(self.store.path)
        with self.assertRaisesRegex(ValueError, 'unsafe_results_database'):
            ResultsStore(another)

    def test_xlsx_when_installed_or_explicit_missing_dependency(self):
        self.store.ingest(imported(body='\ufeff=SUM(1,2)'))
        try:
            result = self.store.export('xlsx')
        except ValueError as exc:
            self.assertEqual(str(exc), 'xlsx_dependency_missing')
            return
        from openpyxl import load_workbook
        workbook = load_workbook(io.BytesIO(result['data']))
        self.assertEqual(workbook.sheetnames, ['results', 'manifest'])
        self.assertEqual(workbook['results'].max_row, 6)
        header = [cell.value for cell in workbook['results'][1]]
        body_column = header.index('body')
        content_row = next(row for row in workbook['results'].iter_rows(min_row=2) if row[0].value == 'content')
        self.assertTrue(content_row[body_column].value.startswith("'\ufeff="))
        self.assertEqual(content_row[body_column].data_type, 's')


if __name__ == '__main__':
    unittest.main()
