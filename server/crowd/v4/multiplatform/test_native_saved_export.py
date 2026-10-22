"""Synthetic raw native rows and genuine-shape receipts, no SDK/cloud/real data."""
import copy,hashlib,json,tempfile,unittest,uuid
from pathlib import Path
import owner_native_saved as N
import native_saved_export as E

NOTE='a'*24
def fixture():
 def row(table,cid,parent=''):
  r={key:''for key in N.FIELDS[table]};r.update(id=1,nickname=None,creator_hash='fixture',add_ts=1,last_modify_ts=2,note_id=NOTE,note_url='https://www.xiaohongshu.com/explore/'+NOTE+'?xsec_token=PRIVATE_FIXTURE&xsec_source=pc')
  if table=='xhs_note':r.update(type='normal',title='原题😀\n保留',desc='全文 e\u0301\n第二行',time=3,last_update_time=4,liked_count='0007',comment_count='95',image_list='["https://fixture.xhscdn.com/a.png"]')
  else:r.update(comment_id=cid,parent_comment_id=parent,content='评论😀\n'+cid,create_time=3,sub_comment_count='0',like_count='0003',pictures='[]')
  return N._record(table,r,NOTE)
 roots=[f'{i:024x}'for i in range(1,45)];records=[row('xhs_note',NOTE)]+[row('xhs_note_comment',cid)for cid in roots]+[row('xhs_note_comment',f'{i:024x}',roots[0])for i in range(45,96)]
 value={'schema':N.SCHEMA,'idempotency_key':'synthetic-four-formats','source':{'platform':'xiaohongshu','kind':'mediacrawler_pro_native_sqlite','sdk_commit':'d'*40,'snapshot_sha256':'e'*64},'records':records}
 receipt={'schema':'crowd-owner-native-saved-receipt-v1','batch_id':str(uuid.UUID(int=1)),'batch_hash':N.batch_hash(value),'snapshot_sha256':'e'*64,'record_count':96,'record_hashes':[{k:x[k]for k in('native_table','native_id','record_sha256')}for x in records],'redacted_fields':[{k:x[k]for k in('native_table','native_id')}|{'field':'note_url'}for x in records],'created_at':'2026-10-22T00:00:00+00:00','source_kind':'native_saved','reward_eligible':False}
 return value,{'native_saved':receipt,'replayed':False,'content':copy.deepcopy(value)}
def rebind(value,get):
 get['content']=copy.deepcopy(value);r=get['native_saved'];r['batch_hash']=N.batch_hash(value);r['record_count']=len(value['records']);r['record_hashes']=[{k:x[k]for k in('native_table','native_id','record_sha256')}for x in value['records']];r['redacted_fields']=[{k:x[k]for k in('native_table','native_id')}|{'field':'note_url'}for x in value['records']]
class Tests(unittest.TestCase):
 def test_all_four_formats_roundtrip_96_typed_rows(self):
  value,get=fixture();bundle=E.formats(value,get)
  for fmt,body in bundle.items():
   with self.subTest(fmt=fmt):self.assertEqual(E.parse_records(fmt,body),value['records'])
  self.assertEqual(len(bundle),4);self.assertIsNone(value['records'][0]['record']['nickname']);self.assertEqual(value['records'][0]['record']['liked_count'],'0007')
 def test_html_injection_escaped_and_full_text_retained(self):
  value,get=fixture();x=value['records'][0];x['record']['desc']='</script><img src=x onerror=alert(1)>\n"&原文';x['record_sha256']=N.digest('crowd-owner-native-record-v1\n'+N.canonical({k:x[k]for k in('native_table','native_id','record')}));rebind(value,get)
  body=E.formats(value,get)['html'];self.assertNotIn(b'<img',body);self.assertNotIn(b'</script>',body);self.assertIn(b'&lt;img',body);self.assertEqual(E.parse_records('html',body),value['records']);self.assertNotIn('来源已审',body.decode());self.assertNotIn('material_traceability_only',body.decode())
 def test_wrong_receipt_or_content_rejected(self):
  for mode in('batch','content','reward','snapshot'):
   value,get=fixture()
   if mode=='batch':get['native_saved']['batch_hash']='0'*64
   elif mode=='content':get['content']['records'][0]['record']['desc']='changed'
   elif mode=='reward':get['native_saved']['reward_eligible']=True
   else:get['native_saved']['snapshot_sha256']='0'*64
   with self.assertRaises(ValueError):E.formats(value,get)
 def test_duplicate_wrong_parent_and_changed_record_hash_rejected(self):
  for mode in('duplicate','parent','hash'):
   value,get=fixture()
   if mode=='duplicate':value['records'][-1]=copy.deepcopy(value['records'][1])
   elif mode=='parent':value['records'][-1]['record']['parent_comment_id']='missing'
   else:value['records'][0]['record']['title']='changed'
   rebind(value,get)
   with self.assertRaises(ValueError):E.formats(value,get)
 def test_csv_large_typed_cell_and_unicode_newlines(self):
  value,get=fixture();value['records']=value['records'][:1];x=value['records'][0];x['record']['desc']='中😀\n'*20000;x['record_sha256']=N.digest('crowd-owner-native-record-v1\n'+N.canonical({k:x[k]for k in('native_table','native_id','record')}));rebind(value,get)
  self.assertEqual(E.parse_records('csv',E.formats(value,get)['csv']),value['records'])
 def test_create_only_exports_and_provenance(self):
  value,get=fixture()
  with tempfile.TemporaryDirectory()as folder:
   out=Path(folder).resolve()/'exports';manifest=E.write_exports(value,get,out)
   self.assertEqual(manifest['record_count'],96);self.assertEqual(manifest['batch_hash'],get['native_saved']['batch_hash']);self.assertFalse(manifest['cloud_media_bytes_saved']);self.assertEqual(set(manifest['files']),{'native.json','native.jsonl','native.csv','native.html'})
   for name,h in manifest['files'].items():self.assertEqual(hashlib.sha256((out/name).read_bytes()).hexdigest(),h)
   with self.assertRaises((ValueError,FileExistsError)):E.write_exports(value,get,out)
 def test_payload_size_limit_not_relaxed(self):
  value,get=fixture();value['records']=value['records'][:1];x=value['records'][0];x['record']['desc']='中😀\n'*30000;x['record_sha256']=N.digest('crowd-owner-native-record-v1\n'+N.canonical({k:x[k]for k in('native_table','native_id','record')}));rebind(value,get)
  with self.assertRaises(ValueError):E.formats(value,get)
 def test_local_media_metadata_bound_to_snapshot_not_cloud_bytes(self):
  value,get=fixture();media={'pass':True,'source_unchanged':True,'snapshot_unchanged':True,'snapshot_sha256':'e'*64,'assets':[{'bytes':68,'sha256':'1'*64,'format':'PNG','width':1,'height':1,'pixel_sha256':'2'*64}]}
  with tempfile.TemporaryDirectory()as folder:
   root=Path(folder).resolve();m=E.write_exports(value,get,root/'good',media)
   self.assertFalse(m['cloud_media_bytes_saved']);self.assertEqual(m['local_media'][0]['storage'],'local_only');self.assertEqual(m['local_media'][0]['bytes'],68)
   with self.assertRaises(ValueError):E.write_exports(value,get,root/'bad',{**media,'snapshot_sha256':'0'*64})
if __name__=='__main__':unittest.main()
