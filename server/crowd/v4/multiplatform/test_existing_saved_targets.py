"""Real local ResultsStore and owner/worker routes; no source or cloud network."""
from copy import deepcopy
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock

from cloud_sync import CloudOwnerAdapter, CloudWorker
from dashboard import Application
from existing_saved import bili_identifier, validate_existing_targets
from results_store import ResultsStore
from test_cloud_sync import FakeCloud, lease

BV='BV1ocaW6rETo'
OTHER='BV1xx411c7mD'
AID='117355149531810'


class ExistingSavedTargetsTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.store=ResultsStore(self.root)
        self.body={'kind':'content','platform':'bilibili','content_id':AID,'title':'Same title cannot prove identity',
            'body':'saved body','source_kind':'mediacrawler_api','reward_eligible':False,
            'platform_fields':{'bvid':BV,'video_url':'https://www.bilibili.com/video/'+BV}}
        self.comment={'kind':'comment','platform':'bilibili','content_id':AID,'comment_id':'c1',
            'parent_comment_id':'0','text':'saved comment','source_kind':'mediacrawler_api','reward_eligible':False}
        self.store.ingest({'run_id':'fixture-run','records':[self.body,self.comment]})
        self.app=object.__new__(Application);self.app.root=self.root;self.app.lock=threading.RLock()
        self.app.cloud_client=Mock()
        self.app.cloud_client.call.return_value={'schema':'crowd-unified-dispatch-v1'}
        self.app.owner_tasks=CloudOwnerAdapter(self.app.cloud_client,self.app._validate_cloud_existing)

    def refs(self,kind=None):
        items=self.store.list_results(filters={'platform':'bilibili','content_id':AID})['items']
        return [{'platform':'bilibili','content_id':AID,'kind':r['kind'],'version_hash':r['version_hash']}
                for r in items if kind is None or r['kind']==kind]

    def payload(self,target=BV,kind=None):
        return {'platforms':['bili'],'mode':'detail','delivery_basis':'existing_saved','desired_items':1,
            'max_api_requests':0,'targets_by_platform':{'bili':[target]},'record_refs_by_platform':{'bili':self.refs(kind)},
            'idempotency_key':'fixture-only','purpose':'noncommercial_research','comments':True,'replies':True,'media':False}

    def route(self,action,payload):
        return self.app.cloud(action,payload) if action.startswith('unified_') else self.app.tasks(action,payload)

    def test_all_owner_preview_create_routes_reject_other_target_before_cloud(self):
        for action in ('preview','create','unified_preview','unified_create'):
            with self.subTest(action=action),self.assertRaisesRegex(ValueError,'existing_saved_target_mismatch'):
                self.route(action,self.payload(OTHER))
        self.app.cloud_client.call.assert_not_called()

    def test_exact_bv_url_and_explicit_aid_mapping_pass_local_guard(self):
        for target in (BV,'https://www.bilibili.com/video/'+BV+'/?p=1',AID,'av'+AID,'https://www.bilibili.com/video/av'+AID):
            with self.subTest(target=target):
                self.app._validate_cloud_existing(self.payload(target))
        for action in ('preview','create','unified_preview','unified_create'):
            self.route(action,self.payload())
        self.assertEqual(self.app.cloud_client.call.call_count,4)
        # Aid spellings are locally recognizable evidence, not a change to the
        # cloud's accepted target syntax (currently detail targets require BV).

    def test_comment_only_uses_local_body_mapping_without_delivering_it(self):
        payload=self.payload(kind='comment')
        self.app._validate_cloud_existing(payload)
        records=self.app._cloud_existing({'platform':'bili','request':{'mode':'detail','targets':[BV]},
            'record_refs':payload['record_refs_by_platform']['bili']})
        self.assertEqual(len(records),1);self.assertEqual(records[0]['kind'],'comment')

    def test_missing_mapping_unknown_targets_and_host_confusion_fail_closed(self):
        request={'platform':'bili','request':{'mode':'detail','targets':[BV]}}
        for target in ('not-a-video','https://bilibili.com.evil.invalid/video/'+BV,'https://b23.tv/unknown',None):
            with self.subTest(target=target),self.assertRaisesRegex(ValueError,'unverified'):
                validate_existing_targets({'platform':'bili','request':{'mode':'detail','targets':[target]}},[self.body])
        for row in ({**self.body,'platform_fields':{}},self.comment):
            with self.assertRaisesRegex(ValueError,'unverified'):
                validate_existing_targets(request,[row])

    def test_conflicting_metadata_cannot_use_one_matching_alias(self):
        for delta in ({'bvid':OTHER},{'aid':'123'},{'bvid':'malformed'}):
            row={**self.body,'platform_fields':{**self.body['platform_fields'],**delta}}
            with self.assertRaisesRegex(ValueError,'existing_saved_target_'):
                validate_existing_targets({'platform':'bili','request':{'mode':'detail','targets':[BV]}},[row])

    def test_author_or_dynamic_id_collision_is_not_video_identity(self):
        for kind in ('author','dynamic'):
            with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,'unverified'):
                validate_existing_targets({'platform':'bili','request':{'mode':'detail','targets':[AID]}},
                                          [{**self.body,'kind':kind}])
        validate_existing_targets({'platform':'bili','request':{'mode':'creator','targets':[AID]}},
                                  [{**self.body,'kind':'author'}])

    def test_mixed_selected_videos_each_require_target_match(self):
        other={**self.body,'content_id':'123','platform_fields':{'bvid':OTHER}}
        with self.assertRaisesRegex(ValueError,'mismatch'):
            validate_existing_targets({'platform':'bili','request':{'mode':'detail','targets':[BV]}},[self.body,other])
        validate_existing_targets({'platform':'bili','request':{'mode':'detail','targets':[BV,OTHER]}},[self.body,other])

    def test_exact_selected_old_version_not_overridden_by_latest_matching_body(self):
        wrong={**self.body,'platform_fields':{'bvid':OTHER}}
        self.store.ingest({'run_id':'different-version','records':[wrong]})
        wrong_ref=self.refs('content')[0]
        self.store.ingest({'run_id':'matching-again','records':[self.body]})
        payload=self.payload();payload['record_refs_by_platform']['bili']=[wrong_ref]
        with self.assertRaisesRegex(ValueError,'mismatch'):self.app._validate_cloud_existing(payload)

    def test_search_creator_other_platform_and_live_capture_keep_prior_semantics(self):
        for mode in ('search','creator','homefeed','trending'):
            validate_existing_targets({'platform':'bili','request':{'mode':mode,'targets':['query-or-author']}},[self.body])
        validate_existing_targets({'platform':'xhs','request':{'mode':'detail','targets':['other']}},[self.body])
        payload=self.payload(OTHER);payload['delivery_basis']='live_capture'
        self.app.owner_tasks.preview(payload)
        self.app.cloud_client.call.assert_called_once()

    def test_adapter_without_results_validator_cannot_forward_unverified_detail(self):
        adapter=CloudOwnerAdapter(self.app.cloud_client)
        with self.assertRaisesRegex(ValueError,'unverified'):adapter.create(self.payload())
        self.app.cloud_client.call.assert_not_called()

    def test_worker_read_boundary_stops_wrong_legacy_lease_before_staging_or_source(self):
        value=lease('existing_saved');value.update(platform='bili',record_refs=self.refs())
        value['request'].update(platform='bili',mode='detail',targets=[OTHER])
        cloud=FakeCloud(value);runner=Mock(side_effect=AssertionError('source forbidden'))
        worker=CloudWorker(self.root,cloud,runner,existing_reader=self.app._cloud_existing)
        outcome=worker.tick()
        self.assertEqual(outcome['error'],'existing_saved_target_mismatch')
        self.assertEqual(worker.outbox.stats()['pending'],0)
        self.assertEqual(worker.outbox.stats()['acknowledged'],0)
        self.assertFalse(any(action in ('capture','finish') for action,_ in cloud.calls))
        runner.assert_not_called()

    def test_successful_worker_keeps_exact_record_payload_and_source_zero(self):
        value=lease('existing_saved');value.update(platform='bili',record_refs=self.refs())
        value['request'].update(platform='bili',mode='detail',targets=[BV])
        cloud=FakeCloud(value);runner=Mock(side_effect=AssertionError('source forbidden'))
        worker=CloudWorker(self.root,cloud,runner,existing_reader=self.app._cloud_existing)
        self.assertEqual(worker.tick()['state'],'finished')
        captures=[p['envelope']['record'] for action,p in cloud.calls if action=='capture']
        self.assertEqual(len(captures),2)
        self.assertEqual({r['content_id'] for r in captures},{AID})
        self.assertEqual(next(r for r in captures if r['kind']=='content')['platform_fields'],self.body['platform_fields'])
        runner.assert_not_called()


if __name__=='__main__':unittest.main()
