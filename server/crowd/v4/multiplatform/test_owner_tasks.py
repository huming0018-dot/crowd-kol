import json
from pathlib import Path
import tempfile
import time
import threading
import unittest
from unittest.mock import patch
import uuid

from owner_tasks import OwnerTasks, parse_batch, plan


class OwnerTaskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.calls = []
        self.responses = {}
        def runner(action, payload):
            self.calls.append((action, payload))
            if action == 'start':
                run_id = str(uuid.uuid4())
                self.responses[run_id] = {'state': 'running'}
                return {'ok': True, 'result': {'run_id': run_id, 'state': 'starting'}}
            if action == 'status':
                return {'ok': True, 'result': self.responses[payload['run_id']]}
            if action == 'import':
                return {'ok': True, 'result': {'records': self.responses[payload['run_id']].get('records', [])}}
            return {'ok': True, 'result': {'stop_requested': True}}
        self.service = OwnerTasks(self.temp.name, runner, interval=100)
        self.service._ensure_thread = lambda: None

    def tearDown(self):
        self.service.close()
        self.temp.cleanup()

    def request(self, **changes):
        return {'platforms': ['xhs', 'wb'], 'mode': 'detail',
                'targets_by_platform': {'xhs': ['66fad51c000000001b0224b8'], 'wb': ['123']},
                'desired_items': 2, 'max_api_requests': 6,
                'purpose': 'noncommercial_research', 'idempotency_key': 'fixture', **changes}

    def create(self, **changes):
        return self.service.create(self.request(**changes))['task']

    def test_preview_platform_targets_and_total_not_multiplied(self):
        result = self.service.preview(self.request(desired_items=5, max_api_requests=7))
        self.assertEqual([c['item_quota'] for c in result['children']], [3, 2])
        self.assertEqual([c['request_quota'] for c in result['children']], [4, 3])
        self.assertFalse(self.calls)
        self.assertEqual(result['storage_scope'], 'local_only')
        missing = self.service.preview(self.request(targets_by_platform={'xhs': ['66fad51c000000001b0224b8']}))
        self.assertEqual(missing['children'][1]['reason_code'], 'missing_targets')

    def test_long_audio_options_reach_bili_and_reject_other_scope(self):
        req = self.request(platforms=['bili'], targets_by_platform={'bili': ['BV1234567890']},
                           media=True, platform_options_by_platform={'bili': {'long_audio': True}})
        child = plan(req)['children'][0]
        self.assertEqual(child['request']['platform_options'], {'long_audio': True})
        for options in ({'bili': {'long_audio': 'true'}}, {'wb': {'long_audio': True}},
                        {'bili': {'long_audio': True, 'cookie': 'secret'}}):
            with self.assertRaises(ValueError):
                plan({**req, 'platform_options_by_platform': options})
        with self.assertRaises(ValueError):
            plan({**req, 'media': False})

    def test_transcript_only_bili_douyin_multi_platform_preflight(self):
        options={'bili':{'transcript_only':True,'long_audio':True},'dy':{'transcript_only':True}}
        req=self.request(platforms=['bili','dy'],targets_by_platform={'bili':['BV1234567890'],'dy':['123']},media=True,platform_options_by_platform=options)
        children=plan(req)['children']
        self.assertEqual([child['request']['platform_options'] for child in children],[options['bili'],options['dy']])
        self.assertEqual(plan({**req,'platforms':['dy'],'targets_by_platform':{'dy':['123']},'platform_options_by_platform':{'dy':options['dy']}})['children'][0]['request']['platform_options'],options['dy'])
        self.assertEqual(len(plan({**req,'platforms':['bili','wb'],'targets_by_platform':{'bili':['BV1234567890'],'wb':['123']},'platform_options_by_platform':{'bili':options['bili'],'wb':{'transcript_only':True}}})['children']),2)

    def test_idempotency_persistence_and_conflict(self):
        first = self.create()
        self.assertEqual(first['task_id'], self.create()['task_id'])
        with self.assertRaisesRegex(ValueError, 'idempotency_conflict'):
            self.create(desired_items=3)
        reopened = OwnerTasks(self.temp.name, lambda *_: None)
        self.assertEqual(len(reopened.list()['tasks']), 1)
        self.assertEqual(reopened.status(first['task_id'])['task']['state'], 'queued')
        reopened.close()
        self.assertEqual(self.service.path.stat().st_mode & 0o777, 0o600)

    def test_sequential_runner_automatic_allocation_and_import(self):
        task = self.create()
        self.service.poll()
        child = self.service.status(task['task_id'])['task']['children'][0]
        self.service.poll()
        self.assertEqual(sum(a == 'start' for a, _ in self.calls), 1)
        self.responses[child['active_run_id']] = {'state': 'completed', 'api_attempts': 1,
            'records': [{'kind': 'content', 'platform': 'xiaohongshu', 'content_id': '66fad51c000000001b0224b8', 'text': 'body'}]}
        self.service.poll()
        current = self.service.status(task['task_id'])['task']
        self.assertEqual(current['children'][0]['state'], 'completed')
        self.assertEqual(current['contents'], 1)
        self.assertEqual(current['delivery_state'], 'local_only')
        self.assertEqual(sum(a == 'start' for a, _ in self.calls), 2)
        second = current['children'][1]
        self.responses[second['active_run_id']] = {'state': 'failed', 'reason': 'executor_error', 'api_attempts': 3}
        self.service.poll()
        self.assertEqual(self.service.status(task['task_id'])['task']['state'], 'partial')

    def test_search_small_quota_never_inflated_and_shared_targets(self):
        request = self.request(mode='search', targets=['烧鸟'], desired_items=20)
        request.pop('targets_by_platform')
        task = self.service.create(request)['task']
        self.service.poll()
        current = self.service.status(task['task_id'])['task']
        self.assertEqual(current['state'], 'waiting')
        self.assertTrue(all(c['reason_code'] == 'upstream_search_minimum_20' for c in current['children']))
        self.assertFalse(self.calls)

    def test_unknown_dispatch_never_retried_after_restart_or_resume(self):
        self.service.runner = lambda *_: {'ok': False, 'error': 'runner_response_timeout_check_runs_before_retry'}
        task = self.create()
        self.service.poll()
        current = self.service.status(task['task_id'])['task']
        self.assertEqual(current['children'][0]['state'], 'unknown')
        self.service.resume(task['task_id'])
        self.service.poll()
        current = self.service.status(task['task_id'])['task']
        self.assertEqual(current['children'][0]['requests_reserved'], 3)
        self.assertEqual(current['children'][0]['state'], 'unknown')

    def test_stop_does_not_drop_results_and_resume_keeps_budget(self):
        task = self.create()
        self.service.poll()
        child = self.service.status(task['task_id'])['task']['children'][0]
        self.service.stop(task['task_id'])
        self.service.poll()
        self.assertTrue(any(a == 'stop' for a, _ in self.calls))
        self.responses[child['active_run_id']] = {'state': 'stopped', 'api_attempts': 3,
            'records': [{'kind': 'content', 'platform': 'xiaohongshu', 'content_id': '66fad51c000000001b0224b8', 'text': 'saved'}]}
        self.service.poll()
        current = self.service.status(task['task_id'])['task']
        self.assertEqual(current['contents'], 1)
        self.assertEqual(current['state'], 'stopped')
        self.service.resume(task['task_id'])
        self.assertEqual(self.service.status(task['task_id'])['task']['children'][0]['requests_spent'], 3)

    def test_system_or_legacy_stopped_child_is_not_reported_as_owner_stop(self):
        for reason in ('cloud_controller_error','cloud_dispatch_denied','cloud_worker_shutdown','legacy_stop_requested','user_stop'):
            with self.subTest(reason=reason):
                task=self.create(platforms=['xhs'],targets_by_platform={'xhs':['66fad51c000000001b0224b8']},desired_items=1,max_api_requests=3,idempotency_key='systemstop-'+reason);self.service.poll()
                child=self.service.status(task['task_id'])['task']['children'][0]
                self.responses[child['active_run_id']]={'state':'stopped','reason':reason,'api_attempts':1,'records':[]}
                self.service.poll();current=self.service.status(task['task_id'])['task']['children'][0]
                self.assertEqual(current['state'],'stopped')
                self.assertEqual(current['reason_code'],reason if reason!='user_stop' else 'legacy_stop_requested')

    def test_first_typed_cause_survives_later_owner_stop_and_direct_user_is_proven(self):
        for origin,reason in [('cloud_worker','cloud_controller_error'),('user','user_stop')]:
            task=self.create(platforms=['xhs'],targets_by_platform={'xhs':['66fad51c000000001b0224b8']},desired_items=1,max_api_requests=3,idempotency_key='typed-'+origin)
            self.service.poll();child=self.service.status(task['task_id'])['task']['children'][0]
            self.service.stop(task['task_id'])
            self.responses[child['active_run_id']]={'state':'stopped','reason':reason,'api_attempts':1,
                'stop_context':{'origin':origin,'reason':reason},'records':[]}
            self.service.poll();current=self.service.status(task['task_id'])['task']['children'][0]
            self.assertEqual(current['reason_code'],reason)

    def test_restart_dispatching_persistence_blocks_replay(self):
        task = self.create()
        with self.service._db() as db:
            saved = self.service._load(db, task['task_id'])
            saved['children'][0].update(state='dispatching', requests_reserved=3)
            self.service._save(db, saved)
        self.service.poll()
        current = self.service.status(task['task_id'])['task']
        self.assertEqual(current['children'][0]['reason_code'], 'dispatch_outcome_unknown')
        self.assertEqual(sum(a == 'start' and p['platform'] == 'xhs' for a, p in self.calls), 0)

    def test_no_content_exit_zero_is_not_completed(self):
        task = self.create()
        self.service.poll()
        run_id = self.service.status(task['task_id'])['task']['children'][0]['active_run_id']
        self.responses[run_id] = {'state': 'completed', 'api_attempts': 1}
        self.service.poll()
        self.assertEqual(self.service.status(task['task_id'])['task']['children'][0]['reason_code'], 'no_content_observed')

    def test_batch_platform_binding_errors_and_dedup(self):
        value = parse_batch('platform,target\nxhs,66fad51c000000001b0224b8\n微博,123\nxhs,66fad51c000000001b0224b8\n')
        self.assertTrue(value['ok'])
        self.assertEqual(value['unique_targets'], 2)
        self.assertEqual(value['targets_by_platform'], {'xhs': ['66fad51c000000001b0224b8'], 'wb': ['123']})
        value = parse_batch('xhs\t66fad51c000000001b0224b8\nwb\thttps://xiaohongshu.com/explore/66fad51c000000001b0224b8\n')
        self.assertFalse(value['ok'])
        self.assertEqual(value['errors'][0]['line'], 2)
        self.assertEqual(value['errors'][0]['error'], 'invalid_platform_url')

    def test_background_progress_without_status_poll(self):
        self.service._ensure_thread = OwnerTasks._ensure_thread.__get__(self.service)
        self.service.interval = 0.01
        task = self.create()
        deadline = time.monotonic() + 2
        while not self.calls and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(any(action == 'start' for action, _ in self.calls))
        self.assertEqual(self.service.status(task['task_id'])['task']['state'], 'running')
        self.service.close()
        self.assertFalse(any(action == 'stop' for action, _ in self.calls))

    def test_shared_scheduler_lock_blocks_other_process_dispatch(self):
        import fcntl
        task = self.create()
        with open(self.service.root / 'scheduler.lock', 'a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertTrue(self.service.poll()['scheduler_busy'])
        self.assertFalse(self.calls)
        self.service.poll()
        self.assertEqual(sum(action == 'start' for action, _ in self.calls), 1)

    def test_single_url_auto_route_and_bare_id_requires_platform(self):
        parsed = parse_batch('https://www.xiaohongshu.com/explore/66fad51c000000001b0224b8\nhttps://weibo.com/123/AbC\n')
        self.assertTrue(parsed['ok'])
        self.assertEqual(parsed['platforms'], ['xhs', 'wb'])
        self.assertFalse(parse_batch('66fad51c000000001b0224b8')['ok'])
        missing = self.service.preview(self.request(targets_by_platform={'xhs': ['66fad51c000000001b0224b8']}))
        self.assertEqual(missing['children'][1]['state'], 'waiting')
        self.assertEqual(missing['mode'], 'detail')

    def test_zhihu_media_and_existing_platform_share_healthy_plan(self):
        request = self.request(platforms=['xhs', 'zhihu'], targets_by_platform={'xhs': ['66fad51c000000001b0224b8'], 'zhihu': ['https://www.zhihu.com/question/1/answer/1']}, media=True)
        value = self.service.preview(request)
        self.assertEqual(value['children'][0]['state'], 'queued')
        self.assertIsNone(value['children'][1]['reason_code'])
        self.assertEqual(value['children'][1]['state'], 'queued')
        task = self.service.create(request)['task']
        self.service.resume(task['task_id'])
        self.assertEqual(self.service.status(task['task_id'])['task']['children'][1]['state'], 'queued')

    def test_cross_instance_stop_survives_delayed_start_response(self):
        task = self.create()
        entered, release = threading.Event(), threading.Event()
        original = self.service.runner
        def slow_start(action, payload):
            if action == 'start':
                entered.set()
                release.wait(3)
            return original(action, payload)
        self.service.runner = slow_start
        thread = threading.Thread(target=self.service.poll)
        thread.start()
        self.assertTrue(entered.wait(1))
        other = OwnerTasks(self.temp.name, original)
        other._ensure_thread = lambda: None
        stopped = other.stop(task['task_id'])
        self.assertEqual(stopped['task']['desired_state'], 'stopped')
        release.set()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(other.status(task['task_id'])['task']['desired_state'], 'stopped')
        self.assertTrue(any(action == 'stop' for action, _ in self.calls))
        other.close()

    def test_auto_session_reuses_idle_platform_and_never_busy(self):
        idle, busy = str(uuid.uuid4()), str(uuid.uuid4())
        original = self.service.runner
        def list_runner(action, payload):
            if action == 'list':
                return {'ok': True, 'result': {'runs': [
                    {'platform': 'xhs', 'session_id': idle, 'state': 'completed', 'updated_at': 1},
                    {'platform': 'xhs', 'session_id': busy, 'state': 'completed', 'updated_at': 3},
                    {'platform': 'xhs', 'session_id': busy, 'state': 'interrupted_unknown', 'updated_at': 4}]}}
            return original(action, payload)
        self.service.runner = list_runner
        task = self.create()
        self.service.poll()
        request = next(payload for action, payload in self.calls if action == 'start')
        self.assertEqual(request['session_id'], idle)
        child = self.service.status(task['task_id'])['task']['children'][0]
        self.assertEqual(child['session_selection'], 'auto_reused')
        self.assertEqual(child['session_login_state'], 'unverified')

    def test_strict_boundary_and_no_secret_status(self):
        with self.assertRaises(ValueError):
            self.create(desired_items=True)
        with self.assertRaises(ValueError):
            self.create(targets_by_platform={'xhs': ['token=secret'], 'wb': ['123']})
        task = self.create(targets_by_platform={'xhs': ['https://www.xiaohongshu.com/explore/66fad51c000000001b0224b8?xsec_token=66fad51c000000001b0224b8d'], 'wb': ['123']})
        self.assertNotIn('xsec_token', json.dumps(task))
        with self.assertRaisesRegex(ValueError, 'invalid_task_id'):
            self.service.status('../anything')


if __name__ == '__main__':
    unittest.main()
