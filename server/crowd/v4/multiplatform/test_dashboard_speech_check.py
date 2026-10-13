from pathlib import Path
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import Mock
from dashboard import Application


class SpeechCheckRoute(unittest.TestCase):
    def setUp(self):
        self.app=Application.__new__(Application);self.app.lock=threading.RLock()
        self.app.media_jobs=SimpleNamespace(capabilities=lambda:{'asr_engines':['cpu','mlx']},start=Mock(return_value={'state':'queued'}))
        self.app._registered_run_root=lambda _:Path('/owned')
        self.app.media_file=Mock(return_value=Path('/owned/audio.m4a'))
        self.app.run=Mock(return_value={'records':[{'kind':'content','platform':'bilibili','content_id':'123'}],
            'media':[{'path':'audio.m4a','content_id':'123','sha256':'a'*64}]})
        self.payload={'run_id':'owned-run','path':'audio.m4a','content_id':'123','kind':'asr'}

    def test_explicit_check_forwarded_and_default_signature_preserved(self):
        self.app.process_media('start',{**self.payload,'speech_check':True,'asr_engine':'mlx'})
        self.assertIs(self.app.media_jobs.start.call_args.kwargs['speech_check'],True)
        self.app.process_media('start',self.payload)
        self.assertNotIn('speech_check',self.app.media_jobs.start.call_args.kwargs)

    def test_invalid_or_non_asr_check_rejected_before_source_read(self):
        for value in (1,None,'true',[]):
            with self.assertRaisesRegex(ValueError,'invalid_speech_check'):
                self.app.process_media('start',{**self.payload,'speech_check':value})
        with self.assertRaisesRegex(ValueError,'invalid_speech_check'):
            self.app.process_media('start',{**self.payload,'kind':'video_ocr','speech_check':False})
        self.app.media_file.assert_not_called()

    def test_bypass_reuses_original_registered_asset_and_explicit_false(self):
        saved={'job_id':'old','run_id':'owned-run','asset_sha256':'a'*64,'content_id':'123','kind':'asr',
            'speech_check':True,'state':'failed','reason':'vad_no_speech_detected','speech_precheck':{'has_speech':False},'asr_engine':'mlx'}
        self.app.media_jobs.status=Mock(return_value=saved)
        self.app.process_media('speech_check_bypass',{'job_id':'old'})
        self.assertIs(self.app.media_jobs.start.call_args.kwargs['speech_check'],False)
        self.assertEqual(self.app.media_jobs.start.call_args.kwargs['asr_engine'],'mlx')
        self.assertEqual(saved['state'],'failed')
        self.app.run.return_value['media'].append(dict(self.app.run.return_value['media'][0]))
        with self.assertRaisesRegex(ValueError,'speech_check_original_media_unavailable'):
            self.app.process_media('speech_check_bypass',{'job_id':'old'})

    def test_unknown_or_failed_detector_cannot_be_bypassed_as_zero(self):
        self.app.media_jobs.status=Mock(return_value={'kind':'asr','speech_check':True,'state':'interrupted_unknown',
            'reason':'vad_no_speech_detected','speech_precheck':{'has_speech':False}})
        with self.assertRaisesRegex(ValueError,'speech_check_bypass_not_available'):
            self.app.process_media('speech_check_bypass',{'job_id':'old'})
        self.app.run.assert_not_called()




class SpeechCheckStatusProof(unittest.TestCase):
    def test_zero_requires_original_snapshot_and_complete_manifest(self):
        import hashlib,json,tempfile,uuid,wave
        from media_jobs import MediaJobs
        from mc_runner import write
        from speech_precheck import validate_report,PROFILE,MODEL_SHA,VAD_SOURCE_SHA,PACKAGES,OPTIONS
        with tempfile.TemporaryDirectory() as directory:
            manager=MediaJobs(directory);folder=manager.root/str(uuid.uuid4());folder.mkdir()
            work=folder/'long-asr';work.mkdir();source=folder/'input.wav'
            with wave.open(str(source),'wb') as stream:
                stream.setparams((1,2,16000,100,'NONE','not compressed'));stream.writeframes(b'\0\0'*100)
            raw=source.read_bytes();sha=hashlib.sha256(raw).hexdigest();(work/'chunk-0000.wav').write_bytes(raw)
            manifest={'schema':1,'asset_sha256':sha,'duration_seconds':100/16000,'segment_seconds':55,'overlap_seconds':2,'source_kind':'authorized_local_file','network':False,
                'chunks':[{'index':0,'start':0,'end':100/16000,'file':'chunk-0000.wav','sha256':sha}]}
            report={'profile':PROFILE,'state':'completed','asset_sha256':sha,'model_sha256':MODEL_SHA,'vad_source_sha256':VAD_SOURCE_SHA,
                'packages':PACKAGES,'options':OPTIONS,'semantic_status':'not_reviewed','audio_was_cut':False,
                'windows':[{'index':0,'pcm_sha256':sha,'samples':100,'intervals':[],'speech_samples':0}]}
            state={'job_id':folder.name,'kind':'asr','state':'failed','speech_check':True,'asset_sha256':sha,
                'processing_profile':'standard_25mib_3600s','reason':'vad_no_speech_detected'}
            def save():
                write(folder/'state.json',state);write(work/'chunks.json',manifest);write(work/'speech-check.json',report)
                summary=validate_report(report,manifest);summary['diagnostic_sha256']=hashlib.sha256((work/'speech-check.json').read_bytes()).hexdigest()
                write(work/'state.json',{'state':'failed','reason':'vad_no_speech_detected','speech_precheck':summary})
            try:
                save();self.assertIs(manager.status(folder.name)['speech_precheck']['has_speech'],False)
                self.assertNotIn('speech_precheck',manager.status(folder.name,include_result=False))
                manifest['asset_sha256']='a'*64;report['asset_sha256']='a'*64;save()
                with self.assertRaisesRegex(ValueError,'speech_precheck_diagnostic_changed'):manager.status(folder.name)
                manifest['asset_sha256']=sha;report['asset_sha256']=sha;save();source.write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError,'speech_precheck_diagnostic_changed'):manager.status(folder.name)
                source.write_bytes(raw);(work/'chunk-0000.wav').write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError,'speech_precheck_diagnostic_changed'):manager.status(folder.name)
                manifest['chunks']=[];report['windows']=[];write(work/'chunks.json',manifest);write(work/'speech-check.json',report)
                with self.assertRaisesRegex(ValueError,'speech_precheck_diagnostic_changed'):manager.status(folder.name)
            finally:manager.close()

if __name__=='__main__':unittest.main()
