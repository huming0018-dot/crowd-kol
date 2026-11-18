"""Offline contract checks for retained KOL library boundary; no service calls."""
import ast
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "server" / "kol" / "_lib"

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class BoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fake = types.ModuleType("requests")
        fake.Response = object
        fake.RequestException = RuntimeError
        def blocked(*a, **k):
            raise AssertionError("Real HTTP is forbidden in these tests")
        fake.request = blocked
        with tempfile.TemporaryDirectory() as app:
            with patch.dict(os.environ, {"FOOD_APP_DIR": app}, clear=True):
                with patch.dict(sys.modules, {"requests": fake}):
                    cls.C = load("kol_test_common", LIB / "common.py")
                    with patch.dict(sys.modules, {"common": cls.C}):
                        cls.S = load("kol_test_names", LIB / "authority_sitemap.py")

    def test_names_and_eligibility(self):
        self.assertEqual(self.S.core("福一零一五（上海店）"), "福1015")
        self.assertEqual(self.C.cjk_norm("和菓子本舖"), "和果子本铺")
        self.assertTrue(self.S.eligible("唐阁"))
        self.assertFalse(self.S.eligible("pop"))
        self.assertEqual(self.C.looks_like_brand("抹茶面包")[0], False)
        self.assertEqual(self.C.looks_like_brand("Proust")[0], True)

    def test_removed_pipeline_not_present(self):
        for name in ("clean_phone", "parse_location", "source_kind", "read_jsonl"):
            self.assertFalse(hasattr(self.C, name))
        for name in ("run", "reconcile", "collect_shanghai", "make_matcher"):
            self.assertFalse(hasattr(self.S, name))

    def test_headers_with_synthetic_config(self):
        with patch.object(self.C, "SERVICE", "TEST_ONLY"):
            self.assertEqual(self.C.headers()["Authorization"], "Bearer TEST_ONLY")

    def test_http_retry_preserved(self):
        responses = [types.SimpleNamespace(status_code=503), types.SimpleNamespace(status_code=200)]
        with patch.object(self.C, "headers", return_value={}):
            with patch.object(self.C.requests, "request", side_effect=responses) as call:
                with patch.object(self.C.time, "sleep") as sleep:
                    self.assertEqual(self.C.req("GET", "/fake").status_code, 200)
                    self.assertEqual(call.call_count, 2)
                    sleep.assert_called_once_with(1)

    def test_pagination_preserved(self):
        def response(rows):
            return types.SimpleNamespace(raise_for_status=lambda: None, json=lambda: rows)
        with patch.object(self.C, "req", side_effect=[response([1, 2]), response([3])]) as call:
            with patch.object(self.C.time, "sleep"):
                self.assertEqual(self.C.fetch_all("fake", page=2), [1, 2, 3])
                self.assertIn("offset=2", call.call_args[0][1])

    def test_repository_consumers_keep_requested_exports(self):
        seen = {"C": set(), "S": set()}
        for file in (ROOT / "server" / "kol").glob("kol_*.py"):
            for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                    if node.value.id in seen:
                        seen[node.value.id].add(node.attr)
        self.assertTrue(seen["C"] and seen["S"])
        for alias, module in (("C", self.C), ("S", self.S)):
            for name in seen[alias]:
                self.assertTrue(hasattr(module, name), (alias, name))

if __name__ == "__main__":
    unittest.main()
