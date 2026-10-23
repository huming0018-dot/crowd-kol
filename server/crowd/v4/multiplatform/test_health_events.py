import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest

from health_events import HealthEvents, safe_snapshot


class HealthEventsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = 1000
        self.events = HealthEvents(self.root, clock=lambda: self.now)
        self.addCleanup(self.events.close)

    def value(self, **changes):
        return {'phase': 'running', 'scheduler_started': True, 'scheduler_alive': True,
                'last_tick_at': self.now, 'outbox': {'pending': 1, 'acknowledged': 2}, **changes}

    def test_whitelist_never_persists_raw_input(self):
        secret = 'Cookie: session_token=https://secret.invalid/body'
        self.events.observe(self.value(last_error=secret, health_error=secret, url=secret,
                                      body=secret, headers={'Authorization': secret}, local_run_id=secret))
        text = (self.events.root / 'events.jsonl').read_text()
        self.assertNotIn(secret, text)
        self.assertEqual(self.events.status()['current']['last_error'], 'health_observation_failed')
        self.assertEqual((self.events.root / 'events.jsonl').stat().st_mode & 0o777, 0o600)

    def test_tick_times_dedup_but_failure_and_recovery_survive(self):
        self.events.observe(self.value())
        self.now += 5
        self.events.observe(self.value())
        self.assertEqual(len(self.events.status()['events']), 1)
        self.events.observe(self.value(health_error='scheduler_dead', scheduler_alive=False))
        self.now += 5
        self.events.observe(self.value())
        events = self.events.status()['events']
        self.assertEqual(len(events), 3)
        self.assertEqual(events[1]['health_error'], 'scheduler_dead')

    def test_seven_day_retention_and_capacity(self):
        self.events.max_events = 3
        for number in range(6):
            self.now += 1
            self.events.observe(self.value(outbox={'pending': number}))
        self.assertEqual(len(self.events.status()['events']), 3)
        self.now += 7*86400 + 1
        self.assertEqual(self.events.status()['events'], [])
        self.events.observe(self.value())
        self.assertEqual(len((self.events.root / 'events.jsonl').read_text().splitlines()), 1)

    def test_symlink_directory_and_file_fail_visible_without_touching_target(self):
        outside = self.root / 'outside'; outside.mkdir()
        self.events.root.symlink_to(outside, target_is_directory=True)
        self.events.observe(self.value())
        self.assertEqual(self.events.status()['monitor_error'], 'health_history_unavailable')
        self.assertFalse((outside / 'events.jsonl').exists())
        self.events.root.unlink(); self.events.root.mkdir(mode=0o700)
        target = self.root / 'secret'; target.write_text('secret')
        (self.events.root / 'events.jsonl').symlink_to(target)
        self.events.observe(self.value())
        self.assertEqual(target.read_text(), 'secret')
        self.assertEqual(self.events.error, 'health_history_unavailable')

    def test_malformed_persisted_record_fails_without_echo(self):
        self.events.observe(self.value())
        path = self.events.root / 'events.jsonl'; path.write_text('{"at": "SECRET"}')
        self.assertEqual(self.events.status()['monitor_error'], 'health_history_unavailable')
        self.assertNotIn('SECRET', json.dumps(self.events.status()))

    def test_bad_values_are_sanitized(self):
        value = safe_snapshot({'phase': {'cookie': 'private'}, 'last_tick_at': float('nan'),
                               'outbox': {'pending': True, 'acknowledged': -1}})
        self.assertEqual(value['phase'], 'state_unreadable')
        self.assertIsNone(value['last_tick_at'])
        self.assertEqual(value['pending'], 0)

    def test_huge_integer_is_rejected_and_fixed_failure_codes_survive(self):
        huge = 10**400
        value = safe_snapshot({'last_tick_at': huge, 'last_success_at': -huge,
                               'last_error': 'cloud_worker_failed', 'health_error': 'cloud_stop_persistence_failed'})
        self.assertIsNone(value['last_tick_at'])
        self.assertIsNone(value['last_success_at'])
        self.assertEqual(value['last_error'], 'cloud_worker_failed')
        self.assertEqual(value['health_error'], 'cloud_stop_persistence_failed')
        self.events.observe(self.value())
        (self.events.root/'events.jsonl').write_text(json.dumps({'at': huge}))
        self.assertEqual(self.events.status()['monitor_error'], 'health_history_unavailable')

    def test_fifo_history_does_not_block_observation_or_status(self):
        self.events.root.mkdir(mode=0o700)
        os.mkfifo(self.events.root/'events.jsonl', 0o600)
        finished = threading.Event()
        def read():
            self.events.observe(self.value())
            self.events.status()
            finished.set()
        thread = threading.Thread(target=read, daemon=True); thread.start()
        self.assertTrue(finished.wait(1), 'FIFO unexpectedly blocked health history')
        thread.join(timeout=1)
        self.assertEqual(self.events.error, 'health_history_unavailable')

    def test_background_records_error_without_ui_and_recovers(self):
        ready = threading.Event()
        count = [0]
        def source():
            count[0] += 1
            if count[0] == 1:
                raise RuntimeError('Cookie=SECRET')
            ready.set()
            return self.value()
        self.events.start(source, interval=.01)
        self.assertTrue(ready.wait(1))
        self.events.close()
        values = self.events.status()['events']
        self.assertTrue(any(row['health_error'] == 'health_observation_failed' for row in values))
        self.assertTrue(any(row['phase'] == 'running' for row in values))
        self.assertNotIn('SECRET', json.dumps(values))
        self.assertFalse(self.events.status()['monitor_alive'])

    def test_concurrent_observation_does_not_corrupt_history(self):
        threads = [threading.Thread(target=self.events.observe, args=(self.value(outbox={'pending': n}),)) for n in range(20)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertIsNone(self.events.status()['monitor_error'])
        self.assertEqual(len(self.events.status()['events']), 20)


if __name__ == '__main__':
    unittest.main()
