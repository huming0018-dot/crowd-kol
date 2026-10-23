"""No network/SDK: original URL validator plus page projection invariants."""
import copy,unittest
from pro_tieba_entry import public_detail,media_projection,verify_media_source,source_assets
from pro_tieba_adapter import digest,TiebaStop
URL='https://imgsa.baidu.com/'
def raw(page,urls):
 return {'thread':{'id':123},'first_floor':{'id':123,'content':[{'type':0,'text':'body'}]},'post_list':[{'id':page+100,'content':[{'type':3,'origin_src':u}for u in urls]}],'user_list':[],'page':{'total_page':2}}
def page(n,urls):
 value=public_detail(raw(n,urls));return {'page':n,'raw':value,'sha256':digest(value)}
class Pages(unittest.TestCase):
 def test_later_page_unique_media_retained_and_downloader_compact(self):
  pages=[page(1,[URL+'a.png']),page(2,[URL+'b.png'])];projection,refs=media_projection(pages)
  self.assertEqual([x['transport_url']for x in source_assets(projection)],[URL+'a.png',URL+'b.png']);self.assertEqual([x['page']for x in refs],[1,2]);self.assertEqual(refs[1]['page_sha256'],pages[1]['sha256']);self.assertEqual(projection['first_floor'],pages[0]['raw']['first_floor'])
 def test_duplicate_across_pages_dedup_bytes_plan_not_origins(self):
  pages=[page(1,[URL+'a.png']),page(2,['http://imgsa.baidu.com/a.png',URL+'a.png'])];projection,refs=media_projection(pages)
  self.assertEqual(len(source_assets(projection)),1);self.assertEqual(len(refs),3);self.assertEqual(refs[1]['original_url'],'http://imgsa.baidu.com/a.png');self.assertEqual([x['page']for x in refs],[1,2,2])
 def test_combined_over3_rejected_not_truncated(self):
  pages=[page(1,[URL+'a.png',URL+'b.png']),page(2,[URL+'c.png',URL+'d.png'])]
  self.assertEqual(len(source_assets(pages[0]['raw'])),2)
  with self.assertRaisesRegex(TiebaStop,'exceeds_existing_scope'):media_projection(pages)
 def test_later_raw_hash_or_reference_tamper_refused(self):
  pages=[page(1,[URL+'a.png']),page(2,[URL+'b.png'])];projection,refs=media_projection(pages);source={'schema_version':2,'pages':pages,'raw':projection,'references':refs};self.assertEqual(len(verify_media_source(source)),2)
  for mutation in ['raw','reference','aggregate']:
   value=copy.deepcopy(source)
   if mutation=='raw':value['pages'][1]['raw']['post_list'][0]['content'][0]['origin_src']=URL+'changed.png'
   if mutation=='reference':value['references'][1]['page']=1
   if mutation=='aggregate':value['raw']['post_list'].pop()
   with self.subTest(mutation=mutation),self.assertRaises(ValueError):verify_media_source(value)
 def test_page_reorder_gap_and_wrong_type_refused(self):
  for pages in [[page(2,[])],[page(1,[]),page(1,[])],[{**page(1,[]),'page':True}]]:
   with self.assertRaises(TiebaStop):media_projection(pages)
 def test_no_media_projection_preserves_empty_explicit_refs(self):
  projection,refs=media_projection([page(1,[])]);self.assertEqual(refs,[]);self.assertEqual(source_assets(projection),[])
 def test_unknown_parts_cannot_be_sanitized_into_verified_zero(self):
  for part in ({'text':'untyped content'},{'unrecognized_media':'https://example.invalid/image.png'},
               {'type':0,'text':'body','unrecognized_media':'https://example.invalid/image.png'}):
   value=raw(1,[]);value['first_floor']['content']=[part]
   with self.subTest(part=part),self.assertRaisesRegex(ValueError,'tieba_zero_media_unverified'):public_detail(value)
if __name__=='__main__':unittest.main()
