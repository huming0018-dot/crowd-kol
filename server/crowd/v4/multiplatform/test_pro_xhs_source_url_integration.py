"""Temp only. Reuses unchanged existing synthetic media fixture, no platform network."""
import importlib.util,os,json,unittest
from pathlib import Path
p=Path(os.environ.get('CROWD_XHS_BASE_TESTS',str(Path(__file__).parent/'tests/pro-xhs-images')))/'test_media.py'
spec=importlib.util.spec_from_file_location('original_media_fixture',p);base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
import pro_xhs_media as native
import saved_media_attachments as attachment
import pro_executor as pro
import mc_runner as m
from results_store import ResultsStore
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
import time

@contextmanager
def fixed_export_clock():
 # openpyxl 3.1.5 core/save clocks and ZipFile writestr/from_file timestamps.
 class FixedDateTime(datetime):
  @classmethod
  def now(cls,tz=None):return cls(2026,1,1,tzinfo=timezone.utc).astimezone(tz) if tz else cls(2026,1,1)
 clock=SimpleNamespace(datetime=FixedDateTime,timezone=timezone)
 zip_clock=SimpleNamespace(time=time.time,localtime=lambda *args:(2026,1,1,0,0,0,3,1,0))
 with patch('openpyxl.packaging.core.datetime',clock),patch('openpyxl.writer.excel.datetime',clock),patch('zipfile.time',zip_clock):yield

class NativeSourceURL(unittest.TestCase):
 @fixed_export_clock()
 def check(self,legacy):
  f=base.Media('test_four_images_and_original_refs_no_target_increment');f.setUp()
  try:
   f.row['image_list']=f.row['image_list'].replace('https://','http://');f.save_row();f.payload['note']=[f.row];items=native.plan(f.run,f.manifest);f.payload['response']={'xhs_plan_sha256':native.digest(items)}
   self.assertTrue(all(x['url'].startswith('http://')for x in items));result=native.execute_payload(f.payload,launch=f.launch);self.assertEqual(f.ledger.snapshot()['used'],8)
   if legacy:
    intent=m.read(f.run/'xhs-pro-media-intent.json');del intent['transport_policy'];intent['plan']=[{**x,'url':x['url'].replace('http:','https:',1)}for x in intent['plan']];m.write(f.run/'xhs-pro-media-intent.json',intent)
    result['assets']=[{**x,'transport_url':x['transport_url'].replace('http:','https:',1)}for x in result['assets']];m.write(f.run/'hybrid-media-result.json',result)
   self.assertEqual(__import__('pro_media_integration').summary(f.run,f.manifest),result)
   records,refs,_=pro.import_records(f.run,f.manifest);norm={'run_id':f.rid,'run_state':'completed','source_kind':'mediacrawler_api','reward_eligible':False,'records':records,'media':refs};m.write(f.run/'normalized.json',norm);m.write(f.run/'status.json',{'run_id':f.rid,'state':'completed'})
   store=ResultsStore(f.root/'results');store.ingest(norm);old={fmt:store.export(fmt,revision=1)['data']for fmt in ('json','jsonl','csv','xlsx')};adapter=attachment.SavedMediaAttachments(f.root/'assets',lambda _:f.run,store);saved=adapter.attach_native(f.rid,refs[0]['media_id']);asset=adapter.resolve(f.rid,saved['media']['path']);self.assertTrue(asset.is_file());sidecar=asset.parent/'attachment.json';raw=sidecar.read_bytes();value=json.loads(raw);expected=attachment.reference_transport(refs[0])if legacy else refs[0]['url'];self.assertEqual(value['transport_url_sha256'],attachment.sha(expected));self.assertEqual(value['source_url_sha256'],attachment.sha(refs[0]['url']));self.assertEqual(adapter.resolve(f.rid,saved['media']['path']),asset);self.assertEqual(sidecar.read_bytes(),raw)
   for fmt,data in old.items():self.assertEqual(store.export(fmt,revision=1)['data'],data)
   if not legacy:
    changed=m.read(f.run/'hybrid-media-result.json');changed['assets'][0]['transport_url']=changed['assets'][0]['transport_url'].replace('http:','https:',1);m.write(f.run/'hybrid-media-result.json',changed)
    with self.assertRaises(ValueError):adapter.resolve(f.rid,saved['media']['path'])
  finally:f.tearDown()
 def test_new_native_http_saved_receipt_and_legacy_four_exports(self):self.check(False)
 def test_old_completed_https_transport_sidecar_unchanged(self):self.check(True)
if __name__=='__main__':unittest.main()
