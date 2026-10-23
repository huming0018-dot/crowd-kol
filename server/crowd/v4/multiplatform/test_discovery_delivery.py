import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch, Mock

import mc_runner
from cloud_sync import CloudOutbox, CloudError, canonical, _hash, SCHEMA
from test_cloud_sync import FakeCloud, lease, row


class DiscoveryDeliveryTests(unittest.TestCase):
    def test_start_marks_only_new_run_without_launching_source(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); root = base/'runtime'; mc = base/'fake-mc'
            (mc/'.venv/bin').mkdir(parents=True); (mc/'.venv/bin/python').touch()
            request = {'platform':'bili','mode':'detail','session_id':str(uuid.uuid4()),'headless':False}
            with patch.object(mc_runner,'validate',return_value=request),patch.object(mc_runner,'source_info',return_value={}),patch.object(mc_runner.subprocess,'Popen',return_value=Mock(pid=1)) as launch:
                result = mc_runner.start(root,mc,{})
            self.assertEqual(mc_runner.read(root/'runs'/result['run_id']/'manifest.json')['discovery_contract_version'],1)
            launch.assert_called_once()  # Fake launch: no process or platform request was started.

    def test_local_results_preserve_entry_and_historical_snapshot(self):
        from results_store import ResultsStore
        with tempfile.TemporaryDirectory() as directory:
            store = ResultsStore(Path(directory)); record = row()
            first = store.ingest({'records':[record]})
            before = store.list_results(revision=first['results_revision'])
            for discovery_kind in ('search','detail','creator','homefeed'):
                store.ingest({'records':[{**record,'discovery_kind':discovery_kind}]})
                current = store.list_results()['items'][0]
                self.assertEqual(current['discovery_kind'],discovery_kind)
                self.assertEqual(current['body'],record['body'])
            self.assertEqual(store.list_results(revision=first['results_revision']),before)
            self.assertNotIn('discovery_kind',before['items'][0])

    def test_five_entry_labels_survive_envelope_and_replay(self):
        for kind in ('search','detail','creator','homefeed','trending'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                cloud = FakeCloud(); context = lease(); context['platform'] = 'bili'
                outbox = CloudOutbox(Path(directory), cloud)
                record = {**row(), 'platform':'bilibili', 'discovery_kind':kind}
                ids = outbox.stage_imported([record], context)
                outbox.flush()
                with outbox._db() as db:
                    before = db.execute('SELECT * FROM captures').fetchall()
                self.assertEqual(json.loads(before[0][2])['record']['discovery_kind'], kind)
                self.assertEqual(outbox.stage_imported([record], context), ids)
                with outbox._db() as db:
                    self.assertEqual(db.execute('SELECT * FROM captures').fetchall(), before)

    def test_legacy_ack_exact_bytes_preserved_and_new_tag_not_backfilled(self):
        with tempfile.TemporaryDirectory() as directory:
            cloud = FakeCloud(); context = lease(); outbox = CloudOutbox(Path(directory), cloud)
            record = row(); record['record_hash'] = 'a' * 64
            ids = outbox.stage_imported([record], context); outbox.flush()
            with outbox._db() as db:
                before = db.execute('SELECT * FROM captures').fetchall()
            self.assertEqual(outbox.stage_imported([{**record, 'discovery_kind':'search'}], context), ids)
            with outbox._db() as db:
                self.assertEqual(db.execute('SELECT * FROM captures').fetchall(), before)
            self.assertNotIn('discovery_kind', json.loads(before[0][2])['record'])
            new_ids = outbox.stage_imported([{**record, 'body':'new version', 'discovery_kind':'search'}], context)
            self.assertNotEqual(new_ids, ids)
            with outbox._db() as db:
                self.assertEqual(db.execute('SELECT * FROM captures WHERE id=?', (ids[0],)).fetchall(), before)

    def test_legacy_reuse_checks_exact_binding_record_and_digest(self):
        for change in ('digest','task_id','child_id','lease_epoch','body','platform','kind','content_id'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                cloud = FakeCloud(); context = lease(); outbox = CloudOutbox(Path(directory), cloud)
                record = row(); ids = outbox.stage_imported([record], context)
                with outbox._db() as db:
                    saved = json.loads(db.execute('SELECT envelope FROM captures').fetchone()[0])
                    if change == 'digest':
                        db.execute('UPDATE captures SET digest=?', ('0'*64,))
                    else:
                        if change in ('task_id','child_id'):
                            saved[change] = str(uuid.uuid4())
                        elif change == 'lease_epoch':
                            saved[change] = 2
                        else:
                            saved['record'][change] = 'changed'
                        db.execute('UPDATE captures SET envelope=?', (canonical(saved),))
                with self.assertRaisesRegex(CloudError, 'capture_hash_conflict'):
                    outbox.stage_imported([{**record, 'discovery_kind':'search'}], context)

    def test_epoch_types_and_extra_fields_cannot_reuse_legacy_binding(self):
        for changed in (True,1.0,'extra'):
            with self.subTest(changed=changed),tempfile.TemporaryDirectory() as directory:
                context=lease();outbox=CloudOutbox(Path(directory),FakeCloud());record=row()
                outbox.stage_imported([record],context)
                with outbox._db() as db:
                    saved=json.loads(db.execute('SELECT envelope FROM captures').fetchone()[0])
                    if changed=='extra':saved['extra']='unexpected'
                    else:saved['lease_epoch']=changed
                    # float 1.0 has a canonical integer representation; store its noncanonical type
                    # explicitly to verify rejection without changing the canonical hash protocol.
                    encoded=json.dumps(saved,ensure_ascii=False,sort_keys=True,separators=(',',':')) if type(changed) is float else canonical(saved)
                    db.execute('UPDATE captures SET envelope=?,digest=?',(encoded,_hash(SCHEMA,saved)))
                with self.assertRaisesRegex(CloudError,'capture_hash_conflict'):
                    outbox.stage_imported([{**record,'discovery_kind':'detail'}],context)
        for epoch in (True,1.0,0,-1,2147483648):
            with self.subTest(epoch=epoch),tempfile.TemporaryDirectory() as directory:
                context=lease();context['lease_epoch']=epoch
                with self.assertRaisesRegex(CloudError,'invalid_capture_record'):
                    CloudOutbox(Path(directory),FakeCloud()).stage_imported([row()],context)

    def test_invalid_labels_and_unsupported_platforms_reject_without_staging(self):
        for kind in (None, True, '', 'following', 'hot-search', 'cookie=bad', []):
            with tempfile.TemporaryDirectory() as directory:
                outbox = CloudOutbox(Path(directory), FakeCloud())
                with self.assertRaisesRegex(CloudError, 'invalid_capture_record'):
                    outbox.stage_imported([{**row(), 'discovery_kind':kind}], lease())
                self.assertEqual(outbox.stats()['capture_ids'], [])
        with tempfile.TemporaryDirectory() as directory:
            outbox = CloudOutbox(Path(directory), FakeCloud())
            with self.assertRaisesRegex(CloudError, 'invalid_capture_record'):
                outbox.stage_imported([{**row(), 'discovery_kind':'trending'}], lease())

    def test_new_manifest_provenance_tags_only_new_imports_base_hash_unchanged(self):
        for mode in ('search','detail','creator','homefeed','trending'):
            for version in (None, 1, True, 1.0):
                with self.subTest(mode=mode, version=version), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory); run_id = str(uuid.uuid4()); run = root / 'runs' / run_id
                    folder = run / 'output' / 'bili' / 'jsonl'; folder.mkdir(parents=True)
                    source = folder / 'detail_contents_test.jsonl'
                    source.write_text(json.dumps({'video_id':'123','desc':'原始正文'})+'\n')
                    manifest = {'run_id':run_id,'request':{'platform':'bili','mode':mode},'source':{}}
                    if version is not None: manifest['discovery_contract_version'] = version
                    mc_runner.write(run / 'manifest.json', manifest)
                    mc_runner.write(run / 'status.json', {'state':'completed'})
                    with patch.object(mc_runner, 'status', return_value={'state':'completed'}):
                        imported = mc_runner.import_output(root, {'run_id':run_id})
                    record = imported['records'][0]
                    if type(version) is int and version==1:
                        self.assertEqual(record['discovery_kind'], mode)
                    else:
                        self.assertNotIn('discovery_kind', record)
                    original = {k:v for k,v in record.items() if k not in ('record_hash','discovery_kind')}
                    self.assertEqual(hashlib.sha256(mc_runner.canonical(original).encode()).hexdigest(), record['record_hash'])


if __name__ == '__main__':
    unittest.main()
