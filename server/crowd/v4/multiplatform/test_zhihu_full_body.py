import hashlib
import json
from pathlib import Path
import unittest

from mc_runner import normalize, ID_KEYS


class ZhihuFullBody(unittest.TestCase):
    def test_full_saved_text_preferred_only_for_zhihu(self):
        for platform in ID_KEYS:
            row={ID_KEYS[platform]:'123','content_type':'answer' if platform=='zhihu' else 'video',
                 'desc':'fixture excerpt','content_text':'fixture full saved text','title':'fixture'}
            record=normalize(platform,'content',row,{})
            self.assertEqual(record['body'],'fixture full saved text' if platform=='zhihu' else 'fixture excerpt')
            self.assertEqual(record['text_status'],'reported')

    def test_empty_absent_or_nontext_full_value_uses_original_fallback(self):
        for full in ('',None,False,123,{}):
            row={'content_id':'123','content_type':'zvideo','desc':'fixture video description','content_text':full}
            self.assertEqual(normalize('zhihu','content',row,{})['body'],'fixture video description')
        self.assertEqual(normalize('zhihu','content',{'content_id':'123','desc':'fixture description'}, {})['body'],'fixture description')

    def test_selected_body_drives_truncation_and_sensitive_flags(self):
        row={'content_id':'123','content_type':'article','desc':'fixture excerpt','content_text':'文'*24001}
        record=normalize('zhihu','content',row,{})
        self.assertEqual(len(record['body']),24000)
        self.assertTrue(record['text_truncated']);self.assertEqual(record['text_completeness'],'partial')
        record=normalize('zhihu','content',{**row,'content_text':'password=fixture'}, {})
        self.assertIsNone(record['body']);self.assertEqual(record['text_status'],'withheld_sensitive')

    def test_actual_source_full523_excerpt205_readonly_original_records_protected(self):
        workspace=Path(__file__).resolve().parents[5]
        run=workspace/'.crowd-launch/seven-platform-live/zhihu/runs/a42307ea-5684-414f-a4dc-11fa628ca098'
        if not run.is_dir():self.skipTest('local real SDK fixture not present')
        files=[f for f in run.rglob('*') if f.is_file() and not f.is_symlink()]
        before={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
        source=next((run/'output/zhihu/jsonl').glob('*contents*.jsonl'))
        raw=json.loads(source.read_text().splitlines()[0])
        self.assertEqual(len(raw['content_text']),523);self.assertEqual(len(raw['desc']),205)
        record=normalize('zhihu','content',raw,{'run_id':run.name,'line':1})
        self.assertEqual(record['body'],raw['content_text']);self.assertEqual(len(record['body']),523)
        old=json.loads((run/'normalized.json').read_text())
        self.assertEqual(len(next(row for row in old['records'] if row['kind']=='content')['body']),205)
        self.assertEqual(before,{str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in files})


if __name__=='__main__':unittest.main()
