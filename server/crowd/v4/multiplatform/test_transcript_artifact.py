import hashlib
import json
from pathlib import Path
import tempfile
import types
import unittest
import uuid
import urllib.error
from unittest.mock import Mock

import transcript_artifact as artifact
from mc_runner import canonical


class TranscriptCloud(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='/private/tmp')
        self.root = Path(self.temp.name)
        self.job, self.local, self.task, self.child, self.run, self.capture = [str(uuid.uuid4()) for _ in range(6)]
        folder = self.root / 'media-processing' / self.job
        folder.mkdir(parents=True)
        data = b'offline-audio-fixture'
        self.asset = hashlib.sha256(data).hexdigest()
        (folder / 'input.wav').write_bytes(data)
        state = {'job_id': self.job, 'run_id': self.local, 'state': 'completed', 'kind': 'asr', 'platform': 'tieba', 'content_id': '123', 'asset_sha256': self.asset, 'input_hash': 'a'*64}
        result = [{'kind': 'transcript', 'platform': 'tieba', 'content_id': '123', 'evidence': {'source_kind': 'authorized_local_file', 'asset_sha256': self.asset, 'duration_seconds': 2, 'processor': 'offline_fixture', 'segments': [{'start': 0, 'end': 1, 'text': '原文'}, {'start': 1, 'end': 2, 'text': '第二句'}]}}]
        (folder/'result.json').write_text(json.dumps(result))
        state['result_sha256'] = hashlib.sha256((folder/'result.json').read_bytes()).hexdigest()
        (folder/'state.json').write_text(json.dumps(state))
        self.jobs = types.SimpleNamespace(root=self.root/'media-processing')
        self.calls, self.remote, self.bad_receipt, self.lose_ack = [], None, False, False
        self.source = {'record': {'kind': 'content', 'platform': 'tieba', 'content_id': '123', 'origin': {'run_id': self.local}, 'reward_eligible': False}, 'receipt': {'task_id': self.task, 'child_id': self.child, 'run_id': self.run, 'lease_epoch': 1, 'status': 'received', 'reward_eligible': False, 'capture_id': self.capture, 'envelope_hash': 'b'*64}}
        self.client = types.SimpleNamespace(endpoint='https://offline.invalid', call=self.call)
        self.folder = folder

    def tearDown(self):
        self.temp.cleanup()

    def call(self, action, payload=None):
        self.calls.append(action)
        if action == 'task_list':
            return {'tasks': [{'task_id': self.task, 'children': [{'child_id': self.child, 'attempts': [{'run_id': self.run, 'lease_epoch': 1, 'local_run_id': self.local}]}]}]}
        if action == 'results':
            return {'items': [self.source]}
        if action == 'transcript_put':
            report = json.loads(payload['report_json'])
            receipt = {k: v for k, v in payload.items() if k not in ('report_json', 'idempotency_key')}
            receipt.update(artifact_id=str(uuid.uuid4()), artifact_hash=hashlib.sha256(('crowd-transcript-artifact-v1\n'+canonical(payload)).encode()).hexdigest(), artifact_kind='transcript_report', status='received', reward_eligible=False)
            receipt.update({k: report[k] for k in ('text_sha256', 'asset_sha256', 'full_result_file_sha256', 'segment_count', 'character_count', 'semantic_review')})
            if self.bad_receipt:
                receipt['text_sha256'] = '0'*64
            self.remote = {'receipt': receipt, 'artifact': payload}
            if self.lose_ack:
                raise ValueError('cloud_outcome_unknown')
            return {'receipt': receipt}
        if action == 'transcript_get':
            if self.remote is None:
                raise ValueError('transcript_not_found')
            return self.remote
        raise AssertionError('unexpected '+action)

    def test_status_save_get_full_segments_original_unchanged(self):
        before = {p.name: p.read_bytes() for p in self.folder.iterdir()}
        self.assertEqual(artifact.transcript_cloud(self.jobs, self.client, self.job, 'status')['status'], 'not_saved')
        saved = artifact.transcript_cloud(self.jobs, self.client, self.job, 'save')
        self.assertEqual(saved['receipt']['artifact_kind'], 'transcript_report')
        got = artifact.transcript_cloud(self.jobs, self.client, self.job, 'get')
        self.assertEqual([r['text'] for r in got['report']['segments']], ['原文', '第二句'])
        self.assertEqual(got['report']['cer'], None)
        self.assertFalse(got['report']['human_groundtruth'])
        self.assertEqual({p.name:p.read_bytes() for p in self.folder.iterdir()}, before)
        self.assertEqual(self.calls.count('transcript_put'), 1)

    def test_wrong_receipt_text_hash_not_saved(self):
        self.bad_receipt = True
        with self.assertRaisesRegex(ValueError, 'receipt_mismatch'):
            artifact.transcript_cloud(self.jobs, self.client, self.job, 'save')
        self.assertFalse((self.root/'transcript-artifact-receipts').exists())

    def test_lost_ack_status_reads_cloud_without_upload_retry(self):
        self.lose_ack = True
        with self.assertRaisesRegex(ValueError, 'outcome_unknown'):
            artifact.transcript_cloud(self.jobs, self.client, self.job, 'save')
        self.assertEqual(artifact.transcript_cloud(self.jobs, self.client, self.job, 'status')['status'], 'received')
        self.assertEqual(self.calls.count('transcript_put'), 1)

    def test_wrong_source_identity_and_bool_epoch_reject(self):
        for key, value in [('platform', 'weibo'), ('content_id', 'different')]:
            old=self.source['record'][key];self.source['record'][key]=value
            with self.assertRaisesRegex(ValueError, 'binding_denied'):
                artifact.prepare_transcript_artifact(self.jobs,self.client,self.job)
            self.source['record'][key]=old
        self.source['receipt']['lease_epoch']=True
        with self.assertRaisesRegex(ValueError, 'binding_denied'):
            artifact.prepare_transcript_artifact(self.jobs,self.client,self.job)

    def test_symlink_root_before_cloud_calls(self):
        target=self.root/'outside';target.mkdir()
        original=self.root/'media-processing';original.rename(self.root/'saved')
        original.symlink_to(target,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'unsafe_transcript_quality_path'):
            artifact.prepare_transcript_artifact(self.jobs,self.client,self.job)
        self.assertEqual(self.calls,[])

    def test_unconfigured_and_incomplete_do_not_cloud_call(self):
        with self.assertRaisesRegex(ValueError,'cloud_configuration_required'):
            artifact.prepare_transcript_artifact(self.jobs,None,self.job)
        state=json.loads((self.folder/'state.json').read_text());state['state']='running';(self.folder/'state.json').write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError,'not_completed'):
            artifact.prepare_transcript_artifact(self.jobs,self.client,self.job)
        self.assertEqual(self.calls,[])

    def test_existing_bili_kind_entity_and_zhihu_typed_suffix(self):
        for platform, entity, content_type in [('bilibili','bilibili:content:123','video'),('zhihu','zhihu:content:123:answer','answer'),('zhihu','zhihu:content:123:article','article')]:
            state=json.loads((self.folder/'state.json').read_text())
            result=json.loads((self.folder/'result.json').read_text())
            state.update(platform=platform,entity_ref=entity)
            result[0]['platform']=platform
            (self.folder/'result.json').write_text(json.dumps(result))
            state['result_sha256']=hashlib.sha256((self.folder/'result.json').read_bytes()).hexdigest()
            (self.folder/'state.json').write_text(json.dumps(state))
            self.source['record'].update(platform=platform,content_type=content_type)
            payload=artifact.prepare_transcript_artifact(self.jobs,self.client,self.job)
            self.assertEqual(json.loads(payload['report_json'])['entity_ref'],entity)
        state['entity_ref']='zhihu:content:123:answer'
        (self.folder/'state.json').write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError,'binding_denied'):
            artifact.prepare_transcript_artifact(self.jobs,self.client,self.job)
        for missing in (False,True):
            if missing:state.pop('entity_ref',None)
            else:state['entity_ref']=None
            (self.folder/'state.json').write_text(json.dumps(state))
            self.calls.clear()
            with self.assertRaisesRegex(ValueError,'binding_denied'):
                artifact.prepare_transcript_artifact(self.jobs,self.client,self.job)
            self.assertEqual(self.calls,[])

    def test_transport_read_classification_does_not_weaken_write_unknown(self):
        from cloud_sync import CloudClient, CloudError
        for role, action, expected in [('owner','transcript_get','cloud_read_unavailable'),('owner','transcript_put','cloud_outcome_unknown'),('worker','transcript_get','cloud_outcome_unknown')]:
            client=CloudClient.__new__(CloudClient)
            client.role=role;client.endpoint='https://offline.invalid';client.headers={}
            client.opener=Mock()
            client.opener.open.side_effect=urllib.error.URLError('offline')
            with self.assertRaisesRegex(CloudError,expected):client.call(action,{})
            self.assertEqual(client.opener.open.call_count,1)


if __name__ == '__main__':
    unittest.main()
