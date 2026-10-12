import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('mlx_asr',Path(__file__).with_name('mlx_asr.py'))
mlx_asr=importlib.util.module_from_spec(spec);spec.loader.exec_module(mlx_asr)

class LocalBoundary(unittest.TestCase):
    def test_hub_name_never_downloaded(self):
        with self.assertRaisesRegex(ValueError,'verified_local_mlx_model_required'):
            mlx_asr.verify_model('mlx-community/whisper-large-v3-turbo')

    def test_unverified_or_symlink_manifest_rejected_without_engine_import(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);manifest=root/'crowd-model.json'
            manifest.write_text(json.dumps({'engine':'mlx_whisper_local'}))
            with self.assertRaisesRegex(ValueError,'mlx_model_manifest_invalid'):
                mlx_asr.verify_model(root)
            manifest.unlink(); target=root/'data.json';target.write_text('{}');manifest.symlink_to(target)
            with self.assertRaisesRegex(ValueError,'verified_local_mlx_model_required'):
                mlx_asr.verify_model(root)

class AlignmentBoundary(unittest.TestCase):
    def test_true_engine_receipt_and_bounds(self):
        rows=[{'start':0.,'end':1.,'text':'你好'}]
        receipt={'method':'mlx_whisper_word_timestamps','source':'mlx_native_output_with_word_timestamps',
            'pcm_duration_seconds':2.,'aligned_estimates':rows,'word_estimates':[{'segment_index':0,
                'words':[{'start':0.,'end':1.,'text':'你好'}]}],'semantic_status':'not_reviewed'}
        self.assertEqual(mlx_asr.validate_alignment(receipt,rows,2.),receipt)
        for mutation in ('method','text','end'):
            value=json.loads(json.dumps(receipt))
            if mutation=='method':value['method']='faster_whisper_word_timestamps'
            elif mutation=='text':value['word_estimates'][0]['words'][0]['text']='伪造'
            else:value['word_estimates'][0]['words'][0]['end']=3.
            with self.assertRaisesRegex(ValueError,'invalid_native_asr_alignment'):
                mlx_asr.validate_alignment(value,rows,2.)


class VerifiedLifecycle(unittest.TestCase):
    def test_lazy_once_verified_and_mutation_fails_even_restored_mtime(self):
        from unittest.mock import patch
        import os
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve()
            for name in ('crowd-model.json','config.json','weights.safetensors'):(root/name).write_bytes(b'owned-fixture')
            session=mlx_asr.VerifiedSession(root)
            with patch.object(mlx_asr,'verify_model',return_value=(root,{})) as verify,patch.object(mlx_asr,'_transcribe_verified',return_value={'value':'unchanged'}) as native,patch.object(mlx_asr,'_provider_result',side_effect=lambda value:value):
                self.assertEqual(verify.call_count,0)
                self.assertEqual(session('first'),{'value':'unchanged'})
                self.assertEqual(session('second'),{'value':'unchanged'})
                self.assertEqual(verify.call_count,1);self.assertEqual(native.call_count,2)
                path=root/'weights.safetensors';old=path.stat();path.write_bytes(b'other-fixture');os.utime(path,ns=(old.st_atime_ns,old.st_mtime_ns))
                with self.assertRaisesRegex(ValueError,'mlx_model_changed_during_job'):session('third')
                self.assertEqual(native.call_count,2)

    def test_change_during_first_hash_and_alternate_weights_refused(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve()
            for name in ('crowd-model.json','config.json','weights.safetensors'):(root/name).write_bytes(b'owned-fixture')
            def changed(path):
                (root/'config.json').write_bytes(b'changed-fixture')
                return root,{}
            session=mlx_asr.VerifiedSession(root)
            with patch.object(mlx_asr,'verify_model',side_effect=changed),patch.object(mlx_asr,'_transcribe_verified') as native:
                with self.assertRaisesRegex(ValueError,'mlx_model_changed_during_job'):session('first')
                native.assert_not_called()
            (root/'model.safetensors').write_bytes(b'unverified')
            with self.assertRaisesRegex(ValueError,'mlx_model_unverified_alternate'):mlx_asr.VerifiedSession(root)('first')


class DecoderTimestampBoundary(unittest.TestCase):
    def test_segment_mode_retains_proved_tail_without_claiming_words(self):
        import copy
        import local_asr
        native={'timing_mode':'segment','duration_seconds':55.,'model_repository':'fixture','model_revision':'fixture',
            'package_version':'0.4.3','decoding':'greedy_temperature_zero','result':{'segments':[
            {'start':54.76,'end':55.76,'text':'好','seek':5476,'avg_logprob':-.2,'no_speech_prob':.1,'compression_ratio':1.}]}}
        result=mlx_asr._provider_result(native)
        self.assertEqual(result['segments'][0]['end'],55.)
        self.assertEqual(result['timing_adjustments'][0]['provider_end'],55.76)
        self.assertEqual(result['timing_adjustments'][0]['reason'],'provider_padding_tail')
        receipt=result['native_alignment']
        self.assertEqual(receipt['method'],'mlx_whisper_decoder_timestamps')
        self.assertNotIn('word_estimates',receipt)
        self.assertEqual(local_asr.validate_native_alignment(receipt,result['segments'],55.),receipt)
        for mutation in ('padding','one_second','fake_word'):
            value=copy.deepcopy(receipt)
            if mutation=='padding':value['token_estimates'][0]['padding_end']=60.
            elif mutation=='one_second':value['token_estimates'][0]['end']=56.
            else:value['method']='mlx_whisper_word_timestamps'
            with self.assertRaisesRegex(ValueError,'invalid_native_asr_alignment'):
                local_asr.validate_native_alignment(value,result['segments'],55.)

    def test_unknown_timing_and_cpu_segment_requests_refused(self):
        import local_asr
        with self.assertRaisesRegex(ValueError,'invalid_mlx_timing_mode'):mlx_asr.VerifiedSession('/unused','wrong')
        with self.assertRaisesRegex(ValueError,'segment_timing_requires_mlx_provider'):
            local_asr.transcribe('/unused','/unused',asr_timing_mode='segment')

if __name__=='__main__':unittest.main()
