"""Offline stdlib fixtures; no SDK, network, real task or production database writes."""
import hashlib,json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import owner_native_saved as N

NOTE='a'*24;ROOT='b'*24;REPLY='c'*24;COMMIT='d'*40
NOTE_ROW={'id':1,'nickname':None,'creator_hash':'fixture','add_ts':1,'last_modify_ts':2,'note_id':NOTE,'type':'normal','title':'中文😀\n原题','desc':'正文\n保留 e\u0301','video_url':'','time':3,'last_update_time':4,'liked_count':'0007','collected_count':'0','comment_count':'2','share_count':'0','image_list':'["https://example.invalid/a.png"]','tag_list':'[]','note_url':'https://www.xiaohongshu.com/explore/'+NOTE+'?xsec_token=PRIVATE_FIXTURE&xsec_source=pc#private','source_keyword':''}
def comment(cid,parent):return {'id':2 if parent else 1,'nickname':'fixture','creator_hash':'fixture','add_ts':1,'last_modify_ts':2,'comment_id':cid,'create_time':3,'note_id':NOTE,'content':'原评论😀\n'+cid[:1],'sub_comment_count':'1'if not parent else'0','pictures':'[]','parent_comment_id':parent,'like_count':'0003','note_url':NOTE_ROW['note_url'],'target_comment_id':''}
def seed(path,wal=False):
    db=sqlite3.connect(path)
    if wal:db.execute('pragma journal_mode=wal');db.execute('pragma wal_autocheckpoint=0')
    for table,rows in [('xhs_note',[NOTE_ROW]),('xhs_note_comment',[comment(ROOT,''),comment(REPLY,ROOT)])]:
        db.execute('create table '+table+'('+','.join('"'+k+'" '+('integer'if type(v)is int else'text')for k,v in rows[0].items())+')')
        for row in rows:db.execute('insert into '+table+' values('+','.join('?'for _ in row)+')',list(row.values()))
    db.commit();return db
class Tests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve();self.source=self.root/'source.sqlite3';self.db=seed(self.source,True)
    def tearDown(self):self.db.close();self.temp.cleanup()
    def payload(self):
        dest=self.root/'snapshot.sqlite3';N.backup_sqlite(self.source,dest);return N.prepare(dest,idempotency_key='fixture-native-saved',sdk_commit=COMMIT,note_id=NOTE)
    def test_backup_reads_committed_wal_without_mutating_source(self):
        before=self.source.read_bytes();wal=Path(str(self.source)+'-wal').read_bytes();dest=self.root/'snapshot.sqlite3';meta=N.backup_sqlite(self.source,dest)
        self.assertEqual(meta['snapshot_sha256'],hashlib.sha256(dest.read_bytes()).hexdigest());self.assertEqual(self.source.read_bytes(),before);self.assertEqual(Path(str(self.source)+'-wal').read_bytes(),wal)
        with sqlite3.connect(dest)as db:self.assertEqual(db.execute('select count(*)from xhs_note_comment').fetchone()[0],2)
        self.assertEqual(dest.stat().st_mode&0o777,0o600)
    def test_public_rows_preserve_types_parent_and_explicit_url_redaction(self):
        value=self.payload();self.assertEqual(len(value['records']),3);note=value['records'][0];raw={**NOTE_ROW,'note_url':'https://www.xiaohongshu.com/explore/'+NOTE}
        self.assertEqual(note['record'],raw);self.assertIsNone(note['record']['nickname']);self.assertEqual(note['record']['liked_count'],'0007');self.assertEqual(note['url_redaction']['removed_query_keys'],['xsec_source','xsec_token']);self.assertTrue(note['url_redaction']['removed_fragment'])
        self.assertEqual(note['native_row_sha256'],N.digest('crowd-owner-native-row-v1\n'+N.canonical({'native_table':'xhs_note','native_id':NOTE,'record':NOTE_ROW})))
        self.assertNotIn('PRIVATE_FIXTURE',json.dumps(value));self.assertNotIn(str(self.root),json.dumps(value));comments={x['native_id']:x['record']for x in value['records'][1:]};self.assertEqual(comments[REPLY]['parent_comment_id'],ROOT);self.assertEqual(comments[ROOT]['parent_comment_id'],'')
    def test_repeat_is_deterministic_and_changed_content_changes_batch_hash(self):
        value=self.payload();dest=self.root/'snapshot.sqlite3';self.assertEqual(value,N.prepare(dest,idempotency_key='fixture-native-saved',sdk_commit=COMMIT,note_id=NOTE));old=N.batch_hash(value)
        with sqlite3.connect(dest)as db:db.execute("update xhs_note set title='changed'")
        db.close()  # This assertion compares a new settled snapshot; the bridge separately rejects live WAL drift.
        self.assertNotEqual(old,N.batch_hash(N.prepare(dest,idempotency_key='fixture-native-saved',sdk_commit=COMMIT,note_id=NOTE)))
    def test_missing_foreign_parent_is_rejected(self):
        self.db.execute('update xhs_note_comment set parent_comment_id=? where comment_id=?',('f'*24,REPLY));self.db.commit()
        with self.assertRaisesRegex(ValueError,'parent'):self.payload()
    def test_unknown_private_column_is_not_silently_exported(self):
        self.db.execute('alter table xhs_note add column cookie text');self.db.commit()
        with self.assertRaisesRegex(ValueError,'schema'):self.payload()
    def test_source_symlink_and_existing_snapshot_are_rejected(self):
        link=self.root/'link';link.symlink_to(self.source)
        with self.assertRaises(ValueError):N.backup_sqlite(link,self.root/'new')
        dest=self.root/'snapshot';N.backup_sqlite(self.source,dest)
        with self.assertRaises(FileExistsError):N.backup_sqlite(self.source,dest)
    def test_size_limit_and_control_canonical(self):
        self.db.execute('update xhs_note set desc=?',('字'*200000,));self.db.commit()
        with self.assertRaises(ValueError):self.payload()
        self.assertEqual(N.canonical({'😀':'\n','a':'\t'}),'{"a":"\\u0009","😀":"\\u000a"}')
class BridgeTests(unittest.TestCase):
    setUp=Tests.setUp
    tearDown=Tests.tearDown
    payload=Tests.payload
    def bridge(self,**options):
        self.value=self.payload()
        class Client:
            role='owner';endpoint='https://bdwrhshgdeghgyzwpxnl.supabase.co/functions/v1/crowd-machine'
            def __init__(self):self.calls=[];self.saved=None;self.timeout=False
            def call(self,action,payload):
                self.calls.append((action,payload))
                if action=='native_saved_put':
                    if self.timeout:raise TimeoutError('private_exception_not_for_response')
                    self.saved=payload
                    return {'native_saved':receipt(payload),'replayed':False}
                if self.saved is None:raise N.CloudError('native_saved_not_found')
                return {'native_saved':receipt(self.saved),'replayed':False,'content':self.saved}
        self.client=Client()
        return N.NativeSavedBridge(self.client,self.root/'journal',self.root/'snapshot.sqlite3',snapshot_sha256=self.value['source']['snapshot_sha256'],sdk_commit=COMMIT,note_id=NOTE,**options)
    def test_put_repeat_has_one_write_and_get_returns_same_content(self):
        b=self.bridge();first=b.put('fixture-native-saved');again=b.put('fixture-native-saved');self.assertEqual(first['state'],'recorded');self.assertEqual(again['native_saved'],first['native_saved']);self.assertEqual(sum(a=='native_saved_put'for a,_ in self.client.calls),1)
        got=b.get('fixture-native-saved');self.assertEqual(got['content'],self.value);self.assertEqual(got['native_saved']['batch_hash'],N.batch_hash(self.value));self.assertFalse(got['native_saved']['reward_eligible'])
    def test_unknown_never_repeats_put_even_if_readback_not_found(self):
        b=self.bridge();self.client.timeout=True;self.assertEqual(b.put('fixture-native-saved')['state'],'outcome_unknown');self.assertEqual(b.put('fixture-native-saved')['state'],'outcome_unknown');self.assertEqual(sum(a=='native_saved_put'for a,_ in self.client.calls),1)
    def test_same_key_changed_semantics_fails_without_second_put(self):
        b=self.bridge();b.put('fixture-native-saved');b.sdk_commit='e'*40
        with self.assertRaisesRegex(ValueError,'conflict'):b.put('fixture-native-saved')
        self.assertEqual(sum(a=='native_saved_put'for a,_ in self.client.calls),1)
    def test_final_journal_failure_remains_unknown_not_false_recorded(self):
        b=self.bridge()
        with patch.object(N,'write',side_effect=OSError('disk full')):v=b.put('fixture-native-saved')
        self.assertEqual(v['state'],'outcome_unknown');files=list((self.root/'journal').glob('*.json'));self.assertEqual(len(files),1);self.assertEqual(json.loads(files[0].read_text())['state'],'attempted_no_retry')
        recovered=b.put('fixture-native-saved');self.assertEqual(recovered['state'],'recorded');self.assertEqual(sum(a=='native_saved_put'for a,_ in self.client.calls),1)
    def test_snapshot_drift_refused_before_rpc(self):
        b=self.bridge()
        with sqlite3.connect(self.root/'snapshot.sqlite3')as db:db.execute("update xhs_note set title='drift'")
        with self.assertRaisesRegex(ValueError,'snapshot'):b.put('fixture-native-saved')
        self.assertEqual(self.client.calls,[])
    def test_foreign_or_incomplete_readback_rejected(self):
        b=self.bridge();b.put('fixture-native-saved');self.client.saved={**self.value,'idempotency_key':'foreign'}
        with self.assertRaisesRegex(ValueError,'receipt'):b.get('fixture-native-saved')
    def test_browser_cannot_select_snapshot_path(self):
        from types import SimpleNamespace
        app=SimpleNamespace(root=self.root,cloud_client=None)
        with self.assertRaisesRegex(ValueError,'request'):N.dispatch(app,'native_saved_put',{'idempotency_key':'fixture','snapshot':'/private'})
def receipt(value):
    return {'schema':'crowd-owner-native-saved-receipt-v1','batch_id':'12345678-1234-4234-8234-123456789012','batch_hash':N.batch_hash(value),'snapshot_sha256':value['source']['snapshot_sha256'],'record_count':len(value['records']),'record_hashes':[{k:r[k]for k in ('native_table','native_id','record_sha256')}for r in value['records']],'redacted_fields':[{k:r[k]for k in ('native_table','native_id')}|{'field':'note_url'}for r in value['records']],'created_at':'2026-10-22T00:00:00Z','source_kind':'native_saved','reward_eligible':False}
if __name__=='__main__':unittest.main()
