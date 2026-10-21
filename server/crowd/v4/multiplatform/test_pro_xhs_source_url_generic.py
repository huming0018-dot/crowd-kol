from pathlib import Path
import importlib.util,json,os,unittest
mp=Path(os.environ.get('CROWD_XHS_MP',str(Path(__file__).parent)));spec=importlib.util.spec_from_file_location('fixture',mp/'tests/pro-xhs-images/test_media.py');fmod=importlib.util.module_from_spec(spec);spec.loader.exec_module(fmod)
spec=importlib.util.spec_from_file_location('tested_attachments',os.environ.get('ATTACHMENT_SOURCE',str(Path(__file__).with_name('saved_media_attachments.py'))));a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
import pro_xhs_media as native,pro_executor as pro,mc_runner as m
from results_store import ResultsStore
class ExistingManual(unittest.TestCase):
 def test_generic_https_receipt_still_attaches_and_resolves_new_native_run(self):
  f=fmod.Media('test_four_images_and_original_refs_no_target_increment');f.setUp()
  try:
   f.row['image_list']=f.row['image_list'].replace('https://','http://');f.save_row();f.payload['note']=[f.row];f.payload['response']={'xhs_plan_sha256':native.digest(native.plan(f.run,f.manifest))};result=native.execute_payload(f.payload,launch=f.launch)
   records,refs,_=pro.import_records(f.run,f.manifest);m.write(f.run/'normalized.json',{'run_id':f.rid,'run_state':'completed','source_kind':'mediacrawler_api','reward_eligible':False,'records':records,'media':refs});m.write(f.run/'status.json',{'run_id':f.rid,'state':'completed'})
   store=ResultsStore(f.root/'store');store.ingest(m.read(f.run/'normalized.json'));adapter=a.SavedMediaAttachments(f.root/'saved',lambda _:f.run,store);ref,body,files=a.verify_source(f.run,refs[0]['media_id']);asset=f.run/result['assets'][0]['path'];data=asset.read_bytes()
   receipt={'state':'downloaded_not_imported_or_cloud_saved','source_files_unchanged':True,'run_id':f.rid,'media_id':ref['media_id'],'platform_http_requests':1,'cloud_ack':False,'reference_sha256':a.sha(ref),'source_record_hash':body['record_hash'],'asset_file':asset.name,'asset_sha256':a.sha(data),'bytes':len(data),'url_sha256':a.sha(ref['url']),'transport_url_sha256':a.sha(a.reference_transport(ref)),'normalized_sha256':files['normalized.json'],'manifest_sha256':files['manifest.json'],'status_sha256':files['status.json'],'content_type':'image/png'}
   bad={**receipt,'native_stage_verified':True,'transport_policy':'native_source_url_v1','transport_url_sha256':a.sha(ref['url'])}
   with self.assertRaisesRegex(ValueError,'attachment_transport_binding_invalid'):adapter.attach(f.rid,ref['media_id'],asset,bad)
   attached=adapter.attach(f.rid,ref['media_id'],asset,receipt);resolved=adapter.resolve(f.rid,attached['media']['path']);self.assertEqual(resolved.read_bytes(),data)
  finally:f.tearDown()
if __name__=='__main__':unittest.main()
