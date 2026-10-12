import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from mc_runner import normalize, BridgeError, canonical
from cloud_sync import RECORD_FIELDS, CloudOutbox
from results_store import _related_content_type


class ZhihuCommentType(unittest.TestCase):
    def row(self, content_type='answer',parent='0'):
        return {'content_id':'123','comment_id':'456','parent_comment_id':parent,'content':'fixture exact',
                'content_type':content_type,'sub_comment_count':2}

    def test_explicit_three_types_reach_existing_cloud_and_typed_callers(self):
        for content_type in ('answer','article','zvideo'):
            raw=self.row(content_type);record=normalize('zhihu','comment',raw,{'line':1})
            self.assertEqual(record['content_type'],content_type)
            cloud={k:v for k,v in record.items() if k in RECORD_FIELDS}
            self.assertEqual(cloud['content_type'],content_type)
            self.assertEqual(_related_content_type(cloud),content_type)
            self.assertEqual(record['entity_key'],'zhihu:123:456')
            self.assertEqual(record['parent_comment_id'],'0')
            unhashed={k:v for k,v in record.items() if k!='record_hash'}
            self.assertEqual(record['record_hash'],hashlib.sha256(canonical(unhashed).encode()).hexdigest())

    def test_missing_unknown_kept_and_bad_type_never_guessed(self):
        for missing in (None,''):
            record=normalize('zhihu','comment',self.row(missing),{})
            self.assertNotIn('content_type',record)
            self.assertIsNone(_related_content_type(record))
        raw=self.row();raw.pop('content_type')
        self.assertNotIn('content_type',normalize('zhihu','comment',raw,{}))
        for invalid in (True,False,3,3.0,{},[], 'question','ANSWER',' answer ','password=fixture'):
            with self.subTest(value=invalid),self.assertRaisesRegex(BridgeError,'^invalid_zhihu_comment_content_type$'):
                normalize('zhihu','comment',self.row(invalid),{})

    def test_reply_identity_namespace_and_other_platform_compatibility(self):
        record=normalize('zhihu','comment',self.row('article','12345'),{})
        self.assertEqual(record['parent_comment_id'],'12345')
        self.assertEqual(record['comment_id'],'456');self.assertEqual(record['kind'],'comment')
        self.assertEqual(record['text'],'fixture exact')
        for kind in ('answer','article'):
            self.assertEqual(normalize('zhihu','comment',self.row(kind),{})['entity_key'],'zhihu:123:456')
        raw=self.row('answer');raw['note_id']='123'
        self.assertNotIn('content_type',normalize('tieba','comment',raw,{}))

    def test_actual_outbox_envelope_preserves_type_without_network(self):
        with tempfile.TemporaryDirectory() as folder:
            outbox=CloudOutbox(folder,None)
            lease={key:str(uuid.uuid4()) for key in ('task_id','child_id','run_id')}
            lease.update(platform='zhihu',lease_epoch=1,delivery_basis='live_capture')
            record=normalize('zhihu','comment',self.row('zvideo','12345'),{})
            capture_id=outbox.stage_imported([record],lease)[0]
            with outbox._db() as db:
                envelope=json.loads(db.execute('select envelope from captures where id=?',(capture_id,)).fetchone()[0])
            self.assertEqual(envelope['record']['content_type'],'zvideo')
            self.assertEqual(envelope['record']['comment_id'],'456')
            self.assertEqual(envelope['record']['parent_comment_id'],'12345')
            self.assertEqual(outbox.stats()['pending'],1)

    def test_actual_six_sdk_rows_readonly_not_reimport_or_reack(self):
        workspace=Path(__file__).resolve().parents[5]
        run=workspace/'.crowd-launch/seven-platform-live/zhihu/runs/a42307ea-5684-414f-a4dc-11fa628ca098'
        if not run.is_dir():self.skipTest('local real SDK fixture not present')
        files=[f for f in run.rglob('*') if f.is_file() and not f.is_symlink()]
        before={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
        comments=next((run/'output/zhihu/jsonl').glob('*comments*.jsonl'))
        rows=[json.loads(line) for line in comments.read_text().splitlines() if line.strip()]
        self.assertEqual(len(rows),6)
        records=[normalize('zhihu','comment',row,{'run_id':run.name,'line':i+1}) for i,row in enumerate(rows)]
        self.assertEqual([record['content_type'] for record in records],['answer']*6)
        self.assertEqual(sum(record['parent_comment_id']=='0' for record in records),3)
        self.assertEqual([record['parent_comment_id'] for record in records],[row['parent_comment_id'] for row in rows])
        self.assertEqual([record['comment_id'] for record in records],[str(row['comment_id']) for row in rows])
        self.assertEqual(before,{str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in files})


if __name__=='__main__':unittest.main()
