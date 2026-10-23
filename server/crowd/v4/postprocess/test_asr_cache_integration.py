"""Project reuse must preserve each job's checkpoints and reject invalid evidence."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import local_asr
import long_media
import wave


class CacheIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'own.wav'
        with wave.open(str(self.source), 'wb') as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            output.writeframes(b'\0\0' * 16000 * 70)
        self.model = self.root / 'model'
        self.model.mkdir()
        (self.model / 'crowd-model.json').write_text('{}')
        self.cache = self.root / 'cache'

    def tearDown(self):
        self.temp.cleanup()

    def run_job(self, name, **options):
        return long_media.transcribe_long(self.source, self.model, self.root / name,
                                         project_root=self.root, cache_dir=self.cache, **options)

    def test_cross_job_reuse_no_model_load_and_fresh_job_checkpoints(self):
        with patch.object(local_asr, 'transcribe', return_value={'segments': [{'start': 0., 'end': 1., 'text': '原文'}]}) as decode:
            first = self.run_job('first')
            self.assertEqual(decode.call_count, 2)
            decode.reset_mock()
            self.assertEqual(self.run_job('second'), first)
            decode.assert_not_called()
            entries = list(self.cache.glob('*.json'))
            self.assertEqual(len(entries), 2)
            for entry in entries:
                value = json.loads(entry.read_text())
                self.assertEqual(set(value), {'input_hash', 'segments', 'segment_metrics',
                                             'timing_adjustments', 'native_alignment'})
                checkpoints = [json.loads(path.read_text()) for path in (self.root / 'second').glob('result-*.json')]
                self.assertIn(value, checkpoints)
            self.assertEqual(json.loads((self.root / 'second/state.json').read_text())['state'], 'completed')

    def test_injected_provider_cannot_publish_project_cache(self):
        with self.assertRaisesRegex(ValueError, 'audio_result_cache_requires_local_provider'):
            self.run_job('injected', transcriber=lambda _: {})
        self.assertFalse(self.cache.exists())

    def test_local_null_is_rejected_without_overwrite_or_provider(self):
        work = self.root / 'corrupt'
        long_media.prepare_chunks(self.source, work)
        target = work / 'result-0000.json'
        target.write_text('null')
        with patch.object(local_asr, 'verify_model', side_effect=AssertionError('must not load')):
            with self.assertRaisesRegex(ValueError, 'long_media_chunk_cache_identity_mismatch'):
                self.run_job('corrupt')
        self.assertEqual(target.read_text(), 'null')
        self.assertEqual(json.loads((work / 'state.json').read_text())['state'], 'failed')

    def test_cache_rejects_wrong_duration_metrics_and_identity(self):
        with patch.object(local_asr, 'transcribe', return_value={'segments': [{'start': 0., 'end': 1., 'text': '原文'}]}):
            self.run_job('seed')
        target = next(self.cache.glob('*.json'))
        original = json.loads(target.read_text())
        mutations = [({'input_hash': '0' * 64}, 'audio_result_cache_identity_mismatch'),
                     ({'segments': [{'start': 0., 'end': 999., 'text': 'bad'}]}, 'invalid_asr_segment'),
                     ({'segment_metrics': []}, 'invalid_asr_segment_metrics')]
        for index, (changes, reason) in enumerate(mutations):
            with self.subTest(reason=reason):
                target.write_text(json.dumps({**original, **changes}))
                with patch.object(local_asr, 'verify_model', side_effect=AssertionError('must fail before model load')):
                    with self.assertRaisesRegex(ValueError, reason):
                        self.run_job('invalid-%s' % index)
                target.write_text(json.dumps(original))


if __name__ == '__main__':
    unittest.main()
