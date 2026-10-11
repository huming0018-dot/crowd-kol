import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

import evidence
import local_asr
import long_media


def metric(index=0, **values):
    return {**dict(segment_index=index, avg_logprob=-.2, compression_ratio=1.,
                   no_speech_prob=.1), **values}


class DiagnosticTests(unittest.TestCase):
    def test_adjacent_repeat_is_review_candidate_without_text_or_scores_changed(self):
        rows = [{'start':float(i), 'end':float(i + 1), 'text':text}
                for i, text in enumerate(['老闆娘', '老闆娘！', '老闆娘', '原后文'])]
        before = json.loads(json.dumps(rows))
        metrics = [metric(i) for i in range(len(rows))]
        result = local_asr.quality_diagnostics(rows, metrics)
        self.assertEqual([r['flags'] for r in result['segments']],
                         [['repeated_adjacent_text']] * 3 + [[]])
        self.assertEqual(rows, before)
        self.assertEqual([{k:r[k] for k in ('start','end','text')} for r in result['segments']], before)
        self.assertEqual([{k:r[k] for k in metric()} for r in result['segments']], metrics)
        self.assertEqual(result['review_status'], 'not_reviewed')
        self.assertEqual(local_asr.quality_diagnostics(rows)['segments'], [])

    def test_repeat_rule_does_not_cross_windows_gaps_or_short_repeats(self):
        rows = [{'start':float(i), 'end':float(i + 1), 'text':'谢谢大家'} for i in range(3)]
        self.assertEqual(local_asr.repeated_text_indices(rows[:2]), set())
        self.assertEqual(local_asr.repeated_text_indices([{**r,'text':'啊'} for r in rows]), set())
        self.assertEqual(local_asr.repeated_text_indices([{**r,'chunk_index':i} for i,r in enumerate(rows)]), set())
        self.assertEqual(local_asr.repeated_text_indices([{**r,'start':i*10.,'end':i*10.+1.} for i,r in enumerate(rows)]), set())
        self.assertEqual(local_asr.repeated_text_indices([{**r,'start':i*7.,'end':i*7.+7.} for i,r in enumerate(rows)]), set())
        invalid = [{**rows[0],'start':10**1000}, *rows[1:]]
        self.assertEqual(local_asr.repeated_text_indices(invalid), set())
        # Genuine repetition remains present: a hint does not prove hallucination.
        real = local_asr.quality_diagnostics(rows, [metric(i) for i in range(3)])
        self.assertEqual(len(real['segments']), 3)
        self.assertEqual([r['text'] for r in real['segments']], ['谢谢大家'] * 3)

    def test_finite_metrics_and_combined_silence_hint(self):
        rows = [{'start':0., 'end':1., 'text':'保留原文'}]
        for field, values in [('avg_logprob', [True, '0', float('nan'), float('inf'), 10 ** 1000]),
                              ('compression_ratio', [-1., False, float('inf')]),
                              ('no_speech_prob', [-.1, 1.1, True])]:
            for value in values:
                data = metric(); data[field] = value
                result = local_asr.quality_diagnostics(rows, [data])
                self.assertIsNone(result['segments'][0][field])
                self.assertEqual(result['status'], 'partial')
                json.dumps(result, allow_nan=False)
        high = metric(); high['no_speech_prob'] = .9
        self.assertNotIn('possible_no_speech', local_asr.quality_diagnostics(rows, [high])['segments'][0]['flags'])
        high.update(avg_logprob=-1.1, compression_ratio=2.5)
        self.assertEqual(local_asr.quality_diagnostics(rows, [high])['segments'][0]['flags'],
                         ['low_logprob', 'high_compression', 'possible_no_speech'])
        self.assertEqual(rows[0]['text'], '保留原文')

    def test_missing_legacy_metrics_are_unknown_not_zero(self):
        rows = [{'start':0., 'end':1., 'text':'旧文'}]
        result = local_asr.quality_diagnostics(rows)
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['segments'], [])
        self.assertEqual(result['review_status'], 'not_reviewed')
        for value in [[], [metric(1)], [metric(False)], [dict(metric(), unexpected='secret')]]:
            with self.assertRaisesRegex(ValueError, 'invalid_asr_segment_metrics'):
                local_asr.quality_diagnostics(rows, value)

    def test_real_decode_fake_provider_blank_index_and_tail(self):
        provider = [SimpleNamespace(text=' ', start=0., end=.2),
                    SimpleNamespace(text='原文', start=.3, end=1.2,
                                    avg_logprob=-1.2, compression_ratio=2.6, no_speech_prob=.7)]
        model=SimpleNamespace(feature_extractor=SimpleNamespace(time_per_frame=.01,nb_max_frames=3000))
        model._split_segments_by_timestamps=lambda *a,**k:([
            {'start':p.start,'end':p.end,'tokens':p.text,'seek':0} for p in provider],0,True)
        def transcribe(*args,**kwargs):
            self.assertIs(kwargs['word_timestamps'],True)
            self.assertIs(kwargs['vad_filter'],False)
            model._split_segments_by_timestamps(SimpleNamespace(decode=lambda tokens:tokens))
            return iter(provider),None
        original_split=model._split_segments_by_timestamps
        model.transcribe=transcribe
        module = SimpleNamespace(WhisperModel=lambda *a, **k: model)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'own.wav'
            with wave.open(str(path), 'wb') as stream:
                stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(16000)
                stream.writeframes(b'\x00\x00' * 16000)
            with patch.object(local_asr, 'verify_model', return_value=(Path(directory), 'test',
                              {'repository':'offline-test', 'revision':'test'})), patch.dict(sys.modules, {'faster_whisper':module}):
                result = local_asr.transcribe(path, Path(directory))
        self.assertIs(model._split_segments_by_timestamps,original_split)
        self.assertEqual(result['segments'], [{'start':.3, 'end':1., 'text':'原文'}])
        self.assertEqual(result['segment_metrics'][0]['segment_index'], 0)
        self.assertEqual(result['quality_diagnostics']['segments'][0]['end'], 1.)
        self.assertEqual(result['timing_adjustments'][0]['provider_end'], 1.2)
        self.assertEqual(result['native_alignment']['method'],'faster_whisper_word_timestamps')
        self.assertEqual(result['native_alignment']['token_candidates'][0]['end'],1.2)
        self.assertEqual(result['native_alignment']['aligned_estimates'][0]['end'],1.2)

    def test_provider_failure_restores_observer_without_retaining_model_cycle(self):
        model=SimpleNamespace(feature_extractor=SimpleNamespace(time_per_frame=.01,nb_max_frames=3000))
        original=lambda *a,**k:([],0,True)
        model._split_segments_by_timestamps=original
        def failed(*args,**kwargs):raise RuntimeError('provider_failed')
        model.transcribe=failed
        module=SimpleNamespace(WhisperModel=lambda *a,**k:model)
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'own.wav'
            with wave.open(str(source),'wb') as stream:
                stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(16000)
                stream.writeframes(b'\x00\x00'*16000)
            with patch.object(local_asr,'verify_model',return_value=(Path(directory),'test',{})), \
                    patch.dict(sys.modules,{'faster_whisper':module}):
                with self.assertRaisesRegex(RuntimeError,'provider_failed'):
                    local_asr.transcribe(source,Path(directory))
        self.assertIs(model._split_segments_by_timestamps,original)

    def test_overlap_diagnostics_remain_original_not_final_score(self):
        manifest = {'duration_seconds':60., 'chunks':[
            {'index':0, 'start':0., 'end':55.}, {'index':1, 'start':53., 'end':60.}]}
        first = {'segments':[{'start':53., 'end':55., 'text':'这是一句完整的话'}], 'segment_metrics':[metric()]}
        bad = metric(); bad['avg_logprob'] = -2.
        second = {'segments':[{'start':0., 'end':1., 'text':'这是一句完整的话'}], 'segment_metrics':[bad]}
        result = long_media.merge_chunks(manifest, [first, second])
        self.assertEqual(len(result['segments']), 1)
        self.assertEqual(len(result['quality_diagnostics']['segments']), 2)
        entries = result['quality_diagnostics']['segments']
        self.assertEqual([(r['chunk_index'], r['segment_index'], r['start'], r['end']) for r in entries],
                         [(0,0,53.,55.), (1,0,53.,54.)])
        self.assertNotIn('avg_logprob', result['segments'][0])
        self.assertEqual(entries[1]['avg_logprob'], -2.)
        self.assertEqual(result['quality_diagnostics']['association'], 'original_window_segments_not_merged_text')
        legacy = long_media.merge_chunks(manifest, [{'segments':first['segments']}, second])
        self.assertEqual(legacy['quality_diagnostics']['status'], 'partial')

    def test_short_evidence_passes_validated_metrics_without_text_change(self):
        parsed = {'raw_text':'原文', 'truncated':False, 'duration_seconds':1.,
                  'segments':[{'start':0., 'end':1., 'text':'原文'}], 'segment_metrics':[metric()]}
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'own.wav'; source.write_bytes(b'audio')
            runner = lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=json.dumps(parsed).encode())
            result = evidence.prepare('asr', source, 'douyin', '123', 'self-owned', runner=runner,
                                      asr_model=Path(directory))
            self.assertEqual(result['evidence']['quality_diagnostics']['status'], 'available')
            self.assertEqual(result['evidence']['raw_text'], '原文')
            parsed.pop('segment_metrics')
            legacy = evidence.prepare('asr', source, 'douyin', '123', 'self-owned', runner=runner,
                                      asr_model=Path(directory))
            self.assertEqual(legacy['evidence']['quality_diagnostics']['status'], 'unknown')

    def test_chunk_cache_preserves_metrics_and_changed_processor_rejects(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'own.wav'; work = Path(directory) / 'chunks'
            with wave.open(str(source), 'wb') as stream:
                stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(16000)
                stream.writeframes(b'\x00\x00' * 16000 * 70)
            calls = []
            def provider(path):
                calls.append(path.name)
                return {'segments':[{'start':0., 'end':1., 'text':'原文'}], 'truncated':False,
                        'segment_metrics':[metric(avg_logprob=-1.2)]}
            with self.assertRaisesRegex(ValueError, 'long_media_cancelled'):
                long_media.transcribe_long(source, None, work, cancel=lambda:len(calls)==1, transcriber=provider)
            cached = json.loads((work / 'result-0000.json').read_text())
            self.assertEqual(cached['segment_metrics'][0]['avg_logprob'], -1.2)
            result = long_media.transcribe_long(source, None, work, transcriber=provider)
            self.assertEqual(calls, ['chunk-0000.wav', 'chunk-0001.wav'])
            self.assertEqual(result['quality_diagnostics']['status'], 'available')
            self.assertEqual(long_media.transcribe_long(source, None, work, transcriber=lambda _:self.fail('cache must reuse')), result)
            real_digest = long_media.digest
            with patch.object(long_media, 'digest', side_effect=lambda path:'changed' if Path(path).name=='local_asr.py' else real_digest(path)):
                with self.assertRaisesRegex(ValueError, 'chunk_cache_identity_mismatch'):
                    long_media.transcribe_long(source, None, work, transcriber=lambda _:self.fail('must not rerun'))
            self.assertEqual(json.loads((work / 'result-0000.json').read_text()), cached)


if __name__ == '__main__':
    unittest.main()
