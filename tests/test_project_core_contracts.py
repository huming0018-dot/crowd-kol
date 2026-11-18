"""Offline checks of project computation; HTTP and notifications are blocked.

These checks cover bounded working behavior, not full entity/sentiment quality.
Known counterexamples are reported separately during repository screening.
"""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "server/kol/_lib"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    with patch.object(sys, "path", list(sys.path)):
        spec.loader.exec_module(module)
    return module


class ProjectCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.http = types.ModuleType("requests")
        cls.http.Response = object
        cls.http.RequestException = RuntimeError
        for verb in ("get", "post", "request", "patch", "delete"):
            setattr(cls.http, verb, Mock(side_effect=AssertionError("HTTP forbidden")))
        with patch.dict(os.environ, {"FOOD_APP_DIR": cls.temp.name,
                                     "FOOD_DATA_DIR": cls.temp.name}, clear=True):
            with patch.dict(sys.modules, {"requests": cls.http, "map_helpers": None}):
                cls.C = load("project_common", LIB / "common.py")
                with patch.dict(sys.modules, {"common": cls.C}):
                    cls.S = load("project_names", LIB / "authority_sitemap.py")
                with patch.dict(sys.modules, {"common": cls.C, "authority_sitemap": cls.S}):
                    for attr in ("kol_monitor", "kol_post_ingest", "kol_identity",
                                 "kol_router", "kol_trust_grade", "kol_context_backfill"):
                        setattr(cls, attr, load("project_" + attr, ROOT / "server/kol" / (attr + ".py")))
        cls.score = load("project_score", ROOT / "server/crowd/crowd_score.py")
        core = types.ModuleType("common_core")
        core.config = lambda key, default=None: cls.temp.name if key == "FOOD_DATA_DIR" else default
        core.fetch_all = Mock(side_effect=AssertionError("Database forbidden"))
        core.log = Mock(side_effect=AssertionError("Logging forbidden"))
        with patch.dict(sys.modules, {"common_core": core, "notifier": types.ModuleType("notifier")}):
            cls.tracking = load("project_tracking", ROOT / "server/crowd/crowd_tracking.py")

    def test_beta_against_analytic_distributions(self):
        for x in (0, .1, .25, .5, .9, 1):
            self.assertAlmostEqual(self.score.beta_cdf(x, 2, 3), 6*x*x - 8*x**3 + 3*x**4, places=12)
        for q in (.025, .5, .975):
            self.assertAlmostEqual(self.score.beta_ppf(q, 2, 1), q**.5, places=12)

    def test_owner_posterior_has_exact_pseudocounts(self):
        rows, stats = self.score.compute({"proofs": [], "tasks": [],
                                         "owner_ratings": [{"store": "幸福火锅", "score": 5}]})
        self.assertEqual((rows[0]["alpha"], rows[0]["beta"]), (26, 1))
        self.assertAlmostEqual(rows[0]["post_mean"], 1 + 4*26/27)
        self.assertTrue(rows[0]["owner_anchor_sufficient"])
        self.assertEqual(stats["owner_ratings"], 1)

    def test_rating_dedup_and_note_nonparticipation(self):
        pr = {"kind": "rating", "participant_id": "p1", "matched_store": "幸福火锅", "rating": 5}
        inputs = {"proofs": [pr, dict(pr), {"kind": "note", "matched_store": "另一家店"}],
                  "tasks": [], "owner_ratings": []}
        rows, stats = self.score.compute(inputs)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["alpha"], rows[0]["beta"]), (2, 1))
        self.assertEqual((stats["crowd_ratings_deduped"], stats["notes_seen"], stats["notes_used"]), (1, 1, 0))
        self.assertFalse(rows[0]["owner_anchor_sufficient"])

    def test_cluster_and_cap_discount_against_hand_calculation(self):
        def ev(i, cluster):
            return {"m": 1, "p": 1, "cluster": cluster, "source": "crowd", "ts": "", "tie": i}
        self.assertEqual(self.score.pool_cell([ev(i, "p") for i in range(3)])[:3], (2.75, 1, 1.75))
        self.assertEqual(self.score.pool_cell([ev(i, str(i)) for i in range(22)])[:3], (21.75, 1, 20.75))

    def test_pairwise_order_and_cross_cuisine_exclusion(self):
        inputs = {"proofs": [], "tasks": [], "owner_ratings": [
            {"store": "甲火锅", "score": 4, "compare_to": "乙火锅"},
            {"store": "乙火锅", "score": 4, "compare_to": "丙面馆"}]}
        rows, stats = self.score.compute(inputs)
        by_name = {r["store"]: r for r in rows}
        self.assertLess(by_name["甲火锅"]["rank_in_cuisine"], by_name["乙火锅"]["rank_in_cuisine"])
        self.assertEqual((stats["comparisons"], stats["comparisons_cross_cell_skipped"]), (1, 1))

    def test_version_content_binding(self):
        inputs = {"proofs": [], "tasks": [], "owner_ratings": [{"store": "幸福火锅", "score": 5}]}
        _, stats = self.score.compute(inputs)
        version = self.score.model_version(inputs, stats)[0]
        inputs["owner_ratings"][0]["score"] = 1
        self.assertNotEqual(version, self.score.model_version(inputs, stats)[0])

    def test_json_replay_cli_does_not_fetch_or_write(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "input.json"
            source.write_text(json.dumps({"proofs": [], "tasks": [], "owner_ratings": []}), encoding="utf-8")
            with patch.object(sys, "argv", ["crowd_score.py", "--from-json", str(source), "--write"]):
                with patch.object(self.score, "fetch_inputs", side_effect=AssertionError("fetch forbidden")):
                    with patch.object(self.score, "write_rows", side_effect=AssertionError("write forbidden")):
                        with contextlib.redirect_stdout(io.StringIO()):
                            self.assertEqual(self.score.main(), 0)

    def test_post_alias_longest_match_and_window_separation(self):
        rows = [{"id": 1, "name": "幸福饭店", "aliases": '["幸福老店"]'},
                {"id": 2, "name": "如意饭店"},
                {"id": 3, "name": "饭店"},
                {"id": 4, "name": "停业饭店", "status": "closed"}]
        idx = self.kol_post_ingest.build_name_index(rows)
        mentions = self.kol_post_ingest.ingest_one({"text": "幸福老店好吃；如意饭店难吃。"}, idx)
        self.assertEqual([(m["rid"], m["polarity"]) for m in mentions], [(1, "pos"), (2, "neg")])
        self.assertFalse(any(item[1] == 4 for item in idx))

    def test_monitor_keeps_ambiguity_and_unique_district_hint(self):
        restaurants = [{"id": 1, "name": "幸福饭店", "district": "静安区"},
                       {"id": 2, "name": "幸福饭店", "district": "徐汇区"}]
        matched, ambiguous = self.kol_monitor.anchor_mentions("幸福饭店好吃", {"幸福饭店": restaurants})
        self.assertEqual(matched, [])
        self.assertEqual(ambiguous[0]["restaurant_id"], None)
        matched, ambiguous = self.kol_monitor.anchor_mentions("静安区幸福饭店好吃", {"幸福饭店": restaurants})
        self.assertEqual([m["restaurant_id"] for m in matched], [1])
        self.assertEqual(ambiguous, [])

    def test_post_commit_payload_uses_only_project_archive_tables(self):
        response = types.SimpleNamespace(status_code=201, json=lambda: [{"id": 51}])
        rec = {"kol_id": 7, "platform": "fixture", "post_url": "https://example.invalid/post", "text": "幸福饭店好吃"}
        idx = self.kol_post_ingest.build_name_index([{"id": 1, "name": "幸福饭店"}])
        with patch.object(self.C, "headers", return_value={}), patch.object(self.C, "BASE", "https://example.invalid/rest/v1"):
            with patch.object(self.http, "post", return_value=response, side_effect=None) as post:
                self.kol_post_ingest.ingest_one(rec, idx, commit=True)
        self.assertEqual(post.call_count, 2)
        self.assertIn("/food_kol_posts?", post.call_args_list[0].args[0])
        self.assertIn("/food_kol_mentions?", post.call_args_list[1].args[0])
        mention = post.call_args_list[1].kwargs["json"][0]
        self.assertEqual((mention["post_id"], mention["restaurant_id"], mention["match_status"]), (51, 1, "matched"))

    def identity_output(self, row, matches, accounts=()):
        out = io.StringIO()
        with patch.object(sys, "argv", ["kol_identity.py"]), patch.object(self.C, "fetch_all", return_value=[row]):
            with patch.object(self.kol_identity, "bili_user_search", return_value=(matches, None)):
                with patch.object(self.kol_identity, "sogou_accounts_for", return_value=(set(accounts), len(accounts), None)):
                    with patch.object(self.kol_identity.time, "sleep"), patch.object(self.kol_identity, "patch_handles", side_effect=AssertionError("write forbidden")):
                        with contextlib.redirect_stdout(out):
                            self.kol_identity.main()
        return out.getvalue()

    def test_identity_accepts_unique_agreeing_mid_in_dry_run(self):
        output = self.identity_output({"id": 1, "name": "甲作者", "platform": "bilibili", "mid": 42},
                                      [{"uname": "甲作者", "mid": "42"}])
        self.assertIn('"mid": "42"', output)
        self.assertIn("将写 handles 的 KOL 数: 1", output)

    def test_identity_rejects_conflicting_or_multiple_same_name_results(self):
        row = {"id": 1, "name": "甲作者", "platform": "cross", "mid": 42}
        self.assertIn("将写 handles 的 KOL 数: 0", self.identity_output(row, [{"uname": "甲作者", "mid": "99"}], ["无关发布者"]))
        row.pop("mid")
        self.assertIn("将写 handles 的 KOL 数: 0", self.identity_output(row, [{"uname": "甲作者", "mid": "42"}, {"uname": "甲作者", "mid": "99"}]))

    def test_router_brand_guard_and_optional_map_boundary(self):
        self.assertEqual(self.kol_router.is_clean_brand("Madre(番禺路店)"), ("madre", "ok"))
        self.assertIsNone(self.kol_router.is_clean_brand("正大广场店")[0])
        with patch.object(self.kol_router, "M", None):
            self.assertEqual(self.kol_router.verify_poi("madre", {"verified": {}}), (None, "no_map_module"))

    def test_trust_pool_exact_mapping_without_write(self):
        with tempfile.TemporaryDirectory() as temp:
            pool = Path(temp) / "pool.json"
            pool.write_text(json.dumps({"pool": [{"name": "甲作者", "tier": "A"}]}), encoding="utf-8")
            out = io.StringIO()
            with patch.object(sys, "argv", ["kol_trust_grade.py"]), patch.object(self.kol_trust_grade, "pool_paths", return_value=pool):
                with patch.object(self.C, "fetch_all", return_value=[{"id": 1, "name": "甲作者", "trust": "low"}]):
                    with patch.object(self.C, "req", side_effect=AssertionError("write forbidden")), contextlib.redirect_stdout(out):
                        self.kol_trust_grade.main()
            self.assertIn("待标 trust 1", out.getvalue())
            self.assertIn("high  甲作者", out.getvalue())

    def test_context_plan_skips_filled_and_unlocatable_mentions(self):
        data = {"food_kol_posts": [{"id": 1, "title": "幸福饭店", "summary": "合成原文"}],
                "food_kol_mentions": [
                    {"id": 1, "post_id": 1, "mentioned_raw": "幸福饭店"},
                    {"id": 2, "post_id": 1, "mentioned_raw": "幸福饭店", "context": "已有"},
                    {"id": 3, "post_id": 1, "mentioned_raw": "如意饭店"},
                    {"id": 4, "post_id": 9, "mentioned_raw": "幸福饭店"}]}
        output = io.StringIO()
        with patch.object(sys, "argv", ["kol_context_backfill.py"]):
            with patch.object(self.C, "fetch_all", side_effect=lambda table, *args, **kwargs: data[table]):
                with patch.object(self.C, "req", side_effect=AssertionError("write forbidden")), contextlib.redirect_stdout(output):
                    self.kol_context_backfill.main()
        self.assertIn("已有context=1 可推导=1 无可推导留空=2", output.getvalue())

    def test_tracking_aggregate_and_timezone_boundary(self):
        data = {"crowd_participants": [{"participant_id": "p1"}, {"participant_id": "p2", "status": "suspended"}],
                "crowd_tasks": [{"status": "open", "kpi_min": 10, "progress": 3, "pack_type": "store"}],
                "crowd_proofs": [{"participant_id": "p1", "gate_status": "accepted", "kind": "rating", "created_at": "2026-11-18T00:00:00Z"},
                                 {"participant_id": "p2", "gate_status": "rejected"},
                                 {"participant_id": "p1", "gate_status": "duplicate_skipped"}]}
        now = self.tracking._ts("2026-11-18T08:00:00+08:00")
        self.assertEqual(now, self.tracking._ts("2026-11-18T00:00:00Z"))
        with patch.object(self.tracking.core, "fetch_all", side_effect=lambda table, *args, **kw: data[table]), patch.object(self.tracking.time, "time", return_value=now):
            report = self.tracking._agg()
        self.assertEqual(report["tasks"]["open_gap"], 7)
        self.assertEqual((report["flow"]["accepted"], report["flow"]["day_accepted"], report["participants"]["active"]), (1, 1, 1))
        self.assertIn("距全部达标还差 7 条", self.tracking.render(report))


if __name__ == "__main__":
    unittest.main()
