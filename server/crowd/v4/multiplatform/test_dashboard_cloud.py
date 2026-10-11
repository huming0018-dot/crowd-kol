"""Integration contracts without source access or cloud credentials."""
import json
from pathlib import Path
import tempfile
import unittest
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


if __name__ == '__main__':
    unittest.main()
