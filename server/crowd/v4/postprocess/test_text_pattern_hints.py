import copy
import unittest
from pathlib import Path
import subprocess
from transcript_quality import text_pattern_hints


class PatternHints(unittest.TestCase):
    def test_actual_credit_output_even_confident_native(self):
        rows = [{'start': 0, 'end': 15.04, 'text': '字幕志愿者 李宗盛'}]
        before = copy.deepcopy(rows)
        hints = text_pattern_hints(rows)
        self.assertEqual(hints[0]['kind'], 'credit_style_output')
        self.assertIn('not_proven', hints[0]['basis'])
        self.assertEqual(rows, before)

    def test_mention_in_full_dialogue_not_whole_output(self):
        rows = [{'text': '字幕志愿者这个词如何理解？'}] + [{'text': '正常对白' + str(i)} for i in range(5)]
        self.assertEqual(text_pattern_hints(rows), [])

    def test_repetition_lyrics_are_hints_not_deletions(self):
        rows = [{'text': '我可以去哪里'} for _ in range(4)] + [{'text': '不同句'}]
        before = copy.deepcopy(rows)
        hints = text_pattern_hints(rows)
        self.assertEqual(hints[0]['segment_indices'], [0, 1, 2, 3])
        self.assertIn('lyrics', hints[0]['basis'])
        self.assertEqual(rows, before)

    def test_empty_and_two_repetitions_no_pattern(self):
        self.assertEqual(text_pattern_hints([]), [])
        self.assertEqual(text_pattern_hints([{'text': '真的真的'}, {'text': '真的真的'}]), [])

class NativeConfidenceDoesNotOverridePattern(unittest.TestCase):
    def test_actual_ui_preview_warns_without_native_flags(self):
        source = (Path(__file__).parent.parent / 'multiplatform/media-ui.js').read_text()
        functions = source.split('  function repeatedTextIndices(', 1)[1].split("  $('media_process_close')", 1)[0]
        script = "const assert=require('node:assert/strict');function repeatedTextIndices(" + functions
        script += "const e={segments:[{text:'字幕志愿者 李宗盛'}],quality_diagnostics:{schema_version:1,status:'available',time_basis:'original_audio_seconds',segments:[{start:0,end:15,text:'字幕志愿者 李宗盛',flags:[],avg_logprob:-.478,no_speech_prob:4e-11,compression_ratio:.694}]}};const text=qualityText(e);assert.match(text,/署名式输出疑点/);assert.match(text,/可能是真实内容/);assert.equal(e.segments[0].text,'字幕志愿者 李宗盛');e.segments=[{text:'正常对白'}];assert.doesNotMatch(qualityText(e),/署名式输出疑点/);"
        result = subprocess.run(['/Users/hubowen/.local/node/bin/node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_actual_high_confidence_credit_lookup_adds_readonly_hint(self):
        from unittest.mock import patch
        from transcript_quality import TranscriptQuality
        rows=[{'start':0,'end':15.04,'text':'字幕志愿者 李宗盛'}]
        saved={'job_id':'fixture','audio_source_job_id':None,'result_sha256':'a'*64,'state':{'asset_sha256':'b'*64,'platform':'kuaishou','content_id':'fixture'},'evidence':{'segments':rows,'duration_seconds':15.071,'quality_diagnostics':{'segments':[dict(rows[0],avg_logprob=-.478,compression_ratio=.694,no_speech_prob=4e-11,flags=[])]}}}
        with patch.object(TranscriptQuality,'validate',return_value=saved):
            value=TranscriptQuality(Path('/private/tmp')).lookup('fixture')
        self.assertEqual(value['quality']['native_metric_status'],'available')
        self.assertEqual(value['quality']['flag_counts']['possible_no_speech'],0)
        self.assertEqual(value['quality']['text_pattern_hints'][0]['kind'],'credit_style_output')
        self.assertFalse(value['quality']['automatic_text_replacement'])
