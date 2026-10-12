import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from media_jobs import MediaJobs

class MacSelection(unittest.TestCase):
    def test_opt_in_requires_explicit_runtime_and_cpu_remains_default(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{},clear=True):
            manager=MediaJobs(directory)
            self.assertEqual(manager.capabilities()['asr_default_engine'],'cpu')
            self.assertEqual(manager.capabilities()['asr_engines'],['cpu'])
            with self.assertRaisesRegex(ValueError,'not_configured'):manager._asr_configuration('mlx')
            with self.assertRaisesRegex(ValueError,'invalid_asr_engine'):manager._asr_configuration('remote')
            manager.close()

    def test_cpu_weights_cannot_be_labeled_mac_engine(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);model=root/'model';model.mkdir();(model/'crowd-model.json').write_text('{}')
            executable=root/'python';executable.write_text('fixture');executable.chmod(0o700)
            with patch.dict(os.environ,{'CROWD_MAC_ASR_MODEL':str(model),'CROWD_MAC_ASR_PYTHON':str(executable)}),patch('media_jobs.sys.platform','darwin'):
                manager=MediaJobs(root/'runtime')
                with self.assertRaisesRegex(ValueError,'invalid_mac_asr_model_manifest'):manager._asr_configuration('mlx')
                self.assertEqual(manager.capabilities()['asr_engines'],['cpu'])
                (model/'crowd-model.json').write_text(json.dumps({'engine':'mlx_whisper_local'}))
                self.assertEqual(manager._asr_configuration('mlx'),(model.resolve(),str(executable)))
                self.assertEqual(manager._asr_configuration('mlx_fast'),(model.resolve(),str(executable)))
                self.assertEqual(manager.capabilities()['asr_engines'],['cpu','mlx','mlx_fast'])
                manager.close()

    def test_actual_start_metadata_can_enter_full_analysis(self):
        import hashlib,time,uuid
        from mc_runner import write
        from analysis_jobs import AnalysisJobs
        from analysis_contract import build_snapshot
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);model=root/'model';model.mkdir()
            (model/'crowd-model.json').write_text(json.dumps({'engine':'mlx_whisper_local'}))
            executable=root/'python';executable.write_text('fixture');executable.chmod(0o700)
            source=root/'fixture.wav';source.write_bytes(b'owned-offline-fixture')
            run=str(uuid.uuid4());body={'run_id':run,'records':[{'platform':'douyin','kind':'content','content_id':'123','title':'测试原文','body':'测试正文'}]}
            def completed(state,snapshot,process_lock):
                result=[{'platform':'douyin','content_id':'123','kind':'transcript','evidence':{
                    'asset_sha256':state['asset_sha256'],'source_kind':'authorized_local_file','truncated':False,
                    'processor':'mlx_whisper_local_segmented','duration_seconds':55.,'timeline':'absolute_seconds',
                    'segments':[{'start':0.,'end':1.,'text':'隔离测试候选非真实转写'}]}}]
                write(snapshot.parent/'result.json',result);state.update(state='completed');write(snapshot.parent/'state.json',state);process_lock.close()
            with patch.dict(os.environ,{'CROWD_MAC_ASR_MODEL':str(model),'CROWD_MAC_ASR_PYTHON':str(executable)}),patch('media_jobs.sys.platform','darwin'):
                manager=MediaJobs(root/'runtime')
                with patch.object(manager,'_execute',side_effect=completed):
                    state=manager.start(source,'douyin','123','asr',run,asr_engine='mlx')
                    manager.threads[state['job_id']].join(3)
                self.assertIn('mlx_asr.py',state['processor_files']);self.assertIn('audio_result_cache.py',state['processor_files'])
                analysis=AnalysisJobs(root/'runtime',executable='/nonexistent-offline-provider')
                try:
                    options=analysis.media_inputs(body,build_snapshot(body,'douyin','123'),run)['options']
                    self.assertEqual(len(options),1)
                    ref={k:options[0][k] for k in ('job_id','result_sha256','asset_sha256')}
                    selected=analysis.media_inputs(body,build_snapshot(body,'douyin','123'),run,[ref])['selected']
                    result=build_snapshot(body,'douyin','123',derived_inputs=selected)
                    self.assertEqual(result['derived_inputs'][0]['processor'],'mlx_whisper_local_segmented')
                finally:analysis.close();manager.close()

    def test_fast_worker_explicitly_passes_segment_mode_and_word_does_not(self):
        import uuid
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);manager=MediaJobs(root/'runtime')
            for engine in ('cpu','mlx','mlx_fast'):
                folder=manager.root/str(uuid.uuid4());folder.mkdir()
                snapshot=folder/'input.wav';snapshot.write_bytes(b'offline-command-fixture')
                state={'job_id':folder.name,'kind':'asr','platform':'bili','content_id':'123',
                       'asr_engine':engine,'asset_sha256':'0'*64}
                process=MagicMock();process.pid=123;process.returncode=1
                lock=MagicMock();lock.fileno.return_value=42
                with patch.object(manager,'_asr_configuration',return_value=(root/'model','offline-python')),patch('media_jobs.subprocess.Popen',return_value=process) as spawn:
                    manager._execute(state,snapshot,lock)
                command=spawn.call_args.args[0]
                self.assertEqual('--asr-timing-mode' in command,engine=='mlx_fast')
                if engine=='mlx_fast':self.assertEqual(command[-2:],['--asr-timing-mode','segment'])
                self.assertEqual(state['state'],'failed')
            manager.close()

if __name__=='__main__':unittest.main()
