import copy
import csv
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch
from PIL import Image
from saved_media_attachments import SavedMediaAttachments,sha,canonical,decode_bytes
from results_store import ResultsStore

class Attachments(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve();self.rid=str(uuid.uuid4());self.run=self.root/'runs'/self.rid;self.run.mkdir(parents=True)
        self.mid='a'*64;self.url='http://sns-webpic-qc.xhscdn.com/public?keep=all'
        self.ref={'media_id':self.mid,'platform':'xiaohongshu','content_id':'note','kind':'image','url':self.url,'status':'reference_only','source_kind':'mediacrawler_api','reward_eligible':False}
        body={'kind':'content','platform':'xiaohongshu','content_id':'note','author_id':'author','body':'=Full original body','published_at_reported':1700000000,'origin':{'run_id':self.rid,'operation_id':self.rid,'executor':'mediacrawler_pro','observation_sha256':'b'*64},'media':[copy.deepcopy(self.ref)]};body['record_hash']=sha(body)
        records=[body]
        for i in range(94):
            row={'kind':'comment','platform':'xiaohongshu','content_id':'note','comment_id':'comment'+str(i),'parent_comment_id':'','text':'full comment '+str(i),'author_id':'author','published_at_reported':1700000000};row['record_hash']=sha(row);records.append(row)
        self.norm={'run_id':self.rid,'source_kind':'mediacrawler_api','reward_eligible':False,'run_state':'completed','records':records,'media':[self.ref]}
        manifest={'run_id':self.rid,'executor':{'backend':'pro'},'request':{'platform':'xhs'}};status={'run_id':self.rid,'state':'completed'}
        self.files={}
        for name,value in [('manifest',manifest),('status',status),('normalized',self.norm)]:
            path=self.run/(name+'.json');path.write_text(canonical(value));self.files[path.name]=sha(path.read_bytes())
        self.asset=self.root/'image.png';Image.new('RGB',(13,11),(10,20,30)).save(self.asset)
        self.receipt={'state':'downloaded_not_imported_or_cloud_saved','run_id':self.rid,'media_id':self.mid,'source_files_unchanged':True,'platform_http_requests':1,'cloud_ack':False,'reference_sha256':sha(self.ref),'source_record_hash':body['record_hash'],'asset_file':self.asset.name,'asset_sha256':sha(self.asset.read_bytes()),'bytes':self.asset.stat().st_size,'content_type':'image/png','url_sha256':sha(self.url),'transport_url_sha256':sha(self.url.replace('http:','https:',1)),**{k: self.files[v] for k,v in [('normalized_sha256','normalized.json'),('manifest_sha256','manifest.json'),('status_sha256','status.json')]}}
        self.store=ResultsStore(self.root/'temporary-store')
        for i in range(71):self.store.ingest({'run_id':str(uuid.uuid4()),'source':{'seed':i},'records':[]})
        self.store.ingest(self.norm)
        self.old72={f:self.store.export(f,revision=72)['data'] for f in ('json','jsonl','csv')}
        self.adapter=SavedMediaAttachments(self.root/'owned',lambda rid:self.run if rid==self.rid else self.root/'unknown',self.store)
    def tearDown(self):self.tmp.cleanup()
    def attach(self):return self.adapter.attach(self.rid,self.mid,self.asset,self.receipt)
    def assert_originals(self):
        self.assertEqual(self.files,{n:sha((self.run/n).read_bytes()) for n in self.files})
        for f in self.old72:self.assertEqual(self.store.export(f,revision=72)['data'],self.old72[f])
    def test_json_array_null_deep_and_encoding_are_fixed_value_errors(self):
        result=self.attach();virtual=result['media']['path'];asset=self.adapter.resolve(self.rid,virtual)
        files=[asset.parent/'attachment.json',asset.parent/'registration.json',self.run/'manifest.json',self.run/'status.json',self.run/'normalized.json']
        malformed=[b'[]',b'null',b'\xff',b'{"nested":'*40+b'null'+b'}'*40,b'{"nested":'*1100+b'null'+b'}'*1100]
        for path in files:
            original=path.read_bytes()
            try:
                for raw in malformed:
                    with self.subTest(file=path.name,kind=len(raw)):
                        path.write_bytes(raw)
                        with self.assertRaises(ValueError):self.adapter.resolve(self.rid,virtual)
            finally:path.write_bytes(original)
        self.assertEqual(self.adapter.resolve(self.rid,virtual),asset);self.assert_originals()

    def test_decoder_bomb_fixed_error_and_system_exit_preserved(self):
        with patch.object(Image,'open',side_effect=Image.DecompressionBombError('PRIVATE_FILENAME')):
            with self.assertRaisesRegex(ValueError,'^attachment_decode_failed$'):decode_bytes(b'bytes')
        with patch.object(Image,'open',side_effect=SystemExit(73)):
            with self.assertRaises(SystemExit) as error:decode_bytes(b'bytes')
            self.assertEqual(error.exception.code,73)

    def test_all_sidecar_fields_typed_and_extra_missing_rejected(self):
        result=self.attach();virtual=result['media']['path'];asset=self.adapter.resolve(self.rid,virtual);sidecar=asset.parent/'attachment.json';original=json.loads(sidecar.read_text())
        fields={'platform':'weibo','content_id':'other','comment_id':'other','media_kind':'video',
                'source_observation_sha256':'0'*64,'source_url_sha256':'0'*64,'transport_url_sha256':'0'*64,
                'normalized_sha256':'0'*64,'cloud_ack':True,'reward_eligible':True}
        for field,value in fields.items():
            with self.subTest(field=field):
                mutated={**original,field:value};sidecar.write_text(canonical(mutated))
                with self.assertRaises(ValueError):self.adapter.resolve(self.rid,virtual)
        for mutated in [{**original,'extra':'unexpected'}, {k:v for k,v in original.items() if k!='cloud_ack'}, {**original,'decoded':{**original['decoded'],'frames':True}}]:
            sidecar.write_text(canonical(mutated))
            with self.assertRaises(ValueError):self.adapter.resolve(self.rid,virtual)
        sidecar.write_text(canonical(original));self.assertEqual(self.adapter.resolve(self.rid,virtual),asset)

    def test_ingest_failure_pending_not_playable_then_retry_recovers(self):
        with patch.object(self.store,'ingest',side_effect=OSError('synthetic store failure')):
            with self.assertRaises(OSError):self.attach()
        sidecar=next((self.adapter.root/self.rid).glob('*/attachment.json'));virtual=json.loads(sidecar.read_text())['path']
        self.assertFalse((sidecar.parent/'registration.json').exists())
        with self.assertRaisesRegex(ValueError,'not_registered'):self.adapter.resolve(self.rid,virtual)
        self.assertEqual(self.store.export()['results_revision'],72)
        result=self.attach();self.assertEqual(result['results']['results_revision'],73)
        self.assertTrue(self.adapter.resolve(self.rid,virtual).is_file());self.assert_originals()

    def test_registration_write_failure_and_forgery_are_not_playable(self):
        original_publish=self.adapter._publish
        def publish(path,data):
            if path.name=='registration.json':raise OSError('synthetic registration write failure')
            return original_publish(path,data)
        with patch.object(self.adapter,'_publish',publish):
            with self.assertRaises(OSError):self.attach()
        sidecar=next((self.adapter.root/self.rid).glob('*/attachment.json'));virtual=json.loads(sidecar.read_text())['path']
        self.assertEqual(self.store.export()['results_revision'],73)
        with self.assertRaisesRegex(ValueError,'not_registered'):self.adapter.resolve(self.rid,virtual)
        result=self.attach();self.assertTrue(result['results']['duplicate_import']);self.assertEqual(result['results']['results_revision'],73)
        self.assertTrue(self.adapter.resolve(self.rid,virtual).is_file())
        registration=sidecar.parent/'registration.json';value=json.loads(registration.read_text());value['import_revision']=True;registration.write_text(canonical(value))
        with self.assertRaisesRegex(ValueError,'not_registered'):self.adapter.resolve(self.rid,virtual)
        value['import_revision']=72;registration.write_text(canonical(value))
        with self.assertRaises(ValueError):self.adapter.resolve(self.rid,virtual)
        self.assert_originals()

    def test_ingest_real_store_revision73_preserves95_and_three_formats(self):
        result=self.attach();self.assertEqual(result['results']['results_revision'],73)
        self.assertFalse(result['cloud_ack']);self.assertTrue(result['original_source_files_unchanged'])
        exports={f:self.store.export(f) for f in ('json','jsonl','csv')};payload=json.loads(exports['json']['data']);self.assertEqual(payload['row_count'],96)
        old=[r for r in json.loads(self.old72['json'])['items'] if r['kind']!='media'];self.assertEqual(len(old),95);current=[r for r in payload['items'] if r['kind']!='media'];self.assertEqual(current,old)
        lines=[json.loads(line) for line in exports['jsonl']['data'].decode().splitlines()];self.assertEqual(lines[1:],payload['items'])
        rows=list(csv.DictReader(io.StringIO(exports['csv']['data'].decode('utf-8-sig'))));self.assertEqual(len(rows),96)
        for item,row in zip(payload['items'],rows):
            for field in rows[0]:
                value=item if field=='record' else item.get(field);text=canonical(value) if isinstance(value,(dict,list)) else '' if value is None else str(value)
                if text.lstrip(' \t\r\n\v\f\ufeff').startswith(('=','+','-','@')):text="'"+text
                self.assertEqual(row[field],text)
        self.assertEqual(self.adapter.resolve(self.rid,result['media']['path']).read_bytes(),self.asset.read_bytes())
        self.assert_originals()
    def test_repeat_is_idempotent_and_does_not_touch_old_entities(self):
        a=self.attach();b=self.attach();self.assertEqual(a['attachment_id'],b['attachment_id']);self.assertTrue(b['results']['duplicate_import']);self.assertEqual(b['results']['results_revision'],73);self.assert_originals()
    def test_forged_receipt_and_types_cannot_create_revision(self):
        for field,value in [('run_id',str(uuid.uuid4())),('reference_sha256','0'*64),('source_record_hash','0'*64),('transport_url_sha256','0'*64),('platform_http_requests',True),('bytes',True),('normalized_sha256','0'*64),('asset_sha256','0'*64),('content_type','video/mp4')]:
            with self.subTest(field=field):
                with self.assertRaises(ValueError):self.adapter.attach(self.rid,self.mid,self.asset,{**self.receipt,field:value})
                self.assertEqual(self.store.export()['results_revision'],72)
        self.assert_originals()
    def test_nonimage_and_symlink_and_foreign_path_rejected(self):
        bad=self.root/'not-image.png';bad.write_bytes(b'NOT_AN_IMAGE')
        receipt={**self.receipt,'asset_file':bad.name,'asset_sha256':sha(bad.read_bytes()),'bytes':bad.stat().st_size}
        with self.assertRaises(Exception):self.adapter.attach(self.rid,self.mid,bad,receipt)
        link=self.root/'symlink.png';link.symlink_to(self.asset)
        with self.assertRaises(ValueError):self.adapter.attach(self.rid,self.mid,link,self.receipt)
        with self.assertRaises(ValueError):self.adapter.resolve(self.rid,'attachments/../../private')
        self.assert_originals()
    def test_tampered_asset_or_sidecar_or_source_rejected_on_playback(self):
        result=self.attach();virtual=result['media']['path'];path=self.adapter.resolve(self.rid,virtual);original=path.read_bytes();path.write_bytes(b'CORRUPTED')
        with self.assertRaises(Exception):self.adapter.resolve(self.rid,virtual)
        path.write_bytes(original);sidecar=path.parent/'attachment.json';saved=sidecar.read_bytes();row=json.loads(saved);row['source_record_hash']='0'*64;sidecar.write_text(canonical(row))
        with self.assertRaises(ValueError):self.adapter.resolve(self.rid,virtual)
        sidecar.write_bytes(saved);(self.run/'status.json').write_text('{}')
        with self.assertRaises(ValueError):self.adapter.resolve(self.rid,virtual)

if __name__=='__main__':unittest.main()
