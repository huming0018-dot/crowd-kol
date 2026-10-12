import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.error
import uuid

import complete_video as video
from media_jobs import MediaJobs


class Response(io.BytesIO):
    def __init__(self,data,headers=None):
        super().__init__(data);self.status=200;self.headers=headers or {'Content-Length':str(len(data))}


class Opener:
    def __init__(self,values):self.values=list(values);self.requests=[]
    def open(self,request,timeout):
        self.requests.append(request)
        value=self.values.pop(0)
        if isinstance(value,Exception):raise value
        return value


class CompleteVideoTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve();self.run_id=str(uuid.uuid4())
        folder=self.root/'runs'/self.run_id/'output/douyin/jsonl';folder.mkdir(parents=True)
        self.raw=folder/'detail_contents.jsonl';self.raw.write_text(json.dumps({'aweme_id':'123','aweme_type':'0','video_download_url':'https://www.douyin.com/aweme/v1/play/?video_id=synthetic-private-signature'})+'\n')
        self.ref=video.source_reference(self.root/'runs'/self.run_id,self.run_id,'123')
        self.work=self.root/'work';self.work.mkdir()
    def tearDown(self):self.tmp.cleanup()

    def test_reference_exact_identity_changes_and_no_public_url(self):
        public=video.public_reference(self.ref)
        self.assertNotIn('synthetic-private-signature',json.dumps(public));self.assertNotIn('url',public)
        self.assertEqual(public['network_input_limit_bytes'],256*1024*1024)
        self.assertFalse(public['collection_budget_changed']);self.assertEqual(public['model_calls'],0)
        with self.assertRaisesRegex(ValueError,'ambiguous_or_missing'):video.source_reference(self.root/'runs'/self.run_id,self.run_id,'999')
        old=self.ref['reference_sha256'];self.raw.write_text(self.raw.read_text()+'\n')
        self.assertNotEqual(old,video.source_reference(self.root/'runs'/self.run_id,self.run_id,'123')['reference_sha256'])
        self.raw.write_text(json.dumps({'aweme_id':'123','video_download_url':'https://www.douyin.com/other'})+'\n'+json.dumps({'aweme_id':'123','video_download_url':'https://www.douyin.com/different'})+'\n')
        with self.assertRaisesRegex(ValueError,'ambiguous_or_missing'):video.source_reference(self.root/'runs'/self.run_id,self.run_id,'123')

    def test_denied_hosts_and_redirect_do_not_send_second_request(self):
        for url in ('http://www.douyin.com/video','https://127.0.0.1/','https://www.douyin.com.evil.test/','https://u:p@www.douyin.com/','https://www.douyin.com:444/','https://www.douyin.com/\nheader','https://www.douyin.com/#token'):
            with self.assertRaisesRegex(ValueError,'url_denied'):video.safe_url(url)
        error=urllib.error.HTTPError(self.ref['url'],302,'private-message',{'Location':'https://localhost/private'},io.BytesIO())
        opener=Opener([error])
        with self.assertRaisesRegex(ValueError,'url_denied'):video.run(self.ref,self.work,opener)
        self.assertEqual(len(opener.requests),1)
        request=opener.requests[0];self.assertFalse(any(key.lower() in ('cookie','authorization') for key in request.headers))

    def test_input_limit_truncation_and_no_retry(self):
        opener=Opener([Response(b'abc',{'Content-Length':str(video.INPUT_LIMIT+1)})])
        with self.assertRaisesRegex(ValueError,'input_limit'):video.run(self.ref,self.work,opener)
        self.assertFalse((self.work/'source.part').exists());self.assertEqual(len(opener.requests),1)
        opener=Opener([Response(b'abc',{'Content-Length':'8'})])
        with self.assertRaisesRegex(ValueError,'incomplete'):video.run(self.ref,self.work,opener)
        self.assertEqual((self.work/'source.part').read_bytes(),b'abc');self.assertEqual(len(opener.requests),1)
        (self.work/'source.part').unlink()
        with patch.object(video,'INPUT_LIMIT',2):
            with self.assertRaisesRegex(ValueError,'input_limit'):video.run(self.ref,self.work,Opener([Response(b'abc',{'Other':'no-length'})]))

    def test_cancel_and_existing_symlink_hardlink_preserve_outside(self):
        (self.work/'cancel.requested').touch();opener=Opener([])
        with self.assertRaisesRegex(ValueError,'cancelled'):video.run(self.ref,self.work,opener)
        self.assertEqual(len(opener.requests),0);(self.work/'cancel.requested').unlink()
        outside=self.root/'outside';outside.write_bytes(b'unchanged')
        for mode in ('symlink','hardlink'):
            target=self.work/'source.part'
            target.symlink_to(outside) if mode=='symlink' else os.link(outside,target)
            with self.assertRaisesRegex(ValueError,'existing_asset'):video.run(self.ref,self.work,Opener([]))
            self.assertEqual(outside.read_bytes(),b'unchanged');target.unlink()
        link=self.root/'linked';link.symlink_to(self.work,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'unsafe'):video.run(self.ref,link,Opener([]))

    def test_real_ffmpeg_whole_synthetic_decode_transcode_and_identity(self):
        ffmpeg=os.environ.get('CROWD_FFMPEG')
        if not ffmpeg or not Path(ffmpeg).is_file():self.skipTest('existing ffmpeg required; no installation')
        source=self.root/'synthetic.mp4'
        subprocess.run([ffmpeg,'-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=15','-f','lavfi','-i','sine=frequency=440:sample_rate=16000','-t','2','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(source)],check=True)
        data=source.read_bytes();old=hashlib.sha256(data).hexdigest();opener=Opener([Response(data)])
        result=video.run(self.ref,self.work,opener);item=result[0];evidence=item['evidence']
        self.assertEqual(item['content_id'],'123');self.assertEqual(evidence['source_asset_sha256'],old)
        self.assertEqual(evidence['asset_sha256'],hashlib.sha256((self.work/'video.mp4').read_bytes()).hexdigest())
        self.assertEqual(evidence['source_reference_sha256'],self.ref['reference_sha256'])
        self.assertTrue(evidence['full_source_decode']);self.assertTrue(evidence['full_output_decode'])
        self.assertLessEqual(abs(evidence['duration_seconds']-2),.25);self.assertEqual(evidence['network_attempts'],1)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),old);self.assertNotIn('synthetic-private-signature',json.dumps(result))
        self.assertEqual((self.work/'video.mp4').stat().st_mode & 0o777,0o600)
        self.assertTrue((self.work/'source.mp4').is_file())
        audio_work=self.root/'audio-work';audio_work.mkdir()
        audio=video.run(self.ref,audio_work,Opener([Response(data)]),output_kind='audio')[0]
        self.assertEqual(audio['kind'],'processed_audio')
        self.assertTrue(audio['evidence']['full_source_audio_decode'])
        self.assertTrue(audio['evidence']['full_output_decode'])
        self.assertLessEqual(abs(audio['evidence']['duration_seconds']-2),.25)
        self.assertEqual(audio['evidence']['source_asset_sha256'],old)
        self.assertEqual(audio['evidence']['asset_sha256'],hashlib.sha256((audio_work/'audio.m4a').read_bytes()).hexdigest())
        self.assertFalse((audio_work/'video.mp4').exists())
        self.assertFalse((audio_work/'source.mp4').exists())
        decoded=subprocess.run([ffmpeg,'-hide_banner','-i',str(audio_work/'audio.m4a')],capture_output=True).stderr.decode()
        self.assertIn('Audio: aac',decoded);self.assertNotIn('Video:',decoded)

    def test_audio_job_asr_binding_rechecks_source_body_result_and_asset(self):
        from mc_runner import canonical,write
        from unittest.mock import Mock
        run=self.root/'runs'/self.run_id
        body={'kind':'content','platform':'douyin','content_id':'123','title':'fixture',
              'origin':{'run_id':self.run_id,'file_sha256':self.ref['source_file_sha256']}}
        body['record_hash']=hashlib.sha256(canonical(body).encode()).hexdigest()
        write(run/'normalized.json',{'run_id':self.run_id,'source_kind':'mediacrawler_api','reward_eligible':False,'records':[body]})
        write(run/'manifest.json',{'run_id':self.run_id});write(run/'status.json',{'run_id':self.run_id,'state':'completed'})
        jobs=MediaJobs(self.root/'binding');job_id=str(uuid.uuid4());folder=jobs.root/job_id;folder.mkdir()
        data=b'isolated-audio-fixture';digest=hashlib.sha256(data).hexdigest();(folder/'audio.m4a').write_bytes(data)
        e={'source_run_id':self.run_id,'source_reference_sha256':self.ref['reference_sha256'],'source_asset_sha256':'a'*64,
           'asset_sha256':digest,'bytes':len(data),'full_source_audio_decode':True,'full_output_decode':True,'duration_seconds':2.,'source_duration_seconds':2.}
        write(folder/'result.json',[{'kind':'processed_audio','platform':'douyin','content_id':'123','evidence':e}])
        state={'job_id':job_id,'kind':'complete_audio','state':'completed','run_id':self.run_id,'platform':'douyin','content_id':'123','asset_sha256':digest,'source_reference_sha256':self.ref['reference_sha256'],'result_sha256':hashlib.sha256((folder/'result.json').read_bytes()).hexdigest()}
        write(folder/'state.json',state)
        try:
            with patch.object(jobs,'start',return_value={'job_id':'offline-asr'}) as start:
                result=jobs.start_asr_from_audio_job(job_id,run,asr_engine='mlx')
                self.assertEqual(result['job_id'],'offline-asr')
                self.assertEqual(start.call_args.kwargs['audio_reference_binding']['source_record_hash'],body['record_hash'])
                self.assertEqual(start.call_args.kwargs['entity_ref'],'douyin:content:123')
                with self.assertRaisesRegex(ValueError,'identity_mismatch'):jobs.start_asr_from_audio_job(job_id,run,'douyin:content:999')
                (folder/'audio.m4a').write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError,'result_changed'):jobs.start_asr_from_audio_job(job_id,run)
                self.assertEqual(start.call_count,1)
        finally:jobs.close()

    def test_failed_download_is_fixed_error_no_secret_or_retry(self):
        opener=Opener([urllib.error.URLError('cookie_private_failure')])
        with self.assertRaisesRegex(ValueError,'^video_source_network_error$'):video.run(self.ref,self.work,opener)
        self.assertEqual(len(opener.requests),1)

    def test_audio_failed_unknown_attempts_known_progress_or_explicit_unknown(self):
        from mc_runner import write
        jobs=MediaJobs(self.root/'attempts')
        try:
            for phase,attempts in (('failed',3),('queued',2),('cancelled',None)):
                job_id=str(uuid.uuid4());folder=jobs.root/job_id;folder.mkdir()
                write(folder/'state.json',{'job_id':job_id,'kind':'complete_audio','state':phase})
                if attempts is not None:write(folder/'video-progress.json',{'network_attempts':attempts})
                state=jobs.status(job_id)
                self.assertEqual(state['network_attempts'],attempts)
                if phase=='queued':self.assertEqual(state['state'],'interrupted_unknown')
            write(folder/'video-progress.json',{'network_attempts':True})
            self.assertIsNone(jobs.status(job_id)['network_attempts'])
            write(folder/'video-progress.json',{'network_attempts':5})
            self.assertIsNone(jobs.status(job_id)['network_attempts'])
        finally:jobs.close()

    def test_verified_no_audio_uses_different_current_default_once_with_remaining_three(self):
        from mc_runner import write
        ffmpeg=os.environ.get('CROWD_FFMPEG')
        if not ffmpeg or not Path(ffmpeg).is_file():self.skipTest('existing ffmpeg required')
        run=self.root/'runs'/self.run_id;sidecar=run/'output/douyin/video-references/123.json';sidecar.parent.mkdir()
        write(sidecar,{'schema_version':1,'run_id':self.run_id,'platform':'douyin','content_id':'123','source_kind':'same_native_aweme_detail','reported_bytes':1024,'reported_bitrate':1000,'url':'https://www.douyin.com/video-only'})
        sidecar.chmod(0o600);original=video.source_reference(run,self.run_id,'123');sidecar_hash=hashlib.sha256(sidecar.read_bytes()).hexdigest()
        source=self.root/'video-only.mp4'
        subprocess.run([ffmpeg,'-v','error','-f','lavfi','-i','testsrc2=size=64x64:rate=10','-t','1','-c:v','libx264',str(source)],check=True)
        data=source.read_bytes();previous_id=str(uuid.uuid4());previous=self.root/previous_id;previous.mkdir()
        opener=Opener([Response(data)])
        with self.assertRaisesRegex(ValueError,'^complete_audio_stream_missing$'):video.run(original,previous,opener,output_kind='audio')
        write(previous/'state.json',{'job_id':previous_id,'kind':'complete_audio','state':'failed','reason':'complete_audio_stream_missing','run_id':self.run_id,'platform':'douyin','content_id':'123','source_reference_sha256':original['reference_sha256'],'input_hash':'b'*64})
        variant=video.source_reference(run,self.run_id,'123',variant='native_default_after_verified_no_audio',previous_job=previous)
        self.assertEqual(variant['max_request_attempts'],3);self.assertNotEqual(variant['url_sha256'],original['url_sha256'])
        self.assertEqual(variant['previous_source_sha256'],hashlib.sha256(data).hexdigest());self.assertEqual(variant['previous_job_id'],previous_id)
        self.assertEqual(hashlib.sha256(sidecar.read_bytes()).hexdigest(),sidecar_hash)
        progress=json.loads((previous/'video-progress.json').read_text());progress['network_attempts']=2;write(previous/'video-progress.json',progress)
        with self.assertRaisesRegex(ValueError,'not_proven'):video.source_reference(run,self.run_id,'123',variant=variant['variant'],previous_job=previous)
        self.assertEqual(len(opener.requests),1)
        retry=self.root/'one-attempt';retry.mkdir()
        redirect=urllib.error.HTTPError(variant['url'],302,'',{'Location':'https://www.douyin.com/next'},io.BytesIO())
        redirected=Opener([redirect])
        with self.assertRaisesRegex(ValueError,'redirect_limit'):video.run({**variant,'max_request_attempts':1},retry,redirected,output_kind='audio')
        self.assertEqual(len(redirected.requests),1)

    def test_job_real_child_lifecycle_reuse_and_download_hash(self):
        executable=self.root/'fake-local-python'
        executable.write_text('''#!/usr/bin/env python3
import hashlib,json,pathlib,sys
p=pathlib.Path(sys.argv[sys.argv.index('--reference')+1]);r=json.loads(p.read_text());f=p.parent
audio='--output-kind' in sys.argv
data=b'isolated-processor-output';(f/('audio.m4a' if audio else 'video.mp4')).write_bytes(data)
e={'source_reference_sha256':r['reference_sha256'],'asset_sha256':hashlib.sha256(data).hexdigest(),'duration_seconds':2,'network_attempts':1,'source_asset_sha256':'a'*64,'source_bytes':100}
(f/'result.json').write_text(json.dumps([{'kind':'processed_audio' if audio else 'processed_video','platform':'douyin','content_id':r['content_id'],'evidence':e}]))
''');executable.chmod(0o700)
        jobs=MediaJobs(self.root,python=str(executable))
        try:
            state=jobs.start_video(self.ref);job_id=state['job_id']
            jobs.threads[job_id].join(5);state=jobs.status(job_id)
            self.assertEqual(state['state'],'completed');self.assertFalse((jobs.root/job_id/'input-ref.json').exists())
            self.assertEqual(jobs.start_video(self.ref)['job_id'],job_id)
            self.assertEqual(jobs.video_file(job_id,state['asset_sha256'])['data'],b'isolated-processor-output')
            with self.assertRaisesRegex(ValueError,'identity_mismatch'):jobs.video_file(job_id,'a'*64)
            (jobs.root/job_id/'video.mp4').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'asset_changed'):jobs.video_file(job_id,state['asset_sha256'])
            with self.assertRaisesRegex(ValueError,'invalid_media_job_id'):jobs.video_file('../bad','a'*64)
            self.assertNotIn(self.ref['url'],json.dumps(jobs.status(job_id)))
            audio=jobs.start_audio_reference(self.ref)
            self.assertNotEqual(audio['job_id'],job_id)
            jobs.threads[audio['job_id']].join(5)
            audio=jobs.status(audio['job_id'])
            self.assertEqual(audio['state'],'completed');self.assertEqual(audio['kind'],'complete_audio')
            self.assertEqual(audio['network_attempts'],1)
            self.assertEqual(jobs.start_audio_reference(self.ref)['job_id'],audio['job_id'])
            with self.assertRaisesRegex(ValueError,'reference_changed'):jobs.start_audio_reference({**self.ref,'url':'https://www.douyin.com/changed'})
        finally:jobs.close()

    def test_api_preview_and_explicit_server_bound_start(self):
        from dashboard import Application
        import threading
        from unittest.mock import Mock
        app=object.__new__(Application);app.lock=threading.RLock();app.root=self.root
        app.media_jobs=Mock();app._registered_run_root=Mock(return_value=self.root)
        app.run=Mock(return_value={'result':{'records':[{'kind':'content','platform':'douyin','content_id':'123'}]}})
        request={'run_id':self.run_id,'content_id':'123'}
        result=app.process_media('video_preview',request)
        self.assertEqual(result['reference_sha256'],self.ref['reference_sha256']);app.media_jobs.start_video.assert_not_called()
        for extra in ({'url':self.ref['url']},{'allow_download':False,'reference_sha256':self.ref['reference_sha256']},{'allow_download':True,'reference_sha256':'wrong'}):
            with self.assertRaises(ValueError):app.process_media('video_start',{**request,**extra})
        app.media_jobs.start_video.assert_not_called()
        app.process_media('video_start',{**request,'allow_download':True,'reference_sha256':result['reference_sha256']})
        self.assertEqual(app.media_jobs.start_video.call_count,1)
        self.assertEqual(app.media_jobs.start_video.call_args[0][0]['url'],self.ref['url'])
        for row in ({'kind':'content','platform':'weibo','content_id':'123'},{'kind':'content','platform':'douyin','content_id':'999'},{'kind':'comment','platform':'douyin','content_id':'123'}):
            app.run.return_value={'records':[row]}
            with self.assertRaisesRegex(ValueError,'identity_ambiguous'):app.process_media('video_preview',request)

    def test_loopback_video_binary_csrf_invalid_uuid_no_source(self):
        import dashboard
        import threading
        import urllib.request
        app=dashboard.Application(self.root/'http');app.owner_tasks.close();app.watchlists.close()
        app.media_jobs=MediaJobs(self.root/'video-http')
        job_id=str(uuid.uuid4());folder=app.media_jobs.root/job_id;folder.mkdir()
        data=b'isolated full video bytes';digest=hashlib.sha256(data).hexdigest()
        video.atomic_json(folder/'state.json',{'job_id':job_id,'state':'completed','kind':'complete_video','asset_sha256':digest})
        (folder/'video.mp4').write_bytes(data)
        server=dashboard.make_server(app,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();url='http://127.0.0.1:'+str(server.server_port)
        try:
            for token,selected,code in ((app.token,job_id,200),('wrong',job_id,403),(app.token,'../other',400)):
                request=urllib.request.Request(url+'/api/media-processing',data=json.dumps({'action':'video_file','payload':{'job_id':selected,'asset_sha256':digest}}).encode(),headers={'Content-Type':'application/json','Origin':url,'X-Crowd-CSRF':token})
                if code==200:
                    response=urllib.request.urlopen(request);self.assertEqual(response.headers['X-Content-SHA256'],digest);self.assertEqual(response.headers['Content-Type'],'video/mp4');self.assertEqual(response.read(),data)
                else:
                    with self.assertRaises(urllib.error.HTTPError) as caught:urllib.request.urlopen(request)
                    self.assertEqual(caught.exception.code,code)
        finally:server.shutdown();server.server_close();thread.join();app.media_jobs.close()

    def test_real_child_cancel_preserves_partial_and_no_implicit_retry(self):
        executable=self.root/'fake-slow-python'
        executable.write_text('''#!/usr/bin/env python3
import pathlib,sys,time
p=pathlib.Path(sys.argv[sys.argv.index('--reference')+1]);(p.parent/'source.part').write_bytes(b'partial download fixture');time.sleep(30)
''');executable.chmod(0o700)
        jobs=MediaJobs(self.root,python=str(executable))
        try:
            state=jobs.start_video(self.ref);job_id=state['job_id'];folder=jobs.root/job_id
            deadline=time.monotonic()+5
            while not (folder/'source.part').exists() and time.monotonic()<deadline:time.sleep(.01)
            self.assertTrue((folder/'source.part').is_file())
            jobs.cancel(job_id);jobs.threads[job_id].join(5);self.assertEqual(jobs.status(job_id)['state'],'cancelled')
            self.assertEqual((folder/'source.part').read_bytes(),b'partial download fixture')
            self.assertEqual(jobs.start_video(self.ref)['job_id'],job_id)
            self.assertEqual(len(jobs.threads),1);self.assertFalse((folder/'input-ref.json').exists())
        finally:jobs.close()


if __name__=='__main__':unittest.main()
