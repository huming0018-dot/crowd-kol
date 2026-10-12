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

if __name__=='__main__':unittest.main()
