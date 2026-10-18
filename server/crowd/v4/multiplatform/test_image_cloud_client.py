import copy
import json
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from PIL import Image

from cloud_sync import SCHEMA, _hash, canonical, CloudError
from image_cloud import prepare_image, validate_manifest
from image_cloud_client import publish, download, status
from results_store import ResultsStore
from saved_media_attachments import SavedMediaAttachments, sha


class Response:
    status = 200
    headers = {}
    def __init__(self, data=b''): self.data = data
    def read(self, limit): return self.data[:limit]
    def __enter__(self): return self
    def __exit__(self, *_): pass


class Client:
    endpoint = 'https://project.supabase.co/functions/v1/crowd-machine'
    role = 'owner'
    def __init__(self, receipt, record):
        self.capture = receipt; self.record = record; self.calls = []; self.data = None
        self.artifact_id = str(uuid.uuid4()); self.manifest = None; self.foreign = False
    def call(self, action, payload):
        self.calls.append(action)
        if action == 'receipt':
            assert self.role == 'worker', 'Actual Edge receipt action is worker-only'
            return {'receipt': copy.deepcopy(self.capture)}
        if action == 'results':
            assert self.role == 'owner', 'Actual Edge results action is owner-only'
            return {'items': [{'record': copy.deepcopy(self.record), 'receipt': copy.deepcopy(self.capture)}]}
        if action == 'image_prepare':
            self.manifest = copy.deepcopy(payload)
            return {'artifact_id': self.artifact_id,
                    'manifest_hash': validate_manifest(payload)['manifest_hash'],
                    'upload_url': self.url('upload/sign').replace('project.supabase.co', 'evil.invalid') if self.foreign else self.url('upload/sign')}
        if action == 'image_commit':
            if self.data is None: raise CloudError('image_object_missing')
            return {'receipt': self.receipt()}
        if action == 'image_get':
            if self.data is None: raise CloudError('image_object_missing')
            return {'receipt': self.receipt(), 'download_url': self.url('sign')}
        raise AssertionError(action)
    def path(self):
        suffix = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp'}[self.manifest['content_mime']]
        return 'crowd-owner-main/' + self.artifact_id + '/' + self.manifest['asset_sha256'] + suffix
    def url(self, kind):
        return 'https://project.supabase.co/storage/v1/object/' + kind + '/crowd-machine-media/' + self.path() + '?token=SYNTHETIC'
    def receipt(self):
        return {'artifact_id': self.artifact_id, 'artifact_kind': 'image_object', 'status': 'received',
                'verification': 'server_storage_bytes_sha256_decode', 'reward_eligible': False,
                'bucket_id': 'crowd-machine-media', 'object_path': self.path(),
                'manifest': copy.deepcopy(self.manifest), 'manifest_hash': validate_manifest(self.manifest)['manifest_hash']}


class Opener:
    def __init__(self, client, outcome='success'):
        self.client = client; self.outcome = outcome; self.puts = 0
    def open(self, request, timeout):
        if request.get_method() == 'PUT':
            self.puts += 1
            assert request.headers['Content-type'] == 'image/png'
            assert request.headers['X-upsert'] == 'false'
            if self.outcome != 'lost_before_server': self.client.data = request.data
            if self.outcome != 'success': raise OSError('SYNTHETIC_CONNECTION_LOST')
            return Response()
        return Response(self.client.data)


class ImageClient(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name).resolve()
        self.rid = str(uuid.uuid4()); self.run = self.root / 'runs' / self.rid; self.run.mkdir(parents=True)
        ref = {'media_id': 'a' * 64, 'platform': 'xiaohongshu', 'content_id': 'note', 'kind': 'image',
               'url': 'http://sns-webpic-qc.xhscdn.com/image?keep=all', 'status': 'reference_only',
               'source_kind': 'mediacrawler_api', 'reward_eligible': False}
        body = {'kind': 'content', 'platform': 'xiaohongshu', 'content_id': 'note', 'body': 'full original body',
                'author': {'author_id': 'public-author'}, 'reward_eligible': False,
                'origin': {'run_id': self.rid, 'operation_id': self.rid, 'executor': 'mediacrawler_pro', 'observation_sha256': 'b' * 64}, 'media': [ref]}
        body['record_hash'] = sha(body); self.body = body
        norm = {'run_id': self.rid, 'run_state': 'completed', 'source_kind': 'mediacrawler_api',
                'reward_eligible': False, 'records': [body], 'media': [ref]}
        files = {}
        for name, value in [('normalized', norm), ('manifest', {'run_id': self.rid, 'executor': {'backend': 'pro'}, 'request': {'platform': 'xhs'}}), ('status', {'run_id': self.rid, 'state': 'completed'})]:
            path = self.run / (name + '.json'); path.write_text(canonical(value)); files[name] = sha(path.read_bytes())
        self.asset = self.root / 'image.png'; Image.new('RGB', (20, 16), (15, 30, 45)).save(self.asset)
        receipt = {'run_id': self.rid, 'media_id': ref['media_id'], 'state': 'downloaded_not_imported_or_cloud_saved',
                   'source_files_unchanged': True, 'platform_http_requests': 1, 'cloud_ack': False,
                   'reference_sha256': sha(ref), 'source_record_hash': body['record_hash'], 'asset_file': self.asset.name,
                   'asset_sha256': sha(self.asset.read_bytes()), 'bytes': self.asset.stat().st_size, 'content_type': 'image/png',
                   'url_sha256': sha(ref['url']), 'transport_url_sha256': sha(ref['url'].replace('http:', 'https:', 1)),
                   **{n + '_sha256': h for n, h in files.items()}}
        store = ResultsStore(self.root / 'library'); store.ingest(norm)
        self.adapter = SavedMediaAttachments(self.root / 'owned', lambda _: self.run, store)
        self.virtual = self.adapter.attach(self.rid, ref['media_id'], self.asset, receipt)['media']['path']
        self.jobs = SimpleNamespace(root=self.root / 'media-jobs')
        captured = {k: v for k, v in body.items() if k != 'record_hash'}
        captured['author_id'] = body['author']['author_id']
        envelope = {'schema': SCHEMA, 'capture_id': str(uuid.uuid4()), 'task_id': str(uuid.uuid4()), 'child_id': str(uuid.uuid4()),
                    'run_id': str(uuid.uuid4()), 'lease_epoch': 1, 'record': captured,
                    'platform': 'xiaohongshu', 'delivery_basis': 'existing_saved',
                    'source_kind': 'machine_api', 'adapter_version': 'cloud-machine-v1',
                    'normalizer_version': 'mc-normalized-v2', 'packaged_at': '2026-10-15T09:00:00Z'}
        self.receipt = {k: envelope[k] for k in ('capture_id', 'task_id', 'child_id', 'run_id', 'lease_epoch')}
        self.receipt.update(status='received', reward_eligible=False, source_kind='machine_api', envelope_hash=_hash(SCHEMA, envelope))
        self.db = self.root / 'outbox.sqlite3'
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE captures(id TEXT,envelope TEXT,digest TEXT,receipt TEXT,state TEXT)')
            db.execute('INSERT INTO captures VALUES(?,?,?,?,?)', (envelope['capture_id'], canonical(envelope), self.receipt['envelope_hash'], canonical(self.receipt), 'acknowledged'))
        self.client = Client(self.receipt, captured); self.opener = Opener(self.client)
    def tearDown(self): self.tmp.cleanup()
    def args(self): return self.jobs, self.adapter, self.db, self.client, self.rid, self.virtual
    def test_actual_projection_publish_status_download_and_replay(self):
        result = publish(*self.args(), opener=self.opener)
        self.assertEqual(result['state'], 'received')
        self.assertEqual(status(*self.args())['state'], 'received')
        self.assertEqual(download(*self.args(), opener=self.opener)['data'], self.asset.read_bytes())
        publish(*self.args(), opener=self.opener)
        self.assertEqual(self.opener.puts, 1)
    def test_unknown_after_upload_reconciles_without_second_put(self):
        self.opener.outcome = 'lost_after_server'
        self.assertEqual(publish(*self.args(), opener=self.opener)['state'], 'received')
        self.assertEqual(self.opener.puts, 1)
    def test_unknown_missing_is_never_reuploaded(self):
        self.opener.outcome = 'lost_before_server'
        for _ in range(2):
            with self.assertRaisesRegex(ValueError, 'image_upload_outcome_unknown'):
                publish(*self.args(), opener=self.opener)
        self.assertEqual(self.opener.puts, 1)
    def test_foreign_upload_denied_before_put(self):
        self.client.foreign = True
        with self.assertRaises(ValueError): publish(*self.args(), opener=self.opener)
        self.assertEqual(self.opener.puts, 0)
    def test_changed_outbox_hash_denied_before_rpc(self):
        with sqlite3.connect(self.db) as db: db.execute("UPDATE captures SET digest=?", ('0' * 64,))
        with self.assertRaisesRegex(ValueError, 'image_capture_binding_changed'): publish(*self.args(), opener=self.opener)
        self.assertEqual(self.client.calls, [])
    def test_authoritative_receipt_mismatch_denied(self):
        self.client.capture = {**self.receipt, 'capture_id': str(uuid.uuid4())}
        with self.assertRaisesRegex(ValueError, 'image_capture_binding_changed'): publish(*self.args(), opener=self.opener)
        self.assertEqual(self.opener.puts, 0)
    def test_source_hash_and_derived_author_must_match(self):
        record = {k: v for k, v in self.body.items() if k != 'record_hash'}
        record['author_id'] = 'other-author'
        with self.assertRaisesRegex(ValueError, 'image_source_binding_denied'):
            prepare_image(self.adapter, self.rid, self.virtual, {'record': record, 'receipt': self.receipt})
    def test_unsaved_status_does_not_prepare_cloud_object(self):
        self.assertEqual(status(*self.args())['state'], 'not_saved')
        self.assertEqual(self.client.calls, ['results'])
    def test_worker_reconciles_with_worker_receipt_action(self):
        self.client.role = 'worker'
        self.assertEqual(publish(*self.args(), opener=self.opener)['state'], 'received')
        self.assertIn('receipt', self.client.calls); self.assertNotIn('results', self.client.calls)
    def test_corrupt_local_receipt_shapes_are_fixed_errors(self):
        for bad in ([], None, {'status': 'received'}):
            with sqlite3.connect(self.db) as db: db.execute('UPDATE captures SET receipt=?', (json.dumps(bad),))
            with self.subTest(bad=bad), self.assertRaises(ValueError): publish(*self.args(), opener=self.opener)
        self.assertEqual(self.opener.puts, 0)
    def test_corrupt_journal_shapes_and_flags_are_fixed_errors(self):
        publish(*self.args(), opener=self.opener)
        path = self.root / 'media-cloud-receipts' / (self.client.manifest['local_job_id'] + '.json')
        saved = json.loads(path.read_text())
        for bad in ([], None, {**saved, 'attempted': 1}, {**saved, 'artifact_id': 'bad'}, {**saved, 'receipt': []}):
            path.write_text(json.dumps(bad))
            with self.subTest(bad=type(bad).__name__), self.assertRaises(ValueError): status(*self.args())
        self.assertEqual(self.opener.puts, 1)
    def test_remote_owner_response_shapes_are_fixed_errors(self):
        original = self.client.call
        for bad in ([], {'items': {}}, {'items': [{'receipt': []}]}, {'items': [{'receipt': self.receipt, 'record': []}]}):
            self.client.call = lambda action, payload, bad=bad: bad if action == 'results' else original(action, payload)
            with self.subTest(bad=type(bad).__name__), self.assertRaises(ValueError): publish(*self.args(), opener=self.opener)
        self.assertEqual(self.opener.puts, 0)


if __name__ == '__main__': unittest.main()
