import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import evidence
import pipeline
import local_asr


class PipelineTests(unittest.TestCase):
    def job(self):
        return {'schema_version': 1, 'platform': 'bilibili', 'content_id': 'BV1xx411c7mD',
                'authorization_ref': 'self-owned', 'assets': [
                    {'url': 'https://i0.hdslb.com/a.png', 'kind': 'image'},
                    {'url': 'https://i0.hdslb.com/b.png', 'kind': 'image'}]}

    def test_partial_preserves_first_receipt_and_no_source_url(self):
        def download(url, folder):
            if url.endswith('b.png'):
                raise ValueError('asset_http_403')
            (folder / 'asset.png').write_bytes(b'image')
            return {'file': 'asset.png', 'bytes': 5, 'asset_sha256': hashlib.sha256(b'image').hexdigest(), 'content_type': 'image/png'}
        derived = {'evidence': {'raw_text': '原文'}, 'kind': 'ocr'}
        with tempfile.TemporaryDirectory() as d, patch.object(pipeline.media, 'validate_url'), patch.object(pipeline.media, 'download', download), patch.object(pipeline.evidence, 'prepare', return_value=derived):
            result = pipeline.run(self.job(), Path(d) / 'job', ocr=True)
            self.assertEqual([x['status'] for x in result['assets']], ['processed', 'failed'])
            self.assertEqual(json.loads((Path(d) / 'job/asset-1/evidence.json').read_text()), [derived])
            self.assertTrue((Path(d) / 'job/receipt-1.json').exists())
            self.assertNotIn('hdslb', json.dumps(result))
            with self.assertRaises(FileExistsError):
                pipeline.run(self.job(), Path(d) / 'job')

    def test_fail_closed_before_download(self):
        with tempfile.TemporaryDirectory() as d, patch.object(pipeline.media, 'validate_url'), patch.object(pipeline.media, 'download') as download:
            for update in [{'authorization_ref': ''}, {'assets': []}, {'schema_version': 2}, {'platform': 'unknown'}]:
                job = self.job(); job.update(update)
                with self.assertRaises(ValueError):
                    pipeline.run(job, Path(d) / 'job')
            with self.assertRaises(ValueError):
                pipeline.run(self.job(), Path(d) / 'job', asr=True)
            download.assert_not_called()
            self.assertFalse((Path(d) / 'job').exists())

    def test_explicit_asr_command_and_bad_output(self):
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / 'own.wav'; source.write_bytes(b'audio')
            def run(command, **kwargs):
                self.assertIn('--model-dir', command)
                self.assertEqual(kwargs['timeout'], 150)
                return subprocess.CompletedProcess(command, 0, stdout=b'{"raw_text":"test","truncated":false}')
            row = evidence.prepare('asr', source, 'bilibili', 'BV1xx411c7mD', 'self-owned', runner=run, asr_model=Path(d))
            self.assertEqual(row['evidence']['processor'], 'faster_whisper_local')
            with self.assertRaises(ValueError):
                evidence.prepare('asr', source, 'bilibili', 'BV1xx411c7mD', 'self-owned', runner=lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=b'{"raw_text":"","truncated":false}'), asr_model=Path(d))

    def test_missing_model_does_not_download(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError, 'verified_local_model_required'):
                local_asr.transcribe(Path(d) / 'audio.wav', Path(d))


if __name__ == '__main__':
    unittest.main()
