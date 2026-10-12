import threading
import unittest
import json
import urllib.error
import urllib.request

from dashboard import Application, make_server
from test_transcript_artifact import TranscriptCloud


class TranscriptCaller(unittest.TestCase):
    def setUp(self):
        self.fixture = TranscriptCloud()
        self.fixture.setUp()
        self.app = Application.__new__(Application)
        self.app.root = self.fixture.root
        self.app.lock = threading.Lock()
        self.app.media_jobs = self.fixture.jobs
        self.app.cloud_client = self.fixture.client
        self.app.analysis_jobs=None
        self.app.media_jobs.close=lambda:None
        self.app.owner_tasks=type('NoTasks',(),{'close':lambda self:None})()
        self.app.watchlists=type('NoWatchlists',(),{'close':lambda self:None})()
        self.app.cloud_worker=None

    def tearDown(self):
        self.fixture.tearDown()

    def test_normal_status_save_get_job_id_only_no_model(self):
        payload={'job_id':self.fixture.job}
        self.assertEqual(self.app.process_media('transcript_cloud_status',payload)['status'],'not_saved')
        self.assertEqual(self.app.process_media('transcript_cloud_save',payload)['receipt']['artifact_kind'],'transcript_report')
        value=self.app.process_media('transcript_cloud_get',payload)
        self.assertEqual(value['report']['segment_count'],2)
        self.assertEqual(value['source_requests'],0)
        self.assertEqual(value['model_calls'],0)
        self.assertEqual(self.fixture.calls.count('transcript_put'),1)

    def test_extra_path_or_report_body_rejected_before_cloud(self):
        for action in ('transcript_cloud_status','transcript_cloud_save','transcript_cloud_get'):
            for payload in ({'job_id':self.fixture.job,'path':'outside'},{'job_id':self.fixture.job,'report_json':'fake'},{}):
                with self.assertRaisesRegex(ValueError,'invalid_transcript_cloud_request'):
                    self.app.process_media(action,payload)
        self.assertEqual(self.fixture.calls,[])

    def test_cloud_not_configured_and_invalid_job_rejected(self):
        self.app.cloud_client=None
        with self.assertRaisesRegex(ValueError,'cloud_configuration_required'):
            self.app.process_media('transcript_cloud_save',{'job_id':self.fixture.job})
        with self.assertRaisesRegex(ValueError,'invalid_media_job_id'):
            self.app.process_media('transcript_cloud_save',{'job_id':'../../outside'})
        self.assertEqual(self.fixture.calls,[])

    def test_actual_loopback_malformed_id_all_actions_400_no_cloud(self):
        self.app.token='offline-CSRF'
        self.app.close=lambda:None
        server=make_server(self.app,0)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        url='http://127.0.0.1:'+str(server.server_port)
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            for action in ('transcript_cloud_status','transcript_cloud_save','transcript_cloud_get'):
                for identity in ('invalidUUID',None,True,{}):
                    request=urllib.request.Request(url+'/api/media-processing',data=json.dumps({'action':action,'payload':{'job_id':identity}}).encode(),headers={'Content-Type':'application/json','Origin':url,'X-Crowd-CSRF':self.app.token})
                    with self.assertRaises(urllib.error.HTTPError) as caught:opener.open(request,timeout=2)
                    self.assertEqual(caught.exception.code,400)
                    self.assertEqual(json.load(caught.exception)['error'],'invalid_media_job_id')
            self.assertEqual(self.fixture.calls,[])
        finally:
            server.shutdown();server.server_close();thread.join()


if __name__=='__main__':
    unittest.main()
