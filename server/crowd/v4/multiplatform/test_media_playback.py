import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from unittest.mock import patch
import dashboard
from media_jobs import MediaJobs


class PlaybackTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.jobs=MediaJobs(self.root)
        self.id='00000000-0000-4000-8000-000000000001';self.folder=self.jobs.root/self.id;self.folder.mkdir()
        self.data=b'owned local snapshot';self.sha=hashlib.sha256(self.data).hexdigest()
        self.state={'job_id':self.id,'state':'completed','kind':'asr','asset_sha256':self.sha}
        self.save();(self.folder/'input.mp4').write_bytes(self.data)
    def save(self):
        (self.folder/'state.json').write_text(json.dumps(self.state));(self.folder/'result.json').write_text('[]')
    def tearDown(self):self.jobs.close();self.temp.cleanup()
    def test_exact_frozen_snapshot_and_changed_missing_ambiguous(self):
        got=self.jobs.playback(self.id,self.sha);self.assertEqual((got['data'],got['mime'],got['sha256']),(self.data,'video/mp4',self.sha))
        with self.assertRaisesRegex(ValueError,'identity_mismatch'):self.jobs.playback(self.id,'0'*64)
        (self.folder/'input.mp4').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'snapshot_changed'):self.jobs.playback(self.id,self.sha)
        (self.folder/'input.mp4').unlink()
        with self.assertRaisesRegex(ValueError,'snapshot_missing'):self.jobs.playback(self.id,self.sha)
        for name in ['input.mp4','input.wav']:(self.folder/name).write_bytes(self.data)
        with self.assertRaisesRegex(ValueError,'snapshot_missing'):self.jobs.playback(self.id,self.sha)
    def test_symlink_corrupt_job_identity_and_non_asr_rejected(self):
        (self.folder/'input.mp4').unlink();outside=self.root/'outside.mp4';outside.write_bytes(self.data);(self.folder/'input.mp4').symlink_to(outside)
        with self.assertRaisesRegex(ValueError,'path_invalid'):self.jobs.playback(self.id,self.sha)
        (self.folder/'input.mp4').unlink();(self.folder/'input.mp4').write_bytes(self.data)
        for changes in [{'job_id':'../../outside'},{'kind':'ocr'},{'state':'running'}]:
            self.state.update(changes);self.save()
            with self.assertRaisesRegex(ValueError,'identity_mismatch'):self.jobs.playback(self.id,self.sha)
            self.state.update(job_id=self.id,kind='asr',state='completed')
    def test_actual_loopback_binary_route_csp_and_csrf(self):
        app=dashboard.Application(self.root/'http');app.owner_tasks.close();app.watchlists.close();app.media_jobs=self.jobs
        server=dashboard.make_server(app,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();url='http://127.0.0.1:'+str(server.server_port)
        try:
            with patch.object(app,'run') as run:
                page=urllib.request.urlopen(url);self.assertIn('media-src blob:',page.headers['Content-Security-Policy']);page.close()
                for token,good in [(app.token,True),('wrong',False)]:
                    req=urllib.request.Request(url+'/api/media-processing',data=json.dumps({'action':'playback','payload':{'job_id':self.id,'asset_sha256':self.sha}}).encode(),headers={'Content-Type':'application/json','Origin':url,'X-Crowd-CSRF':token})
                    if good:
                        response=urllib.request.urlopen(req);self.assertEqual(response.headers['X-Content-SHA256'],self.sha);self.assertEqual(response.headers['Content-Type'],'video/mp4');self.assertEqual(response.read(),self.data)
                    else:
                        with self.assertRaises(urllib.error.HTTPError) as caught:urllib.request.urlopen(req)
                        self.assertEqual(caught.exception.code,403)
                run.assert_not_called()
                for bad in ['not-a-uuid', None, '../outside']:
                    req=urllib.request.Request(url+'/api/media-processing',data=json.dumps({'action':'playback','payload':{'job_id':bad,'asset_sha256':self.sha}}).encode(),headers={'Content-Type':'application/json','Origin':url,'X-Crowd-CSRF':app.token})
                    with self.assertRaises(urllib.error.HTTPError) as caught:urllib.request.urlopen(req)
                    self.assertEqual(caught.exception.code,400)
                    self.assertEqual(json.load(caught.exception)['error'],'invalid_media_job_id')
        finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
