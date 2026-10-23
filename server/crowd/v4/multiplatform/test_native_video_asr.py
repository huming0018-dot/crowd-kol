"""Source-bound native video processing with fake models; no source requests or inference."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock,patch

import media_jobs as jobs
import media_native
import test_media_native as fixture_module

POST=jobs.PROCESSOR.parent
spec=importlib.util.spec_from_file_location('native_video_asr_test',POST/'native_video_asr.py')
native=importlib.util.module_from_spec(spec);spec.loader.exec_module(native)

class NativeVideoAsrTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture_module.Tests();self.fixture.setUp();self.root=self.fixture.root
        self.model=self.root/'model';self.model.mkdir();(self.model/'crowd-model.json').write_text('{}')
        self.manager=jobs.MediaJobs(self.root,self.model)
    def tearDown(self):self.manager.close();self.fixture.tearDown()
    def grow(self,size):
        t=self.fixture
        with open(t.asset,'r+b') as stream:stream.truncate(size)
        t.sha=hashlib.sha256(t.asset.read_bytes()).hexdigest();t.item.update(bytes=size,sha256=t.sha);t.save()
    def start(self,kind='asr',cid='123',run=None,entity=None):
        t=self.fixture
        with patch.object(media_native,'_duration',return_value=5400000),patch.object(self.manager,'_execute',side_effect=self.complete):
            state=self.manager.start(t.asset,t.platform,cid,kind,run or t.run,entity_ref=entity,native_run_folder=t.folder)
            self.manager.threads[state['job_id']].join(3);return state
    def complete(self,state,snapshot,process_lock):
        try:
            jobs.write(snapshot.parent/'result.json',[{'platform':state['platform'],'content_id':state['content_id'],'evidence':{'asset_sha256':state['asset_sha256'],'segments':[{'start':0,'end':1,'text':'synthetic'}]}}])
            state.update(state='completed');jobs.write(snapshot.parent/'state.json',state)
        finally:process_lock.close()
    def test_bound_26mib_native_snapshot_profile_playback_resume(self):
        self.grow(26*1024*1024);t=self.fixture;source_hash=t.sha
        state=self.start();folder=self.manager.root/state['job_id'];snapshot=folder/'input.mp4'
        self.assertEqual(state['processing_profile'],native.PROFILE);self.assertEqual(hashlib.sha256(snapshot.read_bytes()).hexdigest(),source_hash)
        self.assertIn('native_video_asr.py',state['processor_files']);context=json.loads((folder/'native-asr-context.json').read_text())
        native.validate_context(context,snapshot,state,data=snapshot.read_bytes())
        state.update(state='completed');jobs.write(folder/'state.json',state);jobs.write(folder/'result.json',[{'platform':t.platform,'content_id':'123','evidence':{'asset_sha256':source_hash}}])
        self.assertEqual(self.manager.playback(state['job_id'],source_hash)['data'],t.asset.read_bytes())
        self.assertTrue(self.start()['cached'])
        state.update(state='cancelled');jobs.write(folder/'state.json',state)
        with patch.object(self.manager,'_execute',side_effect=self.complete):
            resumed=self.manager.resume(state['job_id']);self.manager.threads[state['job_id']].join(3)
        self.assertEqual(resumed['job_id'],state['job_id']);self.assertEqual(hashlib.sha256(snapshot.read_bytes()).hexdigest(),source_hash)
        self.assertEqual(hashlib.sha256(t.asset.read_bytes()).hexdigest(),source_hash)
    def test_no_registration_ocr_wrong_identity_and_over64_reject(self):
        self.grow(26*1024*1024);t=self.fixture
        with self.assertRaises(ValueError):self.manager.start(t.asset,t.platform,'123','asr',t.run)
        with self.assertRaises(ValueError):self.start(kind='ocr')
        with self.assertRaises(ValueError):self.start(cid='other')
        with self.assertRaises(ValueError):self.start(run='other')
        self.grow(64*1024*1024+1)
        with self.assertRaises(ValueError):self.start()
        self.assertEqual(list(self.manager.root.iterdir()),[])
    def test_small_native_completed_cache_identity_stays_legacy(self):
        t=self.fixture
        with patch.object(self.manager,'_execute',side_effect=self.complete):
            old=self.manager.start(t.asset,t.platform,'123','asr',t.run);self.manager.threads[old['job_id']].join(3)
        folder=self.manager.root/old['job_id'];old.update(state='completed');jobs.write(folder/'state.json',old);jobs.write(folder/'result.json',[{'evidence':{'asset_sha256':t.sha}}])
        before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
        with patch.object(media_native,'_duration',return_value=1000):new=self.manager.start(t.asset,t.platform,'123','asr',t.run,native_run_folder=t.folder)
        self.assertEqual(new['job_id'],old['job_id']);self.assertTrue(new['cached'])
        self.assertNotIn('native_video_asr.py',new['processor_files']);self.assertNotIn('native_video_context_sha256',new)
        self.assertEqual(before,{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()})
    def test_metadata_audio_duration_and_source_drift_fail_closed(self):
        self.grow(26*1024*1024);t=self.fixture
        with patch.object(media_native,'_duration',side_effect=ValueError('media_native_audio_track_missing')):
            with self.assertRaises(ValueError):self.manager.preview(t.asset,t.platform,'123','asr',t.run,native_run_folder=t.folder)
        t.item['sha256']='a'*64;t.save()
        with self.assertRaises(ValueError):self.start()
    def test_context_strict_types_dynamic_and_old_limits(self):
        self.grow(26*1024*1024);state=self.start();folder=self.manager.root/state['job_id'];context=json.loads((folder/'native-asr-context.json').read_text())
        for change in ({'schema_version':True},{'schema_version':1.0},{'audio_duration_ms':True},{'audio_duration_ms':7200001},{'entity_ref':'douyin:dynamic:123'},{'asset_sha256':'x'*64}):
            with self.subTest(change=change),self.assertRaises(ValueError):native.validate_context({**context,**change},folder/'input.mp4')
        dynamic={**context,'platform':'bilibili','entity_ref':'bilibili:dynamic:123'};native.validate_context(dynamic,folder/'input.mp4')
        altered={**context,'normalized_sha256':'a'*64};jobs.write(folder/'native-asr-context.json',altered)
        state.update(state='completed');jobs.write(folder/'state.json',state);jobs.write(folder/'result.json',[])
        with self.assertRaises(ValueError):self.manager.playback(state['job_id'],state['asset_sha256'])
        self.assertEqual(self.manager.capabilities()['limits']['bytes'],25*1024*1024)
    def test_real_private_ffmpeg_metadata_has_audio_and_rejects_silent_video(self):
        executable=Path(__file__).resolve().parents[5]/'outputs/unified-crawler-implementation-2026-10-11/long-media-tools/lib/python3.9/site-packages/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1'
        self.assertTrue(executable.is_file())
        audio=self.root/'own-audio.mp4';silent=self.root/'own-silent.mp4'
        subprocess.run([str(executable),'-v','error','-f','lavfi','-i','color=s=16x16:r=1','-f','lavfi','-i','sine=frequency=440','-t','2','-c:v','libx264','-c:a','aac',str(audio)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        subprocess.run([str(executable),'-v','error','-f','lavfi','-i','color=s=16x16:r=1','-t','2','-c:v','libx264',str(silent)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        with patch.dict(os.environ,{'CROWD_FFMPEG':str(executable)}):
            self.assertEqual(media_native._duration(audio.read_bytes(),require_audio=True),2000)
            with self.assertRaisesRegex(ValueError,'audio_track_missing'):media_native._duration(silent.read_bytes(),require_audio=True)
    def test_native_wrapper_freezes_bytes_and_restores_only_local_limits(self):
        self.grow(26*1024*1024);state=self.start();folder=self.manager.root/state['job_id'];context=json.loads((folder/'native-asr-context.json').read_text())
        sys.path.insert(0,str(POST))
        try:
            import long_media
            previous=(long_media.MAX_BYTES,long_media.MAX_SECONDS)
            def offline(source,model,work,**kwargs):
                self.assertEqual((long_media.MAX_BYTES,long_media.MAX_SECONDS),(64*1024*1024,7200))
                (folder/'input.mp4').write_bytes(b'changed after freeze')
                self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),state['asset_sha256'])
                return {'segments':[{'start':0,'end':1,'text':'synthetic'}],'raw_text':'synthetic'}
            with patch.object(long_media,'transcribe_long',side_effect=offline):
                result=native.prepare(folder/'input.mp4',self.model,folder/'work',context)
            self.assertEqual(result['asset_sha256'],state['asset_sha256']);self.assertEqual((long_media.MAX_BYTES,long_media.MAX_SECONDS),previous)
            with self.assertRaises(ValueError):native.prepare(folder/'input.mp4',self.model,folder/'work',context)
            self.assertEqual((long_media.MAX_BYTES,long_media.MAX_SECONDS),previous)
        finally:sys.path.remove(str(POST))
    def test_actual_executor_native_command_and_context_are_bound(self):
        self.grow(26*1024*1024);state=self.start();folder=self.manager.root/state['job_id'];state.update(state='queued')
        process=Mock(returncode=0,pid=123);process.poll.return_value=0
        process_lock=open(self.manager.root/'processor.lock','a+')
        with patch.object(jobs.subprocess,'Popen',return_value=process) as launch:self.manager._execute(state,folder/'input.mp4',process_lock)
        command=launch.call_args.args[0];self.assertEqual(command[1],str(POST/'native_video_asr.py'))
        self.assertEqual(command[command.index('--native-video-context')+1],str(folder/'native-asr-context.json'))
        self.assertEqual(self.manager.status(state['job_id'])['state'],'completed')
    def test_actual_http_preview_strict_no_scope_override_and_csrf(self):
        import dashboard,threading,urllib.request,urllib.error
        self.grow(26*1024*1024);t=self.fixture;app=dashboard.Application(self.root);app.media_jobs=self.manager
        server=dashboard.make_server(app,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        url='http://127.0.0.1:'+str(server.server_port);payload={'run_id':t.run,'path':t.item['path'],'content_id':'123','kind':'asr'}
        def request(body,token=None):
            headers={'Content-Type':'application/json','Origin':url,'X-Crowd-CSRF':app.token if token is None else token}
            req=urllib.request.Request(url+'/api/media-processing',data=json.dumps(body).encode(),headers=headers)
            try:
                with urllib.request.urlopen(req) as response:return response.status,response.headers.get('Content-Type'),json.load(response)
            except urllib.error.HTTPError as error:return error.code,error.headers.get('Content-Type'),json.load(error)
        try:
            with patch.object(app,'run',return_value={'ok':True,'result':t.normalized}),patch.object(app,'_registered_run_root',return_value=self.root),patch.object(media_native,'_duration',return_value=5400000):
                status,mime,result=request({'action':'preview','payload':payload})
                self.assertEqual(status,200);self.assertIn('application/json',mime);self.assertTrue(result['native_video_verified'])
                self.assertEqual(result['max_input_bytes'],64*1024*1024);self.assertEqual(result['max_audio_seconds'],7200)
                for altered in ({**payload,'native_asr':True},{**payload,'processing_profile':native.PROFILE},{**payload,'content_id':'other'}):
                    self.assertEqual(request({'action':'preview','payload':altered})[0],400)
                self.assertEqual(request({'action':'preview','payload':payload},'wrong')[0],403)
                self.assertEqual(len(list(self.manager.root.iterdir())),0)
        finally:
            server.shutdown();server.server_close();thread.join(2);app.watchlists.close()
            if app.owner_tasks is not None:app.owner_tasks.close()

if __name__=='__main__':unittest.main()
