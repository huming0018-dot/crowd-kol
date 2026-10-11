import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fetch_model
from local_asr import verify_model
from asr_quality import character_error_rate, simplify_macos


class ModelsTests(unittest.TestCase):
    def test_fixed_revision_and_weight_pin(self):
        model = fetch_model.MODELS['small']
        manifest = {**model, 'license': 'MIT', 'sha256': {'model.bin': model['model_sha256']}}
        self.assertEqual(fetch_model.model_profile(manifest)[0], 'small')
        for change in ({'revision': 'main'}, {'license': 'unknown'}, {'sha256': []}, {'sha256': {'model.bin': '0' * 64}}):
            with self.assertRaises(ValueError):
                fetch_model.model_profile({**manifest, **change})

    def test_redirects_are_https_official_without_userinfo(self):
        for url in ('https://huggingface.co/a', 'https://cas-bridge.xethub.hf.co/a'):
            fetch_model.trusted_url(url)
        for url in ('http://huggingface.co/a', 'https://evil-hf.co/a', 'https://huggingface.co.evil/a',
                    'https://name@huggingface.co/a', 'https://huggingface.co:444/a'):
            with self.assertRaises(ValueError):
                fetch_model.trusted_url(url)

    def test_verified_legacy_layout_and_hash_tampering(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            names = ('model.bin', 'config.json', 'tokenizer.json', 'vocabulary.txt')
            hashes = {}
            for name in names:
                (directory / name).write_bytes(b'weight')
                hashes[name] = hashlib.sha256(b'weight').hexdigest()
            profile = {**fetch_model.MODELS['tiny'], 'model_sha256': hashes['model.bin']}
            manifest = {'repository': profile['repository'], 'revision': profile['revision'],
                        'license': 'MIT', 'sha256': hashes}
            (directory / 'crowd-model.json').write_text(json.dumps(manifest))
            with patch.dict(fetch_model.MODELS, tiny=profile):
                self.assertEqual(verify_model(directory)[1], 'tiny')
                (directory / 'config.json').write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, 'hash_mismatch'):
                    verify_model(directory)

    def test_failed_download_does_not_publish_or_overwrite(self):
        class Opener:
            def open(self, *_args, **_kwargs):
                return io.BytesIO(b'bad weights')
        with tempfile.TemporaryDirectory() as root, patch('fetch_model.urllib.request.build_opener', return_value=Opener()):
            destination = Path(root) / 'new'
            with self.assertRaisesRegex(ValueError, 'weight_hash_mismatch'):
                fetch_model.fetch(destination, 'small')
            self.assertFalse(destination.exists())
            destination.mkdir()
            (destination / 'keep').write_text('original')
            with self.assertRaisesRegex(ValueError, 'already_exists'):
                fetch_model.fetch(destination)
            self.assertEqual((destination / 'keep').read_text(), 'original')

    def test_download_limit_is_enforced_before_publish(self):
        class Opener:
            def open(self, *_args, **_kwargs):
                return io.BytesIO(b'123456')
        with tempfile.TemporaryDirectory() as root, patch('fetch_model.urllib.request.build_opener', return_value=Opener()):
            with patch.dict(fetch_model.MODELS, small={**fetch_model.MODELS['small'], 'limit': 5}):
                with self.assertRaisesRegex(ValueError, 'download_limit'):
                    fetch_model.fetch(Path(root) / 'new', 'small')
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_character_error_rate_does_not_correct_words(self):
        self.assertEqual(character_error_rate('你好，世界！', '你好世界')['cer'], 0)
        self.assertEqual(character_error_rate('你好世界', '你好时间')['edit_distance'], 2)
        self.assertEqual(character_error_rate('甲乙', '甲乙丙')['cer'], .5)
        self.assertEqual(character_error_rate('甲乙', '甲')['cer'], .5)
        with self.assertRaisesRegex(ValueError, 'reference_empty'):
            character_error_rate('， ', '文字')
        with self.assertRaisesRegex(ValueError, 'comparison_too_large'):
            character_error_rate('字' * 5001, '字' * 5001)

    def test_macos_script_normalization_is_explicit(self):
        import sys
        if sys.platform != 'darwin':
            self.skipTest('macOS ICU unavailable')
        self.assertEqual(simplify_macos('這是測試中文轉換'), '这是测试中文转换')
        self.assertEqual(character_error_rate('测试', '測試', True)['cer'], 0)
        self.assertGreater(character_error_rate('测试', '測試')['cer'], 0)


if __name__ == '__main__':
    unittest.main()
