"""New jobs retain chunks/checkpoints, never a second whole PCM copy."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import long_media as lm
from test_long_media import audio


class IntermediatePCMTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'own.wav'
        audio(self.source, seconds=70)
        self.work = self.root / 'work'

    def tearDown(self):
        self.temp.cleanup()

    def assert_no_intermediates(self):
        self.assertEqual(sorted(p.name for p in self.work.glob('*.wav')),
                         ['chunk-0000.wav', 'chunk-0001.wav'])

    def test_new_job_keeps_only_chunk_pcm_and_durable_manifest(self):
        source_hash = lm.digest(self.source)
        manifest = lm.prepare_chunks(self.source, self.work)
        self.assert_no_intermediates()
        self.assertEqual(lm.digest(self.source), source_hash)
        self.assertTrue((self.work / 'chunks.json').is_file())
        self.assertEqual(sum(p.stat().st_size for p in self.work.glob('*.wav')), 72 * 32000 + 88)
        self.assertEqual([row['sha256'] for row in manifest['chunks']],
                         [lm.digest(self.work / row['file']) for row in manifest['chunks']])

    def test_old_whole_pcm_never_modified_even_without_checkpoint(self):
        self.work.mkdir()
        old = self.work / 'audio.wav'
        old.write_bytes(b'historical whole PCM evidence')
        before = (lm.digest(old), old.stat().st_mtime_ns, old.stat().st_ino)
        lm.prepare_chunks(self.source, self.work)
        self.assertEqual((lm.digest(old), old.stat().st_mtime_ns, old.stat().st_ino), before)
        files = {p.name: (lm.digest(p), p.stat().st_mtime_ns) for p in self.work.iterdir()}
        with patch.object(lm, 'exclusive_audio_file', side_effect=AssertionError('must resume without new PCM')):
            lm.prepare_chunks(self.source, self.work)
        self.assertEqual({p.name: (lm.digest(p), p.stat().st_mtime_ns) for p in self.work.iterdir()}, files)

    def test_manifest_failure_cleans_only_new_intermediate(self):
        self.work.mkdir()
        old = self.work / 'audio.wav'
        old.write_bytes(b'old evidence')
        with patch.object(lm, 'save', side_effect=OSError('simulated manifest write failure')):
            with self.assertRaises(OSError):
                lm.prepare_chunks(self.source, self.work)
        self.assertEqual(old.read_bytes(), b'old evidence')
        self.assertFalse((self.work / 'chunks.json').exists())
        self.assertEqual(sorted(p.name for p in self.work.glob('*.wav')),
                         ['audio.wav', 'chunk-0000.wav', 'chunk-0001.wav'])

    def test_cancel_cleans_generated_intermediate_without_touching_source(self):
        before = lm.digest(self.source)
        checks = 0

        def cancel():
            nonlocal checks
            checks += 1
            return checks >= 3

        with self.assertRaisesRegex(ValueError, 'long_media_cancelled'):
            lm.prepare_chunks(self.source, self.work, cancel)
        self.assertEqual(lm.digest(self.source), before)
        self.assertFalse((self.work / 'chunks.json').exists())
        self.assertTrue(all(p.name.startswith('chunk-') for p in self.work.glob('*.wav')))

    @unittest.skipUnless(lm.ffmpeg_path(), 'local ffmpeg required')
    def test_compressed_input_also_does_not_retain_whole_pcm(self):
        encoded = self.root / 'own.m4a'
        subprocess.run([lm.ffmpeg_path(), '-nostdin', '-loglevel', 'error',
                        '-i', str(self.source), '-c:a', 'aac', str(encoded)],
                       check=True, timeout=30)
        before = lm.digest(encoded)
        lm.prepare_chunks(encoded, self.work)
        self.assert_no_intermediates()
        self.assertEqual(lm.digest(encoded), before)


if __name__ == '__main__':
    unittest.main()
