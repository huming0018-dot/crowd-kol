import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import audio_result_cache as cache


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / 'cache'
        self.key = 'a' * 64
        self.value = {'input_hash': self.key, 'segments': [],
                      'timing_adjustments': [], 'segment_metrics': []}

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def validator(value):
        if not isinstance(value['segments'], list):
            raise ValueError('invalid_segments')

    def test_reuse_exact_and_conflicting_results(self):
        with cache.AudioResultCache(self.root, self.path) as store:
            self.assertIsNone(store.get(self.key, self.validator))
            self.assertTrue(store.put(self.key, self.value, self.validator))
            self.assertEqual(store.get(self.key, self.validator), self.value)
            self.assertFalse(store.put(self.key, self.value, self.validator))
            with self.assertRaisesRegex(ValueError, 'conflict'):
                store.put(self.key, {**self.value, 'segments': ['changed']}, self.validator)
            self.assertEqual((self.path / (self.key + '.json')).stat().st_mode & 0o777, 0o600)

    def test_validation_and_identity_fail_closed(self):
        with cache.AudioResultCache(self.root, self.path) as store:
            for value in ({**self.value, 'input_hash': 'b' * 64},
                          {**self.value, 'owner': 'wrong'},
                          {**self.value, 'segments': 'wrong'}):
                with self.assertRaises(ValueError):
                    store.put(self.key, value, self.validator)
            store.put(self.key, self.value, self.validator)
            target = self.path / (self.key + '.json')
            target.write_text('{broken')
            with self.assertRaisesRegex(ValueError, 'corrupt'):
                store.get(self.key, self.validator)
            with self.assertRaisesRegex(ValueError, 'corrupt'):
                store.put(self.key, self.value, self.validator)
            self.assertEqual(target.read_text(), '{broken')
            target.write_text('null')
            with self.assertRaisesRegex(ValueError, 'corrupt'):
                store.get(self.key, self.validator)
            with self.assertRaisesRegex(ValueError, 'corrupt'):
                store.put(self.key, self.value, self.validator)
            self.assertEqual(target.read_text(), 'null')

    def test_symlinks_hardlinks_permissions_and_project_boundary(self):
        with self.assertRaises(ValueError):
            cache.AudioResultCache(self.root, self.root.parent / 'outside')
        self.path.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            cache.AudioResultCache(self.root, self.path)
        self.path.unlink()
        ancestor = self.root / 'writable'
        ancestor.mkdir(mode=0o777); ancestor.chmod(0o777)
        with self.assertRaisesRegex(ValueError, 'unsafe.*ancestor'):
            cache.AudioResultCache(self.root, ancestor / 'cache')
        with cache.AudioResultCache(self.root, self.path) as store:
            target = self.path / (self.key + '.json')
            original = self.root / 'original'
            original.write_text(json.dumps(self.value)); original.chmod(0o600)
            target.symlink_to(original)
            with self.assertRaises(OSError):
                store.get(self.key, self.validator)
            target.unlink(); os.link(original, target)
            with self.assertRaisesRegex(ValueError, 'unsafe'):
                store.get(self.key, self.validator)
            target.unlink()
            store.put(self.key, self.value, self.validator)
            target.chmod(0o644)
            with self.assertRaisesRegex(ValueError, 'unsafe'):
                store.get(self.key, self.validator)

    def test_bounds_never_evict_existing_results(self):
        with cache.AudioResultCache(self.root, self.path) as store:
            store.put(self.key, self.value, self.validator)
            with patch.object(cache, 'MAX_ENTRIES', 1):
                other = 'b' * 64
                self.assertFalse(store.put(other, {**self.value, 'input_hash': other}, self.validator))
            self.assertEqual(store.get(self.key, self.validator), self.value)
            with patch.object(cache, 'MAX_ENTRY_BYTES', 1):
                with self.assertRaisesRegex(ValueError, 'over_limit'):
                    store.get(self.key, self.validator)
            self.assertEqual(len(list(self.path.glob('*.json'))), 1)

    def test_fifo_refused_without_blocking(self):
        with cache.AudioResultCache(self.root, self.path) as store:
            os.mkfifo(self.path / (self.key + '.json'), 0o600)
            with self.assertRaisesRegex(ValueError, 'unsafe'):
                store.get(self.key, self.validator)
            other = 'b' * 64
            with self.assertRaisesRegex(ValueError, 'unsafe'):
                store.put(other, {**self.value, 'input_hash': other}, self.validator)


if __name__ == '__main__':
    unittest.main()
