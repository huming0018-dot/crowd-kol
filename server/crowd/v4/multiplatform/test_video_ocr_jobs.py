import gzip,hashlib,json,os,tempfile,unittest,uuid,subprocess
from pathlib import Path
from unittest.mock import patch
from mc_runner import canonical,write
from media_jobs import MediaJobs
import video_ocr_jobs as ocr

class VideoOCRJobsTests(unittest.TestCase):
    def test_explicit_retry_preserves_failed_prioritizes_active_and_rejects_unknown(self):
        from unittest.mock import Mock
        from types import SimpleNamespace
        threads=[]
        def create_thread(*args,**kwargs):
            thread=Mock();thread.is_alive.return_value=True
            thread.start.side_effect=kwargs['args'][-1].close
            threads.append(thread);return thread
        with patch.object(ocr,'source',return_value=(self.source,self.binding)) as resolve,patch.object(ocr,'native_configuration',return_value=(self.root/'native','d'*64)),patch.dict(os.environ,{'CROWD_FFMPEG':str(self.source)}),patch.object(ocr.subprocess,'run',return_value=SimpleNamespace(stderr=b'Duration: 00:00:02.10\nVideo: h264')),patch.object(ocr.threading,'Thread',side_effect=create_thread):
            with self.assertRaisesRegex(ValueError,'invalid_video_ocr_retry'):ocr.start(self.jobs,self.parent,self.run,retry=1)
            resolve.assert_not_called()
            first=ocr.start(self.jobs,self.parent,self.run);first_path=self.jobs.root/first['job_id']/'state.json'
            threads[0].is_alive.return_value=False
            failed=json.loads(first_path.read_text());failed.update(state='failed',reason='offline-failed-fixture');write(first_path,failed);preserved=first_path.read_bytes()
            reused=ocr.start(self.jobs,self.parent,self.run);self.assertEqual(reused['job_id'],first['job_id']);self.assertEqual(len(threads),1)
            second=ocr.start(self.jobs,self.parent,self.run,retry=True)
            self.assertNotEqual(second['job_id'],first['job_id']);self.assertEqual(second['retry_of_job_id'],first['job_id'])
            self.assertEqual(first_path.read_bytes(),preserved)
            double=ocr.start(self.jobs,self.parent,self.run,retry=True)
            self.assertEqual(double['job_id'],second['job_id']);self.assertEqual(len(threads),2)
            second_path=self.jobs.root/second['job_id']/'state.json';active=json.loads(second_path.read_text());active['state']='running';write(second_path,active)
            self.assertEqual(ocr.start(self.jobs,self.parent,self.run)['job_id'],second['job_id'])
            active['state']='completed';write(second_path,active);write(second_path.parent/'result.json',[])
            self.assertTrue(ocr.start(self.jobs,self.parent,self.run,retry=True)['cached'])
            active['state']='cancelled';write(second_path,active)
            threads[1].is_alive.return_value=False
            cancelled_bytes=second_path.read_bytes();third=ocr.start(self.jobs,self.parent,self.run,retry=True)
            self.assertEqual(third['retry_of_job_id'],second['job_id']);self.assertEqual(second_path.read_bytes(),cancelled_bytes)
            threads[2].is_alive.return_value=False
            with self.assertRaisesRegex(ValueError,'reconciliation_required'):ocr.start(self.jobs,self.parent,self.run,retry=True)
            self.assertEqual(first_path.read_bytes(),preserved)
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
        from video_ocr_geometry import project
        frames=[{'index':i,'time':i*.5,'sha256':'a'*64,'blocks':[{'text':'画面fixture','confidence':.5,**project([.2,.5,.4,.3],.67,.82),'selected':True}],'native_seconds':.1} for i in range(5)]
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

    def test_registered_asr_parent_seven_platforms_and_real_body_hash(self):
        from test_media_native import Tests as NativeFixture
        from media_native import PLATFORMS
        fixture=NativeFixture();fixture.setUp()
        try:
            for platform_code,platform in PLATFORMS.items():
                with self.subTest(platform=platform):
                    fixture.seed(platform_code,ctype='answer' if platform=='zhihu' else None)
                    self.normalize_native_fixture(fixture,platform_code,'answer' if platform=='zhihu' else None)
                    parent=str(uuid.uuid4());folder=self.jobs.root/parent;folder.mkdir();(folder/'input.mp4').write_bytes(fixture.data)
                    entity='zhihu:content:123:answer' if platform=='zhihu' else platform+':content:123'
                    write(folder/'result.json',[{'kind':'transcript','platform':platform,'content_id':'123','evidence':{'asset_sha256':fixture.sha}}])
                    write(folder/'state.json',{'job_id':parent,'kind':'asr','state':'completed','platform':platform,'content_id':'123','run_id':fixture.run,'entity_ref':entity,'asset_sha256':fixture.sha,'result_sha256':ocr.sha(folder/'result.json')})
                    path,binding=ocr.source(self.jobs,parent,fixture.folder)
                    self.assertEqual(path,folder/'input.mp4');self.assertEqual(binding['entity_ref'],entity)
                    self.assertEqual(binding['source_record_sha256'],fixture.body['record_hash'])
                    self.assertEqual(binding['source_parent_result_sha256'],ocr.sha(folder/'result.json'))
                    original_body=dict(fixture.body);fixture.body['title']='forged normalized body'
                    fixture.body['record_hash']=hashlib.sha256(canonical({k:v for k,v in fixture.body.items() if k not in ('record_hash','discovery_kind')}).encode()).hexdigest();fixture.save()
                    with self.assertRaisesRegex(ValueError,'raw_body_changed'):ocr.source(self.jobs,parent,fixture.folder)
                    fixture.body=original_body;fixture.normalized['records']=[fixture.body];fixture.save()
                    (folder/'input.mp4').write_bytes(fixture.data+b'changed')
                    with self.assertRaisesRegex(ValueError,'source_changed'):ocr.source(self.jobs,parent,fixture.folder)
        finally:fixture.tearDown()

    def test_registered_asr_cannot_guess_missing_body_hash_or_use_unregistered_file(self):
        from test_media_native import Tests as NativeFixture
        fixture=NativeFixture();fixture.setUp()
        try:
            self.normalize_native_fixture(fixture,'dy')
            parent=str(uuid.uuid4());folder=self.jobs.root/parent;folder.mkdir();(folder/'input.mp4').write_bytes(fixture.data)
            write(folder/'result.json',[{'kind':'transcript','platform':'douyin','content_id':'123','evidence':{'asset_sha256':fixture.sha}}])
            state={'job_id':parent,'kind':'asr','state':'completed','platform':'douyin','content_id':'123','run_id':fixture.run,'entity_ref':'douyin:content:123','asset_sha256':fixture.sha,'result_sha256':ocr.sha(folder/'result.json')};write(folder/'state.json',state)
            fixture.normalized['records'][0].pop('record_hash');fixture.save()
            with self.assertRaises(ValueError):ocr.source(self.jobs,parent,fixture.folder)
            fixture.seed('dy');fixture.normalized['media']=[];fixture.save()
            with self.assertRaises(ValueError):ocr.source(self.jobs,parent,fixture.folder)
            state['state']='failed';write(folder/'state.json',state)
            with self.assertRaisesRegex(ValueError,'parent_invalid'):ocr.source(self.jobs,parent,fixture.folder)
        finally:fixture.tearDown()

    def normalize_native_fixture(self,fixture,code,ctype=None):
        from mc_runner import normalize,ID_KEYS
        raw={ID_KEYS[code]:'123','title':'original title','desc':'original body'}
        if ctype:raw['content_type']=ctype
        path=fixture.folder/fixture.normalized['files'][0]['path'];path.write_text(json.dumps(raw)+'\n');file_sha=ocr.sha(path)
        origin={'run_id':fixture.run,'file_sha256':file_sha,'line':1}
        fixture.body=normalize(code,'content',raw,origin)
        fixture.normalized['records']=[fixture.body];fixture.normalized['files'][0]['sha256']=file_sha;fixture.save()

    def test_direct_registered_video_reference_skips_asr_and_copy_with_stable_parent(self):
        from test_media_native import Tests as NativeFixture
        from media_native import PLATFORMS
        fixture=NativeFixture();fixture.setUp()
        try:
            for code,platform in PLATFORMS.items():
                with self.subTest(platform=platform):
                    fixture.seed(code,ctype='answer' if platform=='zhihu' else None);self.normalize_native_fixture(fixture,code,'answer' if platform=='zhihu' else None)
                    entity='zhihu:content:123:answer' if platform=='zhihu' else platform+':content:123'
                    with patch.object(ocr,'start',return_value={'job_id':'offline-no-inference'}) as dispatch:
                        self.assertEqual(ocr.start_saved_video_ocr(self.jobs,fixture.folder,fixture.asset,platform,'123',entity,retry=True)['job_id'],'offline-no-inference')
                        parent=dispatch.call_args.args[1];parent_folder=self.jobs.root/parent
                        state=json.loads((parent_folder/'state.json').read_text());self.assertEqual(state['kind'],'registered_video_reference');self.assertTrue(state['registration_only'])
                        self.assertEqual(sorted(p.name for p in parent_folder.iterdir()),['result.json','state.json'])
                        original=parent_folder.joinpath('state.json').read_bytes();path,binding=ocr.source(self.jobs,parent,fixture.folder)
                        self.assertEqual(path,fixture.asset);self.assertEqual(binding['source_record_sha256'],fixture.body['record_hash'])
                        ocr.start_saved_video_ocr(self.jobs,fixture.folder,fixture.asset,platform,'123',entity)
                        self.assertEqual(dispatch.call_args.args[1],parent);self.assertEqual((parent_folder/'state.json').read_bytes(),original)
                        outside=self.root/'unregistered.mp4';outside.write_bytes(fixture.data)
                        with self.assertRaisesRegex(ValueError,'saved_source_ambiguous'):ocr.start_saved_video_ocr(self.jobs,fixture.folder,outside,platform,'123',entity)
                        state['state']='interrupted_unknown';write(parent_folder/'state.json',state);before=dispatch.call_count
                        with self.assertRaisesRegex(ValueError,'reconciliation_required'):ocr.start_saved_video_ocr(self.jobs,fixture.folder,fixture.asset,platform,'123',entity,retry=True)
                        self.assertEqual(dispatch.call_count,before)
        finally:fixture.tearDown()

if __name__=='__main__':unittest.main()
