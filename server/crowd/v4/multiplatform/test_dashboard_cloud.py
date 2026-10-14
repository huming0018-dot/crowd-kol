"""Integration contracts without source access or cloud credentials."""
import json
from pathlib import Path
import tempfile
import unittest
import uuid
import threading
import urllib.request
import urllib.error
from unittest.mock import patch, MagicMock

from dashboard import Application, make_server
from results_store import ResultsStore


class CloudDashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def app(self):
        app = Application(self.root)
        self.addCleanup(lambda: make_server(app, 0).server_close())
        return app

    def test_cloud_config_selects_authoritative_adapter_not_local_scheduler(self):
        path = self.root / 'cloud-config.json'
        path.write_text('{}'); path.chmod(0o600)
        with patch('cloud_sync.CloudClient') as client, patch('cloud_sync.CloudOwnerAdapter') as adapter, \
                patch('cloud_sync.CloudWorker') as worker, patch('owner_tasks.OwnerTasks') as local:
            app = self.app()
            self.assertIs(app.owner_tasks, adapter.return_value)
            local.assert_not_called()
            self.assertEqual([call.args[1] for call in client.call_args_list], ['owner', 'worker'])
            worker.return_value.start_scheduler.assert_called_once()
            args = worker.call_args.args
            self.assertEqual(args[2], app.task_run)
            self.assertEqual(args[4], app._cloud_existing)

    def test_existing_saved_uses_exact_selected_version_without_source_requests(self):
        app = self.app()
        row = {'kind': 'content', 'platform': 'xiaohongshu', 'content_id': 'n1',
               'body': 'Saved body', 'source_kind': 'mediacrawler_api', 'reward_eligible': False,
               'origin': {'run_id': 'prior-run'}}
        store = ResultsStore(self.root)
        store.ingest({'run_id': 'prior-run', 'source_kind': 'mediacrawler_api', 'records': [row]})
        version = store.list_results()['items'][0]['version_hash']
        store.ingest({'run_id': 'later-run', 'source_kind': 'mediacrawler_api',
                      'records': [{**row, 'body': 'New version', 'origin': {'run_id': 'later-run'}}]})
        lease = {'platform': 'xhs', 'record_refs': [{'content_id': 'n1', 'version_hash': version}]}
        with patch.object(app, 'run') as run:
            records = app._cloud_existing(lease)
            self.assertEqual(records[0]['origin']['run_id'], 'prior-run')
            self.assertEqual(records[0]['body'], 'Saved body')
            run.assert_not_called()
            lease['record_refs'][0]['version_hash'] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'version_not_found'):
                app._cloud_existing(lease)

    def test_existing_saved_snapshot_passes_revision_to_exact_observation(self):
        app=self.app();store=ResultsStore(self.root)
        record={'kind':'content','platform':'xiaohongshu','content_id':'n1','body':'Same body','origin':{'run_id':'old'},'metrics':{'likes':1}}
        first=store.ingest({'run_id':'old','records':[record]})['results_revision']
        old=store.list_results()['items'][0]
        second=store.ingest({'run_id':'new','records':[{**record,'origin':{'run_id':'new'},'metrics':{'likes':2}}]})['results_revision']
        current=store.list_results()['items'][0]
        for revision,expected in ((first,old),(second,current)):
            lease={'platform':'xhs','record_refs':[{'content_id':'n1','kind':'content','version_hash':old['version_hash'],'results_revision':revision}]}
            self.assertEqual(app._cloud_existing(lease),[expected])
        for bad in (0,-1,True,1.0,second+1):
            lease['record_refs'][0]['results_revision']=bad
            with self.assertRaisesRegex(ValueError,'invalid_results_revision'):
                app._cloud_existing(lease)

    def test_cloud_status_is_public_state_without_auth_material(self):
        app = self.app()
        folder = self.root / 'worker'; folder.mkdir()
        state = folder / 'state.json'
        state.write_text(json.dumps({'phase': 'delivering', 'lease': {'run_id': 'public-run',
                                                                    'worker_key': 'private'}}))
        app.cloud_worker = MagicMock(path=state, last_error=None)
        app.cloud_worker.status.return_value = {'phase': 'delivering', 'outbox': {'pending': 1, 'acknowledged': 2}}
        value = app.cloud('status', {})
        self.assertEqual(value['storage_scope'], 'cloud')
        self.assertEqual(value['outbox']['pending'], 1)
        self.assertNotIn('private', json.dumps(value))

    def test_owner_stop_projection_matches_only_stopped_child_without_history_rewrite(self):
        app=self.app();rid=str(uuid.uuid4());run=app.runner_root/'runs'/rid;run.mkdir(parents=True)
        (run/'status.json').write_text('{"state":"stopped","reason":"user_stop","updated_at":1}')
        (run/'stop.json').write_text('{"requested_at":1}')
        original_status=(run/'status.json').read_bytes();original_marker=(run/'stop.json').read_bytes()
        value={'ok':True,'task':{'children':[{'state':'stopped','local_run_id':rid},
                                           {'state':'completed','local_run_id':rid},
                                           {'state':'stopped','local_run_id':str(uuid.uuid4())}]}}
        original=json.dumps(value,sort_keys=True);projected=app._task_stop_projection(value)
        children=projected['task']['children']
        self.assertEqual(children[0]['local_stop_reason'],'legacy_stop_requested')
        self.assertEqual(children[0]['local_stop_context']['origin'],'unknown')
        self.assertNotIn('local_stop_reason',children[1]);self.assertNotIn('local_stop_reason',children[2])
        self.assertEqual(json.dumps(value,sort_keys=True),original)
        self.assertEqual((run/'status.json').read_bytes(),original_status);self.assertEqual((run/'stop.json').read_bytes(),original_marker)

    def test_http_stop_marks_explicit_user_and_rejects_system_impersonation(self):
        app=Application(self.root);server=make_server(app,0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        url='http://127.0.0.1:'+str(server.server_port);rid=str(uuid.uuid4())
        def post(payload):
            request=urllib.request.Request(url+'/api/action',json.dumps({'action':'stop','payload':payload}).encode(),
                {'Content-Type':'application/json','Origin':url,'X-Crowd-CSRF':app.token},method='POST')
            return urllib.request.urlopen(request,timeout=5)
        try:
            with patch.object(app,'run',return_value={'ok':True,'result':{'stop_requested':True}}) as run:
                with post({'run_id':rid}) as response:self.assertTrue(json.load(response)['ok'])
                run.assert_called_once_with('stop',{'run_id':rid,'origin':'user','reason':'user_stop'})
                with self.assertRaises(urllib.error.HTTPError) as error:
                    post({'run_id':rid,'origin':'cloud_worker','reason':'cloud_controller_error','error_code':'secret_cookie_value'})
                self.assertEqual(error.exception.code,400)
                self.assertNotIn('secret_cookie_value',error.exception.read().decode());self.assertEqual(run.call_count,1)
        finally:server.shutdown();thread.join(2);server.server_close()


if __name__ == '__main__':
    unittest.main()
