import base64
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

import dashboard
from media_jobs import MediaJobs


class UnifiedDashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = dashboard.Application(Path(self.temp.name) / 'runtime')
        self.app.owner_tasks.close()
        self.app.owner_tasks._ensure_thread = lambda: None
        self.server = dashboard.make_server(self.app, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.temp.cleanup()

    def post(self, path, action, payload):
        request = urllib.request.Request(self.url + path, data=json.dumps({'action':action,'payload':payload}).encode(),
            headers={'Content-Type':'application/json','Origin':self.url,'X-Crowd-CSRF':self.app.token})
        return urllib.request.urlopen(request)

    def test_owner_preview_routing_and_idempotent_same_http_task(self):
        with patch.object(self.app, 'run') as runner:
            batch = json.load(self.post('/api/tasks','parse_batch',{'mode':'detail','text':'https://weibo.com/123/AbC\nabc'}))
            self.assertTrue(batch['ok']); self.assertFalse(batch['valid']); self.assertEqual(batch['errors'][0]['line'],2)
            payload = {'platforms':['xhs','wb'],'mode':'detail','targets_by_platform':{'wb':['123']},
                       'desired_items':2,'max_api_requests':4,'purpose':'noncommercial_research','idempotency_key':'http-test'}
            value=json.load(self.post('/api/tasks','preview',payload))
            self.assertEqual(value['children'][0]['reason_code'],'missing_targets')
            first=json.load(self.post('/api/tasks','create',payload))['task']
            second=json.load(self.post('/api/tasks','create',payload))['task']
            self.assertEqual(first['task_id'],second['task_id'])
            self.assertEqual(json.load(self.post('/api/tasks','stop',{'task_id':first['task_id']}))['task']['state'],'stopped')
            runner.assert_not_called()

    def test_results_http_ingest_evaluate_csv_manifest_and_revision(self):
        imported={'run_id':'00000000-0000-4000-8000-000000000044','records':[
            {'kind':'content','platform':'weibo','content_id':'123','title':'=1+1','body':'保存的正文','author_id':'author','published_at_reported':1700000000},
            {'kind':'comment','platform':'weibo','content_id':'123','comment_id':'c1','parent_comment_id':'0','text':'评论'}]}
        with patch.object(self.app,'run',return_value={'ok':True,'result':imported}) as runner:
            revision=json.load(self.post('/api/results','ingest',{'run_id':imported['run_id']}))['results_revision']
            saved=json.load(self.post('/api/results','evaluate',{'platform':'wb','content_id':'123','revision':revision,'value':4,'tags':['待研究']}))
            self.assertFalse(saved['reward_eligible'])
            rows=json.load(self.post('/api/results','list',{'filters':{'tags':['待研究']}}))
            self.assertEqual(rows['total'],1)
            response=self.post('/api/results','export',{'format':'csv','revision':revision})
            csv=response.read(); manifest=json.loads(base64.urlsafe_b64decode(response.headers['X-Crowd-Export-Manifest']))
            self.assertEqual(manifest['row_count'],2)
            self.assertEqual(hashlib.sha256(csv).hexdigest(),response.headers['X-Content-SHA256'])
            self.assertIn("'=1+1",csv.decode('utf-8-sig'))
            self.assertEqual(runner.call_count,1)

    def test_routes_reject_unknown_missing_and_invalid_ids(self):
        cases=[('/api/tasks','status',{'task_id':'invalid'}),('/api/results','detail',{}),
               ('/api/results','list',{'unknown':True}),('/api/media-processing','status',{'job_id':'invalid'})]
        for path,action,payload in cases:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.post(path,action,payload)
            self.assertEqual(caught.exception.code,400)
            self.assertFalse(json.load(caught.exception)['ok'])

    def test_parent_import_does_not_hide_library_failure(self):
        imported = {'records': [], 'local_results_error': 'results_store_write_failed'}
        with patch.object(self.app, 'run', return_value={'ok': True, 'result': imported}):
            response = self.app.task_run('import', {'run_id': 'saved-run'})
        self.assertFalse(response['ok'])
        self.assertEqual(response['error'], 'local_results_persistence_failed')
        with patch.object(self.app, 'run', return_value={'ok': True, 'result': {'records': []}}):
            self.assertTrue(self.app.task_run('import', {'run_id': 'saved-run'})['ok'])

    def test_media_rejects_cross_content_and_paths(self):
        run_id='00000000-0000-4000-8000-000000000055'
        folder=self.app.runner_root/'runs'/run_id/'output';folder.mkdir(parents=True);(folder/'image.png').write_bytes(b'not-image')
        imported={'media':[{'path':'output/image.png'}],'records':[{'kind':'content','platform':'weibo','content_id':'123'}]}
        with patch.object(self.app,'run',return_value={'ok':True,'result':imported}):
            for path,cid in [('output/image.png','other'),('../../private','123')]:
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    self.post('/api/media-processing','start',{'run_id':run_id,'path':path,'content_id':cid,'kind':'ocr'})
                self.assertEqual(caught.exception.code,400)
        self.assertFalse(list((self.app.root/'media-processing').glob('*/state.json')))


class MediaJobsTests(unittest.TestCase):
    def test_real_local_transcript_saved_cached_and_original_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'source.vtt';source.write_text('WEBVTT\n\n00:00.000 --> 00:01.000\n已有字幕\n')
            before=hashlib.sha256(source.read_bytes()).hexdigest(); jobs=MediaJobs(temp)
            state=jobs.start(source,'weibo','123','transcript','00000000-0000-4000-8000-000000000001')
            deadline=time.monotonic()+5
            while jobs.status(state['job_id'])['state'] not in ('completed','failed') and time.monotonic()<deadline:
                time.sleep(.01)
            result=jobs.status(state['job_id'])
            self.assertEqual(result['state'],'completed')
            self.assertEqual(result['result'][0]['evidence']['raw_text'],source.read_text())
            self.assertTrue(jobs.start(source,'weibo','123','transcript','other')['cached'])
            self.assertEqual(before,hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertFalse(list((jobs.root/state['job_id']).glob('input*')))
            self.assertEqual((jobs.root/state['job_id']/'result.json').stat().st_mode&0o777,0o600)
            jobs.close()

    def test_unconfigured_asr_and_restart_unknown_not_false_success(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'source.wav';source.write_bytes(b'audio');jobs=MediaJobs(temp)
            with self.assertRaisesRegex(ValueError,'local_asr_model_not_configured'):
                jobs.start(source,'weibo','123','asr','run')
            job_id='00000000-0000-4000-8000-000000000099';folder=jobs.root/job_id;folder.mkdir()
            (folder/'state.json').write_text(json.dumps({'state':'running','job_id':job_id}))
            self.assertEqual(jobs.status(job_id)['state'],'interrupted_unknown')
            with self.assertRaisesRegex(ValueError,'invalid_media_job_id'):jobs.status('bad')
            jobs.close()


if __name__ == '__main__':
    unittest.main()
