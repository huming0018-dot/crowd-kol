"""Offline synthetic KS fixture through original licensed SDK; no platform source.

Run with the existing Pro Python:
  CROWD_KS_SDK=<licensed-SDK-root> python -B -m unittest test_pro_ks_projection
The same-repo own modules and synthetic fixtures/pro-ks-saved-fixture.json are
used. Missing licensed SDK/input fails explicitly; no dependency installation,
credentials, browser or account profile is requested. This is not authentication.
"""
import copy,json,os,sys,unittest
from pathlib import Path
HERE=Path(__file__).resolve().parent
SDK=Path(os.environ['CROWD_KS_SDK']);sys.path[:0]=[str(HERE),str(SDK)]
from pro_ks_adapter import Evidence,digest
FIXTURE=Path(os.environ.get('CROWD_KS_SAVED_FIXTURE',HERE/'fixtures/pro-ks-saved-fixture.json'));RAW=json.loads(FIXTURE.read_text())
class Tests(unittest.TestCase):
 def data(self):
  d=copy.deepcopy(RAW);e=Evidence(d['video_id']);e.detail=d['detail'];e.pages=d['pages'];return e,d
 def project(self,e,d):return e.project(d['videos'],d['comments'],d['run_id'])
 def test_actual_native_saved_fixture(self):
  e,d=self.data();p=self.project(e,d);self.assertEqual(len(p['records']),5);self.assertEqual(len(p['source']['media_references']),2);self.assertEqual(p['source']['capture_sha256'],digest({'detail':d['detail'],'pages':d['pages']}))
 def test_missing_cursor_refused(self):
  e,d=self.data();e.pages[0]['raw'].pop('pcursorV2');e.pages[0]['sha256']=digest(e.pages[0]['raw'])
  with self.assertRaisesRegex(ValueError,'terminal_unverified'):self.project(e,d)
 def test_recorded_reply_error_refused(self):
  e,d=self.data();e.failed('reply','')
  with self.assertRaisesRegex(ValueError,'capture_unknown'):self.project(e,d)
 def test_changed_saved_comment_refused(self):
  e,d=self.data();d['comments'][0]['content']='tampered'
  with self.assertRaisesRegex(ValueError,'saved_comment_changed'):self.project(e,d)
 def test_other_video_id_refused(self):
  e,d=self.data();e.video_id='other'
  with self.assertRaisesRegex(ValueError,'content_binding'):self.project(e,d)
 def test_foreign_reply_parent_refused(self):
  e,d=self.data();next(x for x in e.pages if x['kind']=='reply')['parent']='999'
  with self.assertRaisesRegex(ValueError,'parent_scope'):self.project(e,d)
 def test_page_hash_tamper_refused(self):
  e,d=self.data();e.pages[0]['raw']['rootCommentsV2'][0]['content']='changed'
  with self.assertRaisesRegex(ValueError,'page_changed'):self.project(e,d)
 def test_incomplete_reply_pages_refused(self):
  e,d=self.data();e.pages=[x for x in e.pages if x['cursor']!='reply-next']
  with self.assertRaisesRegex(ValueError,'pages_incomplete'):self.project(e,d)
 def test_replay_refused(self):
  e,d=self.data();e.pages.append(copy.deepcopy(e.pages[0]))
  with self.assertRaisesRegex(ValueError,'cursor_or_replay'):self.project(e,d)
 def test_declared_reply_count_typed_nonnegative(self):
  for value in (None,True,-1,2.0,'2'):
   e,d=self.data();page=next(x for x in e.pages if x['kind']=='root');page['raw']['rootCommentsV2'][0]['commentCount']=value;page['sha256']=digest(page['raw'])
   with self.subTest(value=value),self.assertRaisesRegex(ValueError,'reply_count_unverified'):self.project(e,d)
 def test_declared_reply_count_cannot_disagree_with_flag(self):
  e,d=self.data();page=next(x for x in e.pages if x['kind']=='root');page['raw']['rootCommentsV2'][0]['commentCount']=0;page['sha256']=digest(page['raw'])
  with self.assertRaisesRegex(ValueError,'reply_count_unverified'):self.project(e,d)
 def test_missing_second_reply_with_terminal_and_rehash_refused(self):
  e,d=self.data();replies=[x for x in e.pages if x['kind']=='reply'];e.pages.remove(replies[1]);replies[0]['raw']['pcursorV2']='no_more';replies[0]['sha256']=digest(replies[0]['raw']);d['comments']=[x for x in d['comments']if x['comment_id']!='202']
  with self.assertRaisesRegex(ValueError,'reply_count_mismatch'):self.project(e,d)
 def test_long_raw_caption_exact_utf8_and_native_split(self):
  e,d=self.data();p=self.project(e,d);raw=d['detail']['visionVideoDetail']['photo']['caption'];record=p['records'][0]
  self.assertGreater(len(raw),500);self.assertEqual(record['raw_caption']['text'].encode(),raw.encode());self.assertEqual(record['raw_caption']['utf8_sha256'],__import__('hashlib').sha256(raw.encode()).hexdigest());self.assertEqual(record['title'],raw);self.assertEqual(record['body'],raw);self.assertEqual(record['native_projection']['title'],raw[:500]);self.assertEqual(record['native_projection']['body'],raw[:500])
 def test_long_comment_unchanged(self):
  e,d=self.data();p=self.project(e,d);r=next(x for x in p['records']if x.get('comment_id')=='101');sql=next(x for x in d['comments']if x['comment_id']=='101');self.assertGreater(len(sql['content']),500);self.assertEqual(r['text'],sql['content'])
 def test_caption_source_binding_not_guessed(self):
  e,d=self.data();e.detail['visionVideoDetail']['photo']['caption']='foreign caption'
  with self.assertRaisesRegex(ValueError,'saved_content_changed'):self.project(e,d)
 def test_native_saved_title_tamper_refused(self):
  e,d=self.data();d['videos'][0]['title']='tampered native title'
  with self.assertRaisesRegex(ValueError,'saved_content_changed'):self.project(e,d)
if __name__=='__main__':unittest.main()
