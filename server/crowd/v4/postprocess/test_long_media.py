"""Real local >60s PCM/ffmpeg fixtures and offline ASR checkpoint contracts."""
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import wave

import long_media as lm


def audio(path, seconds=70, rate=16000, channels=1):
    with wave.open(str(path), 'wb') as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(rate)
        tone = b''.join(struct.pack('<h', int(5000 * math.sin(2 * math.pi * 440 * i / rate))) * channels
                        for i in range(rate))
        for _ in range(seconds):
            output.writeframesraw(tone)


class LongMediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'own.wav'
        audio(self.source)
        self.work = self.root / 'work'

    def tearDown(self):
        self.temp.cleanup()

    def test_real_70_second_split_pcm_hashes_and_repeatable_cache(self):
        before = lm.digest(self.source)
        manifest = lm.prepare_chunks(self.source, self.work)
        self.assertEqual(manifest['duration_seconds'], 70)
        self.assertEqual([(x['start'], x['end']) for x in manifest['chunks']], [(0, 55), (53, 70)])
        for row in manifest['chunks']:
            with wave.open(str(self.work / row['file']), 'rb') as handle:
                self.assertEqual(handle.getnframes() / handle.getframerate(), row['end'] - row['start'])
            self.assertEqual(lm.digest(self.work / row['file']), row['sha256'])
        with patch.object(lm.shutil, 'copyfile', side_effect=AssertionError('must reuse verified chunks')):
            self.assertEqual(lm.prepare_chunks(self.source, self.work), manifest)
        self.assertEqual(lm.digest(self.source), before)

    @unittest.skipUnless(lm.ffmpeg_path(), 'local ffmpeg required')
    def test_long_audio_over_hour_is_bounded_and_video_keeps_old_limit(self):
        source = self.root / 'long.m4a'
        subprocess.run([lm.ffmpeg_path(), '-nostdin','-loglevel','error', '-f','lavfi',
                        '-i','anullsrc=r=16000:cl=mono','-t','3601','-c:a','aac',str(source)],
                       check=True,timeout=60)
        manifest = lm.prepare_chunks(source, self.work)
        self.assertGreater(manifest['duration_seconds'],3600)
        self.assertLess(manifest['duration_seconds'],3602)
        self.assertEqual(manifest['chunks'][-1]['end'],manifest['duration_seconds'])
        self.assertEqual(lm.prepare_chunks(source,self.work),manifest)
        other = self.root / 'video.mp4'
        shutil.copyfile(source,other)
        with self.assertRaisesRegex(ValueError,'audio_empty_or_over_duration_limit'):
            lm.prepare_chunks(other,self.root/'video-work')

    def test_long_audio_single_file_limit_does_not_expand_video_limit(self):
        for suffix,maximum in (('.m4a',lm.LONG_AUDIO_BYTES),('.mp4',lm.MAX_BYTES)):
            source = self.root / ('oversized'+suffix)
            with source.open('wb') as stream:
                stream.truncate(maximum+1)
            with self.assertRaisesRegex(ValueError,'media_missing_or_over_processing_limit'):
                lm.prepare_chunks(source,self.root/('work'+suffix))

    def test_absolute_timeline_overlap_only_dedup_and_stable_merge(self):
        manifest = lm.prepare_chunks(self.source, self.work)
        rows = [
            {'segments': [{'start': 0, 'end': 1, 'text': '开头'}, {'start': 53, 'end': 55, 'text': '重复句。'}]},
            {'segments': [{'start': 0, 'end': 2, 'text': '重复句'}, {'start': 3, 'end': 4, 'text': '重复句'},
                          {'start': 5, 'end': 7, 'text': '结尾'}]}]
        merged = lm.merge_chunks(manifest, rows)
        self.assertEqual(merged['deduplicated_overlap_segments'], 1)
        self.assertEqual([(x['start'], x['end']) for x in merged['segments']], [(0, 1), (53, 55), (56, 57), (58, 60)])
        self.assertEqual(lm.merge_chunks(manifest, rows), merged)
        self.assertEqual(merged['timeline'], 'absolute_seconds')

    def test_overlap_partial_prefix_keeps_original_decision_and_normal_repetition(self):
        manifest = lm.prepare_chunks(self.source, self.work)
        partial = {'start': 53.26, 'end': 54.96, 'text': '最後，我們用真實……'}
        full = {'start': 0, 'end': 10, 'text': '最後，我們用真實耗時比較兩個模型。'}
        repeated = {'start': 12, 'end': 14, 'text': partial['text']}
        result = lm.merge_chunks(manifest, [{'segments': [partial]}, {'segments': [full, repeated]}])
        self.assertEqual(len(result['segments']), 2)
        self.assertEqual(result['segments'][0]['text'], full['text'])
        decision = result['overlap_decisions'][0]
        self.assertEqual(decision['match'], 'prefix')
        self.assertEqual(decision['removed_segment']['text'], partial['text'])
        self.assertEqual(decision['removed_segment']['start'], 53.26)
        self.assertEqual(partial['text'], '最後，我們用真實……')

    def test_suffix_fragment_and_false_positive_boundaries(self):
        manifest = lm.prepare_chunks(self.source, self.work)
        full = {'start': 50, 'end': 55, 'text': '我们保留正文和评论以及媒体文件'}
        suffix = {'start': .2, 'end': 1.5, 'text': '评论以及媒体文件'}
        result = lm.merge_chunks(manifest, [{'segments': [full]}, {'segments': [suffix]}])
        self.assertEqual(len(result['segments']), 1)
        self.assertEqual(result['overlap_decisions'][0]['match'], 'suffix')
        for bad in ({**suffix, 'start': 3., 'end': 4.},
                    {**suffix, 'text': '媒体文件'},
                    {**suffix, 'text': '评论以及媒体完全不同'},
                    {**suffix, 'end': 3.}):
            with self.subTest(bad=bad):
                retained = lm.merge_chunks(manifest, [{'segments': [full]}, {'segments': [bad]}])
                self.assertEqual(len(retained['segments']), 2)
                self.assertEqual(retained['overlap_decisions'], [])

    def test_adjacent_same_text_without_time_overlap_is_not_removed(self):
        manifest = lm.prepare_chunks(self.source, self.work)
        result = lm.merge_chunks(manifest, [
            {'segments': [{'start': 52, 'end': 53, 'text': '我们现在开始采集'}]},
            {'segments': [{'start': 0, 'end': 1, 'text': '我们现在开始采集'}]}])
        self.assertEqual(len(result['segments']), 2)
        self.assertEqual(result['overlap_decisions'], [])

    def test_cancel_checkpoint_resume_and_cached_chunks_no_retranscription(self):
        cancelled = False
        calls = []

        def partial(path):
            nonlocal cancelled
            calls.append(path.name)
            cancelled = True
            return {'segments': [{'start': 0, 'end': 1, 'text': '第一段'}], 'truncated': False}

        with self.assertRaisesRegex(ValueError, 'long_media_cancelled'):
            lm.transcribe_long(self.source, None, self.work, cancel=lambda: cancelled, transcriber=partial)
        state = json.loads((self.work / 'state.json').read_text())
        self.assertEqual((state['state'], state['completed_chunks']), ('cancelled', 1))
        self.assertTrue((self.work / 'result-0000.json').is_file())

        def finish(path):
            calls.append(path.name)
            return {'segments': [{'start': 0, 'end': 1, 'text': '后续'}], 'truncated': False}

        result = lm.transcribe_long(self.source, None, self.work, transcriber=finish)
        self.assertEqual(calls, ['chunk-0000.wav', 'chunk-0001.wav'])
        self.assertEqual(result['segments'][1]['start'], 53)
        with patch.object(lm, 'validate_segments', wraps=lm.validate_segments):
            again = lm.transcribe_long(self.source, None, self.work,
                                       transcriber=lambda _: self.fail('completed chunks must be cached'))
        self.assertEqual(again, result)

    def test_failure_preserves_first_chunk_and_rejects_corrupt_cache(self):
        calls = 0

        def fail_second(_):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ValueError('test_provider_failed')
            return {'segments': [{'start': 0, 'end': 1, 'text': '保留'}], 'truncated': False}

        with self.assertRaisesRegex(ValueError, 'test_provider_failed'):
            lm.transcribe_long(self.source, None, self.work, transcriber=fail_second)
        self.assertTrue((self.work / 'result-0000.json').is_file())
        self.assertEqual(json.loads((self.work / 'state.json').read_text())['completed_chunks'], 1)
        (self.work / 'chunk-0000.wav').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'checkpoint_audio_corrupt'):
            lm.prepare_chunks(self.source, self.work)

    def test_silent_window_is_retained_as_no_text_without_losing_spoken_window(self):
        calls = 0

        def provider(_):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ValueError('speech_empty')
            return {'segments': [{'start': 0, 'end': 1, 'text': '有声段'}], 'truncated': False}

        result = lm.transcribe_long(self.source, None, self.work, transcriber=provider)
        self.assertEqual(result['audio_windows_processed'], 2)
        self.assertEqual(result['no_text_windows'], 1)
        self.assertEqual(len(result['segments']), 1)
        with self.assertRaisesRegex(ValueError, 'incomplete_asr_chunk_results'):
            lm.merge_chunks(lm.prepare_chunks(self.source, self.work), [])

    def test_missing_model_explicit_state_no_download_and_invalid_time(self):
        with self.assertRaisesRegex(ValueError, 'local_asr_model_not_configured'):
            lm.transcribe_long(self.source, None, self.work)
        self.assertEqual(json.loads((self.work / 'state.json').read_text())['state'], 'model_unavailable')
        for rows in ([{'start': float('nan'), 'end': 1, 'text': 'x'}],
                     [{'start': 55.05, 'end': 55.08, 'text': 'tail'}],
                     [{'start': 0, 'end': 100, 'text': 'x'}],
                     [{'start': 0, 'end': 1, 'text': '', 'source': 'bad'}]):
            with self.assertRaises(ValueError):
                lm.validate_segments(rows, 55)

    def test_write_paths_reject_symlinks_without_modifying_original_or_outside(self):
        outside = self.root / 'outside'
        outside.mkdir()
        victim = outside / 'original.wav'
        victim.write_bytes(b'preserve-original')
        for name in ('audio.wav', 'audio.partial.wav', 'chunk-0000.wav', 'active.lock', 'state.json'):
            with self.subTest(name=name):
                work = self.root / ('guard-' + name)
                work.mkdir()
                (work / name).symlink_to(victim)
                with self.assertRaisesRegex(ValueError, 'unsafe_long_media_work_file'):
                    lm.transcribe_long(self.source, None, work, transcriber=lambda _: None)
                self.assertEqual(victim.read_bytes(), b'preserve-original')
                self.assertEqual(list(outside.iterdir()), [victim])
        direct = self.root / 'linked-work'
        direct.symlink_to(outside, target_is_directory=True)
        nested = direct / 'new-work'
        for work in (direct, nested, self.source.parent):
            with self.assertRaisesRegex(ValueError, 'unsafe_long_media_work_directory'):
                lm.transcribe_long(self.source, None, work, transcriber=lambda _: None)
        self.assertEqual(list(outside.iterdir()), [victim])
        self.assertFalse((self.source.parent / 'active.lock').exists())

    def test_atomic_pcm_output_does_not_modify_preexisting_hardlinked_original(self):
        import os
        self.work.mkdir()
        victim = self.root / 'hardlink-victim'
        victim.write_bytes(b'keep')
        os.link(victim, self.work / 'audio.wav')
        os.link(victim, self.work / 'chunk-0000.wav')
        lm.prepare_chunks(self.source, self.work)
        self.assertEqual(victim.read_bytes(), b'keep')

    def test_long_evidence_processes_hashed_snapshot_when_original_changes(self):
        import evidence
        original = self.source.read_bytes()
        def transcribe(snapshot, _model, _work, cancel=None):
            self.source.write_bytes(b'external-file-changed')
            self.assertNotEqual(Path(snapshot), self.source)
            self.assertEqual(Path(snapshot).stat().st_mode & 0o777, 0o600)
            self.assertEqual(Path(snapshot).read_bytes(), original)
            return {'raw_text': 'frozen snapshot', 'truncated': False, 'segments': []}
        with patch.object(lm, 'transcribe_long', side_effect=transcribe):
            row = evidence.prepare('asr', self.source, 'weibo', '123', 'own-fixture',
                                   asr_model=self.root / 'not-used-model', work_dir=self.work)
        self.assertEqual(row['evidence']['asset_sha256'], hashlib.sha256(original).hexdigest())

    def test_full_ffmpeg_extracts_video_audio_over_60_seconds(self):
        executable = lm.ffmpeg_path()
        if executable is None:
            self.skipTest('explicit full audio-capable ffmpeg unavailable')
        video = self.root / 'own-70s.mp4'
        subprocess.run([executable, '-nostdin', '-loglevel', 'error', '-y',
                        '-f', 'lavfi', '-i', 'color=c=black:s=32x32:r=1', '-i', str(self.source),
                        '-t', '70', '-c:v', 'libx264', '-c:a', 'aac', '-shortest', str(video)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        self.assertLess(video.stat().st_size, lm.MAX_BYTES)
        before = lm.digest(video)
        manifest = lm.prepare_chunks(video, self.work)
        self.assertGreater(manifest['duration_seconds'], 60)
        self.assertEqual(len(manifest['chunks']), 2)
        self.assertEqual(lm.digest(video), before)
        results = [{'segments': [{'start': 0, 'end': 1, 'text': '合成验证'}]} for _ in manifest['chunks']]
        self.assertEqual(lm.merge_chunks(manifest, results), lm.merge_chunks(manifest, results))


if __name__ == '__main__':
    unittest.main()
