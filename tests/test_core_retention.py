"""Offline inventory regression, not a collection or database acceptance test."""
import ast
import hashlib
from pathlib import Path
import runpy
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]


def definitions(path, names, namespace):
    tree = ast.parse((ROOT / path).read_text(encoding='utf-8'))
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace


class CoreRetentionTests(unittest.TestCase):
    def test_placeholder_search_apis_removed_without_losing_cross_core(self):
        path = ROOT / 'server/kol/kol_cross.py'
        tree = ast.parse(path.read_text(encoding='utf-8'))
        names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
        self.assertFalse(names & {'weibo_search', 'zhihu_search', 'douyin_search'})
        self.assertTrue({'clean', 'fp', 'sogou_wechat', 'load_state', 'main', 'channels_probe'} <= names)

    def test_cross_fingerprint_keeps_normalized_title_contract(self):
        # Inject only the explicit text-normalizer dependency; no network imports.
        ns = definitions('server/kol/kol_cross.py', {'fp'},
                         {'hashlib': hashlib, 'C': SimpleNamespace(cjk_norm=lambda s: s.lower())})
        self.assertEqual(ns['fp']('TITLE'), hashlib.sha1(b'title').hexdigest()[:16])

    def test_context_window_keeps_exact_source_and_absence(self):
        ns = definitions('server/kol/kol_context_backfill.py', {'window'}, {'W': 40})
        self.assertEqual(ns['window']('a' * 50 + '店名' + 'z' * 50, '店名'), 'a' * 40 + '店名' + 'z' * 40)
        self.assertIsNone(ns['window']('没有店名', '其他'))

    def test_scoring_core_normal_path_is_complete_and_repeatable(self):
        ns = runpy.run_path(str(ROOT / 'server/crowd/crowd_score.py'))
        inputs = ns['synthetic_inputs']()
        first = ns['compute'](inputs)
        self.assertEqual(first, ns['compute'](inputs))
        rows, stats = first
        self.assertEqual(len(rows), 5)
        self.assertEqual(stats['crowd_ratings_deduped'], 1)
        self.assertEqual(stats['notes_used'], 0)
        for row in rows:
            self.assertLessEqual(row['ci_lo'], row['post_mean'])
            self.assertLessEqual(row['post_mean'], row['ci_hi'])
        for q in [0.025, 0.5, 0.975]:
            self.assertAlmostEqual(ns['beta_ppf'](q, 1, 1), q, places=12)


if __name__ == '__main__':
    unittest.main()
