"""Isolated controller failures: no platform access or production state."""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from cloud_sync import CloudWorker
import mc_runner
from test_cloud_sync import FakeCloud, uid


class SchedulerHealthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cloud = FakeCloud()
        self.cloud.call = lambda action, payload=None: {'lease': None}
        self.actions = []
        self.worker = CloudWorker(Path(self.temp.name), self.cloud,
            lambda action, payload: self.actions.append(action), interval=.02)

    def tearDown(self):
        self.worker.close()
        self.temp.cleanup()

    def wait_for(self, condition):
        deadline = time.monotonic() + 2
        while not condition() and time.monotonic() < deadline:
            time.sleep(.005)
        self.assertTrue(condition())

    def test_missing_lock_does_not_kill_scheduler_or_recreate_lock(self):
        self.worker.lock_path.unlink()
        self.worker.start_scheduler()
        self.wait_for(lambda: self.worker.last_error == 'cloud_lock_unavailable')
        status = self.worker.status()
        self.assertTrue(status['scheduler_alive'])
        self.assertEqual(status['health_error'], 'cloud_lock_unavailable')
        self.assertIsNone(status['last_success_at'])
        self.assertFalse(self.worker.lock_path.exists())
        self.assertEqual(self.actions, [])

    def test_permission_error_is_safe_and_never_dispatches(self):
        with patch('cloud_sync.open', side_effect=PermissionError('Cookie=secret; /private/path')):
            self.assertEqual(self.worker.tick()['error'], 'cloud_lock_unavailable')
        self.assertNotIn('secret', json.dumps(self.worker.status()))
        self.assertEqual(self.actions, [])

    def test_symlink_lock_is_refused(self):
        self.worker.lock_path.unlink()
        target = Path(self.temp.name) / 'other.lock'
        target.write_text('')
        self.worker.lock_path.symlink_to(target)
        self.assertEqual(self.worker.tick()['error'], 'cloud_lock_unavailable')
        self.assertEqual(self.actions, [])

    def test_postprocessing_failures_stay_pending_and_visible(self):
        run_id = uid()
        self.worker._save({'phase': 'idle', 'postprocessing_runs': [run_id]})
        def fail(action, payload):
            raise RuntimeError('token=private')
        self.worker.postprocessing_callback = fail
        self.assertEqual(self.worker.tick()['state'], 'idle')
        self.assertEqual(self.worker.status()['postprocessing_error'], 'postprocessing_enqueue_failed')
        self.assertEqual(mc_runner.read(self.worker.path)['postprocessing_runs'], [run_id])
        self.assertNotIn('private', json.dumps(self.worker.status()))
        self.worker.postprocessing_callback = lambda action, payload: None
        self.worker.tick()
        self.assertIsNone(self.worker.status()['postprocessing_error'])
        self.assertEqual(mc_runner.read(self.worker.path)['postprocessing_runs'], [])

    def test_dead_thread_visible_restart_is_serial_and_preserves_unknown(self):
        self.worker._save({'phase': 'dispatching', 'local_run_id': uid()})
        before = self.worker.path.read_bytes()
        self.worker.thread = threading.Thread(target=lambda: None)
        self.worker.thread.start()
        self.worker.thread.join()
        self.worker.scheduler_started = True
        self.assertEqual(self.worker.status()['health_error'], 'scheduler_dead')
        starters = [threading.Thread(target=self.worker.start_scheduler) for _ in range(8)]
        for thread in starters: thread.start()
        for thread in starters: thread.join()
        self.wait_for(lambda: self.worker.last_error == 'source_outcome_unknown')
        self.assertTrue(self.worker.status()['scheduler_alive'])
        self.assertEqual(mc_runner.read(self.worker.path)['phase'], 'dispatching')
        self.assertEqual(self.actions, [])
        self.assertEqual(json.loads(before)['local_run_id'], mc_runner.read(self.worker.path)['local_run_id'])

    def test_stalled_thread_is_visible_without_duplicate_restart(self):
        started, release = threading.Event(), threading.Event()
        def blocked():
            started.set()
            release.wait(2)
            return {'state': 'idle'}
        with patch.object(self.worker, 'tick', side_effect=blocked):
            self.worker.start_scheduler()
            self.assertTrue(started.wait(1))
            first = self.worker.thread
            self.worker._last_tick_monotonic = time.monotonic() - 31
            self.assertEqual(self.worker.status()['health_error'], 'scheduler_stale')
            self.worker.start_scheduler()
            self.assertIs(self.worker.thread, first)
            release.set()

    def test_uncaught_loop_error_is_visible_and_no_secret_trace(self):
        with patch.object(self.worker, 'tick', side_effect=RuntimeError('token=secret')):
            self.worker.start_scheduler()
            self.worker.thread.join(1)
        status = self.worker.status()
        self.assertFalse(status['scheduler_alive'])
        self.assertEqual(status['health_error'], 'cloud_scheduler_failed')
        self.assertNotIn('secret', json.dumps(status))

    def test_unexpected_active_controller_error_stops_exact_run_only(self):
        lease = FakeCloud().lease
        run_id = uid()
        self.worker.runner = lambda action, payload: self.actions.append((action, payload)) or {'stop_requested': True}
        self.worker._save({'phase': 'running', 'local_run_id': run_id, 'lease': lease})
        with patch.object(self.worker, '_tick', side_effect=RuntimeError('secret')):
            self.assertEqual(self.worker.tick()['error'], 'cloud_worker_failed')
        self.assertEqual(len(self.actions), 1)
        self.assertEqual(self.actions[0][0], 'stop')
        self.assertEqual(self.actions[0][1]['run_id'], run_id)
        self.assertNotIn('secret', json.dumps(self.worker.status()))
        self.worker._save({'phase': 'local_stop_unknown', 'local_run_id': run_id, 'lease': lease})

    def test_start_failure_is_visible_and_close_is_safe(self):
        with patch('cloud_sync.threading.Thread.start', side_effect=RuntimeError('private')):
            self.worker.start_scheduler()
        self.assertIsNone(self.worker.thread)
        self.assertEqual(self.worker.status()['health_error'], 'cloud_scheduler_failed')
        self.worker.close()

    def test_success_and_close_do_not_report_death_or_restart(self):
        self.worker.start_scheduler()
        self.wait_for(lambda: self.worker.last_success_at is not None)
        self.worker.close()
        status = self.worker.status()
        self.assertTrue(status['scheduler_closed'])
        self.assertFalse(status['stale'])
        self.assertIsNone(status['health_error'])
        first = self.worker.thread
        self.worker.start_scheduler()
        self.assertIs(self.worker.thread, first)


if __name__ == '__main__':
    unittest.main()
