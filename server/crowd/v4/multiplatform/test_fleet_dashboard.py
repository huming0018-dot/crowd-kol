import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import uuid

from cloud_sync import CloudError, CloudWorker
from dashboard import Application
from health_events import HealthEvents
from test_cloud_sync import FakeCloud, lease, row


class FleetDashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = Application(Path(self.temp.name))
        self.addCleanup(self.app.watchlists.close)
        self.addCleanup(self.app.owner_tasks.close)
        self.addCleanup(self.app.health_events.close)

    def test_fleet_read_only_payload_and_schema_gate(self):
        self.app.cloud_client = Mock()
        for action, schema in [('unified_status', 'crowd-unified-status-v1'), ('node_events', 'crowd-node-events-v1')]:
            self.app.cloud_client.call.return_value = {'schema': schema, 'events': [], 'tasks': []}
            self.assertTrue(self.app.cloud(action, {})['available'])
            self.app.cloud_client.call.assert_called_with(action, {})
            for payload in [{'node_key': 'SECRET'}, {'limit': True}, {'limit': -1}, {'limit': 201}]:
                with self.assertRaises(ValueError): self.app.cloud(action, payload)
            self.app.cloud_client.call.return_value = {'ok': True}
            value = self.app.cloud(action, {})
            self.assertFalse(value['available'])
            self.assertEqual(value['reason'], 'upgrade_required')
            self.app.cloud_client.call.side_effect = CloudError('invalid_action')
            self.assertEqual(self.app.cloud(action, {})['reason'], 'upgrade_required')
            self.app.cloud_client.call.side_effect = CloudError('principal_denied')
            self.assertEqual(self.app.cloud(action, {})['reason'], 'upgrade_or_access_required')
            self.app.cloud_client.call.side_effect = CloudError('cloud_read_unavailable')
            with self.assertRaises(CloudError): self.app.cloud(action, {})
            self.app.cloud_client.call.side_effect = None

    def test_unified_dispatch_actions_are_separate_from_legacy_and_fail_unknown_closed(self):
        self.app.cloud_client = Mock()
        key = str(uuid.uuid4())
        payload = {'idempotency_key': key, 'platforms': ['xhs', 'bili'], 'mode': 'search',
                   'targets': ['上海美食'], 'desired_items': 40, 'purpose': 'noncommercial_research'}
        self.app.cloud_client.call.return_value = {'schema': 'crowd-unified-dispatch-v1', 'ready': True, 'routes': []}
        for action in ['unified_preview', 'unified_create']:
            self.assertTrue(self.app.cloud(action, payload)['available'])
            self.app.cloud_client.call.assert_called_with(action, payload)
            with self.assertRaises(ValueError): self.app.cloud(action, {**payload, 'routing': 'manual'})
        self.app.cloud_client.call.return_value = {'schema': 'old-cloud'}
        with self.assertRaisesRegex(CloudError, 'cloud_outcome_unknown'):
            self.app.cloud('unified_create', payload)
        with self.assertRaisesRegex(CloudError, 'cloud_read_unavailable'):
            self.app.cloud('unified_preview', payload)
        self.app.cloud_client.call.side_effect = CloudError('cloud_outcome_unknown')
        with self.assertRaisesRegex(CloudError, 'cloud_outcome_unknown'):
            self.app.cloud('unified_create', payload)
        self.app.cloud_client.call.assert_called_with('unified_create', payload)

    def test_dispatch_lookup_exact_key_and_backend_upgrade_no_fallback(self):
        self.app.cloud_client = Mock()
        self.app.cloud_client.call.return_value = {'schema': 'crowd-unified-dispatch-list-v1', 'dispatches': []}
        for payload in [{}, {'idempotency_key': 'original-key'}]:
            self.assertTrue(self.app.cloud('unified_dispatches', payload)['available'])
            self.app.cloud_client.call.assert_called_with('unified_dispatches', payload)
        for payload in [{'idempotency_key': ''}, {'idempotency_key': True}, {'idempotency_key': 'secret\n'}, {'limit': 100}, {'task_id': 'bad'}]:
            with self.assertRaises(ValueError): self.app.cloud('unified_dispatches', payload)
        self.app.cloud_client.call.side_effect = CloudError('invalid_action')
        value = self.app.cloud('unified_preview', {'idempotency_key': 'a'})
        self.assertFalse(value['available'])
        self.assertEqual(value['reason'], 'upgrade_or_access_required')
        self.app.cloud_client = None
        self.assertEqual(self.app.cloud('unified_preview', {'idempotency_key': 'a'})['reason'], 'not_connected')

    def test_node_cursor_and_identity_validation(self):
        for value in [True, -1, 2**53, '0', 1.5]:
            with self.assertRaises(ValueError): self.app.cloud('node_events', {'after_id': value})
        for value in [None, '', 'Cookie SECRET', [], True]:
            with self.assertRaises(ValueError): self.app.cloud('node_events', {'installation_id': value})
        self.assertFalse(self.app.cloud('node_events', {'after_id': 0, 'installation_id': str(uuid.uuid4())})['available'])
        with self.assertRaises(ValueError): self.app.cloud('unified_status', {'after_id': 0})

    def test_local_mode_never_claims_connected(self):
        self.assertEqual(self.app.cloud('workflow_events', {})['coverage'], 'not_connected')
        self.assertEqual(self.app.cloud('unified_status', {})['reason'], 'not_connected')

    def test_fast_phases_survive_and_do_not_log_source_or_session(self):
        cloud = FakeCloud()
        local_id = str(uuid.uuid4())
        def runner(action, payload):
            return {'result': {'start': {'run_id': local_id}, 'status': {'state': 'completed', 'api_attempts': 1}, 'import': {'records': [row()]}}[action]}
        worker = CloudWorker(self.temp.name, cloud, runner)
        worker.tick()
        self.app.cloud_worker = worker
        value = self.app.cloud('workflow_events', {})
        phases = [event['phase'] for event in reversed(value['events'])]
        for phase in ['claiming', 'authorized', 'dispatching', 'running', 'importing', 'delivering', 'finishing', 'completed']:
            self.assertIn(phase, phases)
        correlated = [event for event in value['events'] if event['task_id']]
        self.assertTrue(correlated)
        self.assertEqual(correlated[0]['task_id'], cloud.lease['task_id'])
        self.assertNotIn('0123456789abcdef01234567', json.dumps(value))
        self.assertNotIn('session_id', json.dumps(value))
        before = value['event_count']
        reopened = CloudWorker(self.temp.name, cloud, runner)
        self.assertEqual(reopened.workflow_events.status()['event_count'], before)

    def test_broken_telemetry_does_not_discard_result_or_prevent_ack(self):
        cloud = FakeCloud()
        worker = CloudWorker(self.temp.name, cloud, lambda *_: None)
        worker.workflow_events.root.mkdir(mode=0o700)
        (worker.workflow_events.root / 'events.jsonl').write_text('unreadable')
        (worker.workflow_events.root / 'events.jsonl').chmod(0o600)
        worker.outbox.stage_imported({'records': [row()]}, cloud.lease)
        worker._save({'phase': 'delivering', 'lease': cloud.lease, 'outcome': 'completed', 'api_attempts': 1})
        self.assertEqual(worker.tick()['state'], 'finished')
        self.assertEqual(worker.outbox.stats()['acknowledged'], 1)
        self.assertEqual(worker.status()['workflow_monitor_error'], 'health_history_unavailable')

    def test_sequence_is_durable_monotonic_and_gap_visible_after_pruning(self):
        now = [1000]
        events = HealthEvents(self.temp.name, clock=lambda: now[0], workflow=True, max_events=3)
        for i in range(5):
            now[0] += 1
            events.observe({'phase': 'running', 'outbox': {'pending': i}})
        value = events.status()
        self.assertEqual([event['seq'] for event in value['events']], [5, 4, 3])
        self.assertTrue(value['truncated'])
        reopened = HealthEvents(self.temp.name, clock=lambda: now[0], workflow=True, max_events=3)
        now[0] += 8 * 86400
        reopened.observe({'phase': 'idle'})
        self.assertEqual(reopened.status()['events'][0]['seq'], 6)
        self.assertTrue(reopened.status()['truncated'])

    def test_empty_claim_poll_does_not_evict_real_history(self):
        cloud = Mock()
        cloud.call.return_value = {'lease': None}
        worker = CloudWorker(self.temp.name, cloud, lambda *_: None)
        for _ in range(10): worker.tick()
        self.assertEqual(worker.workflow_events.status()['event_count'], 1)


if __name__ == '__main__':
    unittest.main()
