import gzip,hashlib,json,os,tempfile,unittest,uuid,subprocess
from pathlib import Path
from unittest.mock import patch
from mc_runner import canonical,write
from media_jobs import MediaJobs
import video_ocr_jobs as ocr

class VideoOCRJobsTests(unittest.TestCase):
    def test_child_stderr_digest_and_fixed_diagnostic_do_not_log_raw_secrets(self):
        folder=self.root/'errors';folder.mkdir()
        raw=b'Cookie=secret https://private.test/?token=hidden'
        report=ocr.safe_child_error(folder,1,raw)
        self.assertNotIn('secret',json.dumps(report));self.assertNotIn('private.test',json.dumps(report))
        write(folder/'video-ocr-error.json',{'reason':'video_ocr_frame_decode_failed','exception_type':'ValueError','python_version':'3.9.6','stack':[], 'stage':{'name':'decode','frame_index':0,'returncode':1}})
        self.assertEqual(ocr.safe_child_error(folder,1,raw)['reason'],'video_ocr_frame_decode_failed')
        write(folder/'video-ocr-error.json',{'reason':'video_ocr_frame_decode_failed','exception_type':'ValueError','python_version':'3.9.6','stack':[{'file':'https://private.test/token','line':1,'function':'f'}], 'stage':{'name':'decode','frame_index':0,'returncode':1}})
        self.assertNotIn('reason',ocr.safe_child_error(folder,1,raw))
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve();self.jobs=MediaJobs(self.root/'runtime')
        self.run_id=str(uuid.uuid4());self.run=self.root/self.run_id;self.run.mkdir()
        self.parent=str(uuid.uuid4());self.parent_folder=self.jobs.root/self.parent;self.parent_folder.mkdir()
        self.source=self.parent_folder/'source.mp4';self.source.write_bytes(b'offline-owned-video-fixture')
        self.binding={'video_source_job_id':self.parent,'run_id':self.run_id,'platform':'douyin','content_id':'123','entity_ref':'douyin:content:123','asset_sha256':ocr.sha(self.source),'source_bytes':len(self.source.read_bytes()),'source_record_sha256':'b'*64,'source_reference_sha256':'c'*64}
    def tearDown(self):self.jobs.close();self.tmp.cleanup()

    def completed(self):
        job=str(uuid.uuid4());folder=self.jobs.root/job;folder.mkdir();work=folder/'video-ocr';work.mkdir()
        frames=[{'index':i,'time':i*.5,'sha256':'a'*64,'blocks':[{'text':'画面fixture','confidence':.5,'bbox':[.2,.7,.4,.04],'selected':True}],'native_seconds':.1} for i in range(5)]
        proof=gzip.compress(json.dumps(frames).encode(),mtime=0);(work/'frames.json.gz').write_bytes(proof)
        files={name:ocr.sha(ocr.ROOT/name) for name in ocr.FILES}
        e={'processor':'apple_vision_sampled_video_text','source_kind':'sampled_video_text','spoken_transcript':False,'cer':None,'truncated':False,'asset_sha256':self.binding['asset_sha256'],'sample_start':0.,'sample_end':2.1,'duration_seconds':2.1,'sample_fps':2,'timestamp_uncertainty_seconds':.5,'crop_top_origin':[.67,.82],'compiled_binary_sha256':'d'*64,'provider_source_sha256':files['video_vision.swift'],'frame_evidence_sha256':hashlib.sha256(proof).hexdigest(),'frame_evidence_file':'frames.json.gz','sampled_frames':5,'expected_frames':5,'segments':[{'start':0.,'end':2.1,'text':'画面fixture'}],'segment_frame_ranges':[[0,4]]}
        write(folder/'result.json',[{'kind':'video_text','platform':'douyin','content_id':'123','evidence':e}])
        identity={**self.binding,'duration_seconds':2.1,'crop_top':.67,'crop_bottom':.82,'compiled_binary_sha256':'d'*64,'processor_files':files,'processing_profile':ocr.PROFILE}
        state={**identity,'input_hash':hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest(),'job_id':job,'kind':'video_ocr','state':'completed','run_folder':str(self.run),'result_sha256':ocr.sha(folder/'result.json')}
        write(folder/'state.json',state);return job,folder,e

    def test_loader_complete_sampled_text_and_tampered_proof_rejected(self):
        job,folder,e=self.completed()
        with patch.object(ocr,'source',return_value=(self.source,self.binding)),patch.object(ocr,'native_configuration',return_value=(self.root/'native','d'*64)):
            loaded=ocr.load_video_ocr(self.jobs,job);self.assertEqual(loaded['evidence']['segments'],e['segments'])
            (folder/'video-ocr/frames.json.gz').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'frames_changed'):ocr.load_video_ocr(self.jobs,job)

    def test_incomplete_samples_and_claimed_speech_rejected(self):
        job,folder,e=self.completed()
        with patch.object(ocr,'source',return_value=(self.source,self.binding)),patch.object(ocr,'native_configuration',return_value=(self.root/'native','d'*64)):
            result=json.loads((folder/'result.json').read_text());result[0]['evidence']['spoken_transcript']=True;write(folder/'result.json',result)
            state=json.loads((folder/'state.json').read_text());state['result_sha256']=ocr.sha(folder/'result.json');write(folder/'state.json',state)
            with self.assertRaisesRegex(ValueError,'coverage_incomplete'):ocr.load_video_ocr(self.jobs,job)

    def test_rewritten_consistent_result_and_state_roi_cannot_reuse_old_identity(self):
        job,folder,e=self.completed();state=json.loads((folder/'state.json').read_text())
        state['crop_top']=.6;write(folder/'state.json',state)
        result=json.loads((folder/'result.json').read_text());result[0]['evidence']['crop_top_origin']=[.6,.82];write(folder/'result.json',result)
        state['result_sha256']=ocr.sha(folder/'result.json');write(folder/'state.json',state)
        with patch.object(ocr,'source',return_value=(self.source,self.binding)),patch.object(ocr,'native_configuration',return_value=(self.root/'native','d'*64)):
            with self.assertRaisesRegex(ValueError,'input_hash_changed'):ocr.load_video_ocr(self.jobs,job)

    def test_per_component_legal_bbox_cannot_extend_outside_frame(self):
        job,folder,e=self.completed();p=folder/'video-ocr/frames.json.gz'
        frames=json.loads(gzip.decompress(p.read_bytes()));frames[0]['blocks'][0]['bbox']=[.9,.7,.4,.04]
        proof=gzip.compress(json.dumps(frames).encode(),mtime=0);p.write_bytes(proof)
        result=json.loads((folder/'result.json').read_text());result[0]['evidence']['frame_evidence_sha256']=hashlib.sha256(proof).hexdigest();write(folder/'result.json',result)
        state=json.loads((folder/'state.json').read_text());state['result_sha256']=ocr.sha(folder/'result.json');write(folder/'state.json',state)
        with patch.object(ocr,'source',return_value=(self.source,self.binding)),patch.object(ocr,'native_configuration',return_value=(self.root/'native','d'*64)):
            with self.assertRaisesRegex(ValueError,'frames_invalid'):ocr.load_video_ocr(self.jobs,job)

    def test_native_requires_explicit_matching_markers(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaisesRegex(ValueError,'not_configured'):ocr.native_configuration()
        native=self.root/'native';native.write_bytes(b'offline');native.chmod(0o700)
        (self.root/'native.source.sha256').write_text(ocr.sha(ocr.ROOT/'video_vision.swift'))
        (self.root/'native.binary.sha256').write_text(ocr.sha(native))
        with patch.dict(os.environ,{'CROWD_VIDEO_OCR_NATIVE':str(native)}):
            self.assertEqual(ocr.native_configuration()[0],native)
            native.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'native_changed'):ocr.native_configuration()

    def test_source_revalidates_body_reference_and_downloaded_bytes(self):
        write(self.parent_folder/'state.json',{'job_id':self.parent,'kind':'complete_audio','state':'failed','platform':'douyin','run_id':self.run_id,'content_id':'123','source_reference_sha256':'c'*64})
        write(self.parent_folder/'video-progress.json',{'source_sha256':self.binding['asset_sha256'],'downloaded_bytes':self.binding['source_bytes']})
        write(self.run/'manifest.json',{'run_id':self.run_id});write(self.run/'status.json',{'run_id':self.run_id,'state':'completed'})
        with patch.object(ocr,'reference',return_value=({'reference_sha256':'c'*64},'b'*64)):
            path,binding=ocr.source(self.jobs,self.parent,self.run);self.assertEqual(path,self.source)
            self.assertEqual(binding,self.binding)
            self.source.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'source_changed'):ocr.source(self.jobs,self.parent,self.run)

    def test_real_child_local_video_fixture_shared_slot_complete_and_reuse(self):
        ffmpeg=os.environ.get('CROWD_FFMPEG')
        if not ffmpeg or not Path(ffmpeg).is_file():self.skipTest('existing ffmpeg required')
        self.source.unlink()
        subprocess.run([ffmpeg,'-v','error','-f','lavfi','-i','color=black:size=320x240:rate=30','-t','2.1','-c:v','libx264',str(self.source)],check=True)
        self.binding.update(asset_sha256=ocr.sha(self.source),source_bytes=self.source.stat().st_size)
        native=self.root/'native'
        native.write_text('''#!/Users/hubowen/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
import json,sys
for line in sys.stdin:
 row=json.loads(line)
 print(json.dumps({'index':row['index'],'blocks':[{'text':'offline fixture','confidence':.5,'bbox':[.2,.5,.4,.3]}],'native_seconds':.01,'truncated':False}),flush=True)
''');native.chmod(0o700)
        (self.root/'native.source.sha256').write_text(ocr.sha(ocr.ROOT/'video_vision.swift'));(self.root/'native.binary.sha256').write_text(ocr.sha(native))
        with patch.dict(os.environ,{'CROWD_VIDEO_OCR_NATIVE':str(native)}),patch.object(ocr,'source',return_value=(self.source,self.binding)):
            state=self.jobs.start_video_ocr(self.parent,self.run);self.jobs.threads[state['job_id']].join(10)
            state=self.jobs.status(state['job_id']);self.assertEqual(state['state'],'completed',state)
            self.assertEqual(state['processed_frames'],5);self.assertEqual(state['expected_frames'],5)
            self.assertEqual(ocr.load_video_ocr(self.jobs,state['job_id'])['evidence']['segments'][0]['text'],'offline fixture')
            reused=self.jobs.start_video_ocr(self.parent,self.run);self.assertEqual(reused['job_id'],state['job_id'])
            self.assertTrue(reused['cached']);self.assertTrue(self.source.is_file())

if __name__=='__main__':unittest.main()
