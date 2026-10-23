import copy
import types
import unittest

from bili_media_selection import install_low_audio_selection


class AudioSelection(unittest.TestCase):
    def setUp(self):
        self.calls = []
        def native(info):
            self.calls.append(info)
            return {"id": 30280, "bandwidth": 200000, "baseUrl": "https://native.example/high?secret=value"}
        self.native = native
        self.module = types.SimpleNamespace(pick_audio_stream=native)
        self.phase = []

    def test_lowest_real_stream_by_bandwidth_then_id_and_no_mutation(self):
        rows = [
            {"id": "30280", "bandwidth": "200000", "baseUrl": "https://native.example/high?secret=value"},
            {"id": 30232, "bandwidth": 64000, "base_url": "https://native.example/low", "backupUrl": ["https://native.example/backup"]},
            {"id": 30216, "bandwidth": 64000, "baseUrl": "https://native.example/lowest"},
        ]
        info = {"dash": {"audio": rows}}
        before = copy.deepcopy(info)
        self.assertTrue(install_low_audio_selection(self.module, 16, self.phase.append))
        chosen = self.module.pick_audio_stream(info)
        self.assertIs(chosen, rows[2])
        self.assertEqual(info, before)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.phase, [{"selection": "lowest_positive_bandwidth_native_audio", "native_stream_id": 30216, "bandwidth": 64000, "eligible_audio_streams": 3}])
        self.assertNotIn("secret", repr(self.phase))
        self.assertNotIn("http", repr(self.phase))

    def test_other_quality_and_wrong_scalar_types_use_original(self):
        for quality in (80, 32, 16.0, True, "16", None):
            self.assertFalse(install_low_audio_selection(self.module, quality, self.phase.append))
            self.assertIs(self.module.pick_audio_stream, self.native)
        self.assertEqual(self.calls, [])

    def test_invalid_positive_fields_do_not_defeat_valid_choice(self):
        bad = [True, False, 0, -1, 1.0, float("inf"), float("nan"), "-1", "1.0", "", "１", "9" * 1000, 2**63]
        rows = [{"id": 30216, "bandwidth": x, "baseUrl": "https://native.example/bad"} for x in bad]
        rows += [{"id": x, "bandwidth": 1, "baseUrl": "https://native.example/bad"} for x in bad]
        rows += [{"id": 30216, "bandwidth": 1, "baseUrl": None}, {"id": 30216, "bandwidth": 1, "baseUrl": 1}]
        valid = {"id": 30232, "bandwidth": 64000, "baseUrl": "https://native.example/good"}
        rows.append(valid)
        install_low_audio_selection(self.module, 16)
        self.assertIs(self.module.pick_audio_stream({"dash": {"audio": rows}}), valid)
        self.assertEqual(self.calls, [])

    def test_missing_shape_or_no_bounded_candidate_calls_native_once(self):
        install_low_audio_selection(self.module, 16, self.phase.append)
        for info in (None, {}, {"dash": []}, {"dash": {"audio": {}}}, {"dash": {"audio": [{"id": 1, "baseUrl": "https://native.example/no-bandwidth"}]}}):
            before = len(self.calls)
            self.module.pick_audio_stream(info)
            self.assertEqual(len(self.calls), before + 1)
            self.assertEqual(self.phase[-1]["selection"], "native_default_no_bounded_candidate")
            self.assertEqual(self.phase[-1]["eligible_audio_streams"], 0)

    def test_install_idempotent_and_other_quality_restores_native(self):
        install_low_audio_selection(self.module, 16)
        install_low_audio_selection(self.module, 16)
        self.module.pick_audio_stream({})
        self.assertEqual(len(self.calls), 1)
        install_low_audio_selection(self.module, 80)
        self.assertIs(self.module.pick_audio_stream, self.native)

    def test_budget_and_control_exit_from_native_not_swallowed(self):
        for code in (73, 76, 77):
            def original(info):
                raise SystemExit(code)
            self.module.pick_audio_stream = original
            install_low_audio_selection(self.module, 16)
            with self.assertRaises(SystemExit) as raised:
                self.module.pick_audio_stream({})
            self.assertEqual(raised.exception.code, code)


if __name__ == "__main__":
    unittest.main()
