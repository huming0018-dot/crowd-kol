import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import wave
import long_media
import speech_precheck as sp


class WholeInputPrecheck(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.source=self.root/'own.wav';self.work=self.root/'work'
        with wave.open(str(self.source),'wb') as stream:
            stream.setparams((1,2,16000,0,'NONE','not compressed'));stream.writeframes(b'\x00\x00'*16000*60)
        self.manifest=long_media.prepare_chunks(self.source,self.work)

    def tearDown(self):self.temp.cleanup()

    def report(self,speech_at=None):
        value={'profile':sp.PROFILE,'state':'completed','asset_sha256':self.manifest['asset_sha256'],
            'model_sha256':sp.MODEL_SHA,'vad_source_sha256':sp.VAD_SOURCE_SHA,'packages':sp.PACKAGES,'options':sp.OPTIONS,
            'semantic_status':'not_reviewed','audio_was_cut':False,'windows':[]}
        for chunk in self.manifest['chunks']:
            count=round((chunk['end']-chunk['start'])*16000)
            rows=[{'start':0,'end':1}] if chunk['index']==speech_at else []
            value['windows'].append({'index':chunk['index'],'pcm_sha256':chunk['sha256'],'samples':count,'intervals':rows,'speech_samples':len(rows)})
        return value

    def save_report(self,report):long_media.save(self.work/'speech-check.json',report)

    def test_whole_zero_blocks_before_any_asr_keeps_all_pcm_and_diagnostic(self):
        self.save_report(self.report());provider=Mock()
        before={p.name:sp.digest(p) for p in self.work.glob('chunk-*.wav')}
        with self.assertRaisesRegex(ValueError,'vad_no_speech_detected'):
            long_media.transcribe_long(self.source,None,self.work,transcriber=provider,speech_check=True)
        provider.assert_not_called();state=json.loads((self.work/'state.json').read_text())
        self.assertEqual(state['reason'],'vad_no_speech_detected');self.assertEqual(state['state'],'failed')
        self.assertEqual(state['speech_precheck']['processed_windows'],2)
        self.assertFalse(state['speech_precheck']['has_speech'])
        self.assertEqual(before,{p.name:sp.digest(p) for p in self.work.glob('chunk-*.wav')})
        self.assertEqual(list(self.work.glob('result-*.json')),[])

    def test_one_short_speech_in_later_window_processes_all_original_windows(self):
        self.save_report(self.report(1));calls=[]
        def provider(path):
            calls.append(path.name)
            return {'segments':[{'start':0,'end':1,'text':'歌曲也保留'}],'truncated':False}
        result=long_media.transcribe_long(self.source,None,self.work,transcriber=provider,speech_check=True)
        self.assertEqual(calls,['chunk-0000.wav','chunk-0001.wav'])
        self.assertTrue(result['speech_precheck']['has_speech'])
        self.assertEqual(result['speech_precheck']['speech_samples'],1)
        self.assertEqual(result['speech_precheck']['semantic_status'],'not_reviewed')

    def test_bypass_false_continues_original_whole_asr_after_saved_zero(self):
        self.save_report(self.report());calls=[]
        def provider(path):
            calls.append(path.name);return {'segments':[{'start':0,'end':1,'text':'继续听写'}],'truncated':False}
        with patch.object(sp,'check',side_effect=AssertionError('bypass must not run VAD')):
            result=long_media.transcribe_long(self.source,None,self.work,transcriber=provider,speech_check=False)
        self.assertEqual(len(calls),2);self.assertNotIn('speech_precheck',result)
        self.assertTrue((self.work/'speech-check.json').is_file())

    def test_failed_or_partial_or_modified_report_never_zero(self):
        for mutation in ('partial','failed','source','model','count','interval'):
            report=copy.deepcopy(self.report())
            if mutation=='partial':report['windows'].pop()
            elif mutation=='failed':report['state']='failed'
            elif mutation=='source':report['windows'][0]['pcm_sha256']='0'*64
            elif mutation=='model':report['model_sha256']='0'*64
            elif mutation=='count':report['windows'][0]['speech_samples']=1
            else:report['windows'][0]['intervals']=[{'start':-1,'end':1}]
            with self.assertRaisesRegex(ValueError,'invalid_speech_precheck'):
                sp.validate_report(report,self.manifest)

    def test_unknown_dependency_failure_does_not_become_no_speech(self):
        with patch.object(sp,'check',side_effect=ValueError('speech_precheck_failed')):
            with self.assertRaisesRegex(ValueError,'speech_precheck_failed'):
                long_media.transcribe_long(self.source,None,self.work,transcriber=Mock(),speech_check=True)
        state=json.loads((self.work/'state.json').read_text())
        self.assertNotIn('speech_precheck',state);self.assertEqual(state['reason'],'speech_precheck_failed')

    def test_on_off_cache_identities_separate(self):
        self.save_report(self.report(1))
        provider=lambda _: {'segments':[{'start':0,'end':1,'text':'保留'}],'truncated':False}
        long_media.transcribe_long(self.source,None,self.work,transcriber=provider,speech_check=True)
        with self.assertRaisesRegex(ValueError,'long_media_chunk_cache_identity_mismatch'):
            long_media.transcribe_long(self.source,None,self.work,transcriber=provider,speech_check=False)

    def test_consistent_report_cannot_hide_incomplete_or_invalid_manifest(self):
        for mutation in ('empty','partial','extra','schema_bool','asset','duration','offset','no_source'):
            manifest=copy.deepcopy(self.manifest);report=copy.deepcopy(self.report())
            if mutation=='empty':manifest['chunks']=[];report['windows']=[]
            elif mutation=='partial':manifest['chunks'].pop();report['windows'].pop()
            elif mutation=='extra':manifest['chunks'].append(copy.deepcopy(manifest['chunks'][-1]));report['windows'].append(copy.deepcopy(report['windows'][-1]))
            elif mutation=='schema_bool':manifest['schema']=True
            elif mutation=='asset':manifest['asset_sha256']='bad';report['asset_sha256']='bad'
            elif mutation=='duration':manifest['duration_seconds']=float('nan')
            elif mutation=='offset':manifest['chunks'][1]['start']=52
            else:manifest.pop('source_kind')
            with self.assertRaisesRegex(ValueError,'invalid_speech_precheck_manifest'):sp.validate_report(report,manifest)

    def test_bool_and_interval_validation(self):
        for value in (None,1,'on'):
            with self.assertRaisesRegex(ValueError,'invalid_speech_check'):
                long_media.transcribe_long('/unused',None,'/unused',speech_check=value)
        for value in ([{'start':False,'end':1}],[{'start':0,'end':16001}],None):
            with self.assertRaisesRegex(ValueError,'invalid_speech_precheck_intervals'):sp.intervals(value,16000)

if __name__=='__main__':unittest.main()
