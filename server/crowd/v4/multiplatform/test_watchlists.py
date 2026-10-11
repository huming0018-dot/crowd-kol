import copy
import tempfile
import unittest
import uuid

from watchlists import Watchlists


class FakeOwners:
    def __init__(self):
        self.tasks, self.requests, self.resumed, self.stopped = {}, [], [], []
        self.unknown_create = False

    def create(self, request):
        self.requests.append(copy.deepcopy(request))
        if self.unknown_create:
            raise RuntimeError('response lost')
        task_id = str(uuid.uuid4())
        self.tasks[task_id] = {'task_id': task_id, 'state': 'queued', 'desired_state': 'running',
            'contents': 0, 'comments': 0, 'children': [{'state': 'queued', 'reason_code': None,
            'active_run_id': None, 'requests_spent': 0}]}
        return {'ok': True, 'task': copy.deepcopy(self.tasks[task_id])}

    def status(self, task_id):
        return {'ok': True, 'task': copy.deepcopy(self.tasks[task_id])}

    def stop(self, task_id):
        self.stopped.append(task_id)
        self.tasks[task_id].update(desired_state='stopped', state='stopped')
        self.tasks[task_id]['children'][0].update(state='stopped', active_run_id=None, reason_code='user_stop')

    def resume(self, task_id):
        self.resumed.append(task_id)
        self.tasks[task_id]['children'][0].update(state='queued', reason_code=None)

    def finish(self, task_id, contents=1, reason=None, state='completed'):
        self.tasks[task_id].update(state=state, contents=contents)
        self.tasks[task_id]['children'][0].update(state=state, reason_code=reason, active_run_id=None, requests_spent=2)


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = 1000
        self.owners = FakeOwners()
        self.service = self.make_service()

    def make_service(self):
        service = Watchlists(self.tmp.name, self.owners, clock=lambda: self.now)
        service.start_scheduler = lambda: None
        self.addCleanup(service.close)
        return service

    def payload(self, **extra):
        return {'title': '餐饮博主', 'platforms': ['wb'], 'targets_by_platform': {'wb': ['123']},
            'interval_minutes': 60, 'window_days': 3, 'total_request_budget': 25,
            'per_cycle_requests': 10, 'per_cycle_items': 2, 'purpose': 'noncommercial_research',
            'comments': True, **extra}

    def create(self, **extra):
        return self.service.create(self.payload(**extra))['watchlist']['watch_id']

    def test_create_and_dispatch_same_injected_owner(self):
        watch_id = self.create()
        self.assertEqual(self.owners.requests, [])
        self.service.poll()
        result = self.service.status(watch_id)['watchlist']
        self.assertEqual(result['state'], 'observing')
        self.assertIn(result['active_task_id'], self.owners.tasks)
        self.assertEqual(self.owners.requests[0]['mode'], 'creator')
        self.assertEqual(self.owners.requests[0]['idempotency_key'], 'watch:' + watch_id + ':1')
        self.assertEqual(result['request_budget_remaining'], 15)
        self.assertEqual(result['coverage'], 'observed_window')
        self.assertFalse(result['reward_eligible'])

    def test_preview_never_creates_task_or_schedule(self):
        preview = self.service.preview(self.payload())
        self.assertEqual(preview['source_actions_started'], 0)
        self.assertEqual(preview['watchlist']['state'], 'preview')
        self.assertEqual(preview['watchlist']['interval_minutes'], 60)
        self.assertEqual(preview['watchlist']['window_days'], 3)
        self.assertEqual(preview['watchlist']['total_request_budget'], 25)
        self.assertNotIn('task_request', preview['watchlist'])
        self.assertEqual(self.service.list()['watchlists'], [])
        self.assertEqual(self.owners.requests, [])

    def test_interval_and_budget_never_reset(self):
        watch_id = self.create()
        self.service.poll()
        first = self.service.status(watch_id)['watchlist']['active_task_id']
        self.owners.finish(first)
        self.service.poll()
        self.assertEqual(len(self.owners.requests), 1)
        self.now += 3599
        self.service.poll()
        self.assertEqual(len(self.owners.requests), 1)
        self.now += 1
        self.service.poll()
        second = self.service.status(watch_id)['watchlist']['active_task_id']
        self.owners.finish(second)
        self.service.poll()
        self.now += 3600
        self.service.poll()
        third = self.service.status(watch_id)['watchlist']['active_task_id']
        self.assertEqual([r['max_api_requests'] for r in self.owners.requests], [10, 10, 5])
        self.owners.finish(third)
        self.service.poll()
        self.now += 3600
        self.service.poll()
        state = self.service.status(watch_id)['watchlist']
        self.assertEqual(state['state'], 'budget_exhausted')
        self.assertEqual(state['requests_reserved_total'], 25)
        self.assertEqual(len(self.owners.requests), 3)

    def test_empty_or_partial_completion_is_observation_only(self):
        watch_id = self.create()
        self.service.poll()
        task_id = self.service.status(watch_id)['watchlist']['active_task_id']
        self.owners.finish(task_id, contents=0, state='waiting', reason='no_content_observed')
        self.service.poll()
        cycle = self.service.status(watch_id)['watchlist']['cycles'][0]
        self.assertEqual(cycle['state'], 'observed_only')
        self.assertEqual(cycle['contents'], 0)
        self.assertEqual(cycle['coverage'], 'observed_window')

    def test_restart_does_not_duplicate_active_cycle(self):
        watch_id = self.create()
        self.service.poll()
        restored = self.make_service()
        restored.poll()
        self.assertEqual(len(self.owners.requests), 1)
        self.assertEqual(restored.status(watch_id)['watchlist']['requests_reserved_total'], 10)

    def test_unknown_active_cycle_blocks_future_requests(self):
        watch_id = self.create()
        self.service.poll()
        task_id = self.service.status(watch_id)['watchlist']['active_task_id']
        self.owners.finish(task_id, state='unknown', reason='source_outcome_unknown')
        self.service.poll()
        self.now += 100000
        self.service.poll()
        self.assertEqual(len(self.owners.requests), 1)
        self.assertEqual(self.service.status(watch_id)['watchlist']['reason_code'], 'prior_cycle_unknown')
        self.service.stop(watch_id)
        with self.assertRaisesRegex(ValueError, 'requires_reconciliation'):
            self.service.resume(watch_id)

    def test_invalid_owner_status_is_unknown_not_empty_success(self):
        watch_id = self.create()
        self.service.poll()
        task_id = self.service.status(watch_id)['watchlist']['active_task_id']
        self.owners.tasks[task_id]['children'] = []
        self.service.poll()
        self.assertEqual(self.service.status(watch_id)['watchlist']['reason_code'], 'prior_cycle_unknown')
        self.assertEqual(len(self.owners.requests), 1)

    def test_unknown_create_is_not_replayed_after_restart(self):
        self.owners.unknown_create = True
        watch_id = self.create()
        self.service.poll()
        restored = self.make_service()
        restored.poll()
        self.assertEqual(len(self.owners.requests), 1)
        self.assertEqual(restored.status(watch_id)['watchlist']['request_budget_remaining'], 15)
        restored.stop(watch_id)
        with self.assertRaisesRegex(ValueError, 'requires_reconciliation'):
            restored.resume(watch_id)

    def test_stop_resume_new_cycle_does_not_revive_old_task(self):
        watch_id = self.create()
        self.service.poll()
        old = self.service.status(watch_id)['watchlist']['active_task_id']
        self.service.stop(watch_id)
        self.service.poll()
        self.now += 3600
        self.service.poll()
        self.assertEqual(len(self.owners.requests), 1)
        self.service.resume(watch_id)
        self.service.poll()
        self.assertEqual(len(self.owners.requests), 2)
        self.assertEqual(self.owners.resumed, [])
        self.assertEqual(self.owners.tasks[old]['desired_state'], 'stopped')
        self.assertNotEqual(self.service.status(watch_id)['watchlist']['active_task_id'], old)

    def test_manual_owner_stop_pauses_watch_and_resume_cannot_revive(self):
        watch_id = self.create()
        self.service.poll()
        task_id = self.service.status(watch_id)['watchlist']['active_task_id']
        self.owners.stop(task_id)
        self.service.poll()
        self.service.stop(watch_id)
        with self.assertRaisesRegex(ValueError, 'owner_task_stopped'):
            self.service.resume(watch_id)
        self.assertEqual(len(self.owners.requests), 1)

    def test_login_requires_explicit_resume_with_same_cycle_budget(self):
        watch_id = self.create()
        self.service.poll()
        task_id = self.service.status(watch_id)['watchlist']['active_task_id']
        self.owners.finish(task_id, contents=0, state='waiting', reason='login_required')
        self.service.poll()
        self.assertEqual(self.service.status(watch_id)['watchlist']['reason_code'], 'prior_cycle_requires_action')
        self.service.resume(watch_id)
        self.assertEqual(self.owners.resumed, [task_id])
        self.service.poll()
        self.assertEqual(len(self.owners.requests), 1)
        self.assertEqual(self.service.status(watch_id)['watchlist']['requests_reserved_total'], 10)

    def test_validation_and_overlap(self):
        invalid = [{'window_days': 2}, {'interval_minutes': True}, {'per_cycle_items': 0},
            {'per_cycle_requests': True}, {'total_request_budget': 3}, {'unknown': 1},
            {'title': 'Cookie=private'}, {'platforms': ['wb', 'wb']}]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.create(**value)
        with self.assertRaisesRegex(ValueError, 'invalid_watchlist_id'):
            self.service.status('bad-id')

    def test_watch_create_idempotency(self):
        first = self.create(idempotency_key='creation-1')
        self.assertEqual(first, self.create(idempotency_key='creation-1'))
        with self.assertRaisesRegex(ValueError, 'idempotency_conflict'):
            self.create(idempotency_key='creation-1', title='changed')
        self.assertEqual(len(self.service.list()['watchlists']), 1)

    def test_private_navigation_locator_not_in_public_state(self):
        watch_id = self.create(platforms=['xhs'], targets_by_platform={'xhs': ['https://www.xiaohongshu.com/user/profile/0123456789abcdef01234567?xsec_token=private_locator']})
        public = self.service.status(watch_id)['watchlist']
        self.assertNotIn('private_locator', str(public))
        self.assertNotIn('xsec_token', str(public))
        self.assertTrue(public['navigation_locators_omitted'])
        self.assertEqual(public['targets_by_platform']['xhs'][0], 'https://www.xiaohongshu.com/user/profile/0123456789abcdef01234567')

    def test_structural_wait_does_not_repeat_every_cycle(self):
        watch_id = self.create()
        self.service.poll()
        task_id = self.service.status(watch_id)['watchlist']['active_task_id']
        self.owners.finish(task_id, state='waiting', reason='media_not_supported_by_upstream')
        self.service.poll()
        self.now += 100000
        self.service.poll()
        self.assertEqual(len(self.owners.requests), 1)
        self.assertEqual(self.service.status(watch_id)['watchlist']['reason_code'], 'prior_cycle_requires_action')


if __name__ == '__main__':
    unittest.main()
