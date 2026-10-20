"""Synthetic same-run SQL/ref fixture. Never platform/source/cloud writes."""
import copy,hashlib,json,os,socket,sqlite3,sys,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import patch
BASE=Path(__file__).resolve().parent
MP=Path(os.environ['CROWD_XHS_MP']);sys.path.insert(0,str(MP))
import mc_runner as m,pro_executor as pro,pro_xhs_media as native
from shared_request_budget import RunRequestBudget,request_fingerprint
from PIL import Image
from saved_media_attachments import SavedMediaAttachments
from results_store import ResultsStore
class Media(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve();self.rid=str(uuid.uuid4());self.sid=str(uuid.uuid4());self.run=self.root/'runs'/self.rid;(self.run/'output').mkdir(parents=True)
  self.request=m.validate({'platform':'xhs','mode':'detail','targets':['a'*24],'max_items':1,'comments':False,'replies':False,'max_comments':20,'media':True,'source_executor':'pro','session_id':self.sid,'max_api_requests':14,'purpose':'noncommercial_research'})
  self.manifest={'run_id':self.rid,'request':self.request,'executor':{'backend':'pro'}};m.write(self.run/'manifest.json',self.manifest)
  self.db=sqlite3.connect(self.run/pro.DB_NAME);self.db.execute('CREATE TABLE vox_crawl_observation(operation_id TEXT,platform TEXT,kind TEXT,entity_id TEXT,payload TEXT)')
  self.row={'note_id':'a'*24,'type':'normal','title':'saved fixture only','desc':'Synthetic public body','image_list':','.join('https://ci.xhscdn.com/image-'+str(i) for i in range(4)),'user_id':'synthetic-author'}
  self.save_row();self.ledger=RunRequestBudget(self.run/'request-budget.json',self.rid,request_fingerprint(self.request),14,create=True)
  self.session=self.root/'sessions'/self.sid;self.session.mkdir(parents=True);m.write(self.session/'identity.json',{'platform':'xhs'});m.write(self.session/'pro-binding.json',{'platform':'xhs','client_id':'synthetic','cookiebridge_url':'http://127.0.0.1:8274','sign_url':'http://127.0.0.1:8990'})
  self.account=self.root/'accounts'/self.sid;self.account.mkdir(parents=True);m.write(self.account/'state.json',{'session_id':self.sid,'platform':'xhs','state':'authenticated','login_verified':True,'authorized_for_run':self.rid,'account_ref':'b'*64,'generation':1})
  self.deps=Path(os.environ['CROWD_XHS_AXIOS_ROOT']).resolve()
  files={str(p.relative_to(self.deps)):native.digest(p.read_bytes()) for p in self.deps.rglob('*') if p.is_file()}
  m.write(self.root/'pro-xhs-media.json',{'schema':'crowd-pro-xhs-download-manager-v1','manager_path':os.environ['CROWD_PRO_DOWNLOAD_MANAGER'],'manager_sha256':native.MANAGER_SHA,'axios_root':str(self.deps),'axios_files':files});os.chmod(self.root/'pro-xhs-media.json',0o600)
  self.payload={'run':str(self.run),'request_hash':request_fingerprint(self.request),'headers':{},'note':[self.row],'response':{'xhs_plan_sha256':native.digest(native.plan(self.run,self.manifest))}}
  self.network=patch.object(socket.socket,'connect',side_effect=AssertionError('NETWORK_FORBIDDEN'));self.network.start()
 def tearDown(self):self.network.stop();self.db.close();self.temp.cleanup()
 def save_row(self):self.db.execute('DELETE FROM vox_crawl_observation');self.db.execute('INSERT INTO vox_crawl_observation VALUES(?,?,?,?,?)',(self.rid,'xhs','topic','a'*24,m.canonical(self.row)));self.db.commit()
 def launch(self,items,folder):
  assets=[]
  for item in items:
   for method in ('HEAD','GET'):native.guard(self.run,{'method':method,'url':item['url'],'media_id':item['media_id']})
   p=folder/item['content_id']/(native.digest(item['media_id'].encode())+'.png');p.parent.mkdir(exist_ok=True);Image.new('RGB',(13,11),(10,20,30)).save(p)
   assets.append({'content_id':item['content_id'],'source_media_id':item['media_id'],'transport_url':item['url'],'path':str(p),'bytes':p.stat().st_size,'sha256':native.digest(p.read_bytes()),'media_engine':native.ENGINE,'content_engine':'mediacrawler_pro','platform':'xhs','kind':'image','source_kind':'mediacrawler_api','reward_eligible':False})
  return assets
 def test_original_xhs_extractor_saved_four_refs(self):
  sdk=Path(os.environ['CROWD_XHS_SDK']);sys.path.insert(0,str(sdk))
  from media_platform.xhs.extractor import XiaoHongShuExtractor
  raw={'note_id':'a'*24,'type':'normal','title':'Synthetic source title','desc':'Synthetic source body','user':{'user_id':'synthetic-author','nickname':'synthetic'},'image_list':[{'url_default':'https://ci.xhscdn.com/original-'+str(i)} for i in range(4)]}
  model=XiaoHongShuExtractor()._extract_note_from_dict(copy.deepcopy(raw));self.row=model.model_dump();self.save_row();items=native.plan(self.run,self.manifest)
  self.assertEqual([x['url'] for x in items],[x['url_default'] for x in raw['image_list']]);self.assertEqual(len(items),4);self.assertEqual(self.ledger.snapshot()['used'],0)
 def test_new_scope_supported(self):self.assertIsNone(pro.explicit_unsupported(self.request))
 def test_driver_missing_changed_or_symlink_refuses_before_sdk_probe(self):
  folder=self.root/'runtime';folder.mkdir();driver=folder/'pro_xhs_download.mjs';manifest=copy.deepcopy(self.manifest);manifest['executor']['root']=str(self.root/'licensed-sdk')
  for mode in ('missing','changed','symlink'):
   if driver.exists() or driver.is_symlink():driver.unlink()
   if mode=='changed':driver.write_text('not the frozen own driver')
   if mode=='symlink':driver.symlink_to(MP/'pro_xhs_download.mjs')
   with self.subTest(mode=mode),patch.object(native,'__file__',str(folder/'pro_xhs_media.py')),patch.object(pro,'probe',side_effect=AssertionError('SDK_PROBE_MUST_NOT_BE_REACHED')) as probe:
    with self.assertRaises(ValueError):pro.execute(self.run,manifest)
    probe.assert_not_called()
   self.assertEqual(self.ledger.snapshot()['used'],0)
 def test_four_images_and_original_refs_no_target_increment(self):
  before=self.row.copy();result=native.execute_payload(self.payload,launch=self.launch);self.assertEqual(len(result['assets']),4);self.assertEqual(self.ledger.snapshot()['used'],8);self.assertEqual(self.row,before);self.assertFalse(result['cloud_ack']);self.assertEqual(__import__('pro_media_integration').summary(self.run,self.manifest),result)
 def test_original_manager_to_real_budget_guard_chain(self):
  import subprocess,base64,io
  data=io.BytesIO();Image.new('RGB',(13,11),(10,20,30)).save(data,format='PNG')
  def launch(items,folder):
   env=os.environ.copy();env['PYTHONPATH']=str(MP)
   payload={'source':os.environ['CROWD_PRO_DOWNLOAD_MANAGER'],'root':str(folder),'items':items,'fixture_png':base64.b64encode(data.getvalue()).decode(),'run':str(self.run),'python':sys.executable,'guard_module':str(MP/'pro_xhs_media.py')}
   done=subprocess.run([os.environ['CROWD_PRO_NODE'],'--experimental-vm-modules',str(BASE/'test_node_fixture_runner.mjs')],input=json.dumps(payload).encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,timeout=10)
   self.assertEqual(done.returncode,0,done.stderr.decode());return json.loads(done.stdout)
  result=native.execute_payload(self.payload,launch=launch);self.assertEqual(len(result['assets']),4);self.assertEqual(self.ledger.snapshot()['used'],8)
 def test_real_axios_http_adapter_and_product_cli_no_sockets(self):
  import subprocess,base64,io
  deps=Path(os.environ['CROWD_XHS_AXIOS_ROOT']).resolve();cfg=m.read(self.root/'pro-xhs-media.json');cfg['axios_root']=str(deps);cfg['axios_files']={str(p.relative_to(deps)):native.digest(p.read_bytes()) for p in deps.rglob('*') if p.is_file()};m.write(self.root/'pro-xhs-media.json',cfg)
  data=io.BytesIO();Image.new('RGB',(13,11),(10,20,30)).save(data,format='PNG');fixture=self.root/'transport-fixture.json';calls=self.root/'http-calls.jsonl';m.write(fixture,{'png':base64.b64encode(data.getvalue()).decode(),'calls':str(calls)})
  def launch(items,folder):
   binding=native.dependency_binding(self.root);context=native.identity(self.run,self.manifest);env=os.environ.copy();env['PYTHONPATH']=str(MP);env['CROWD_XHS_HTTPS_FIXTURE']=str(fixture)
   payload={'binding':binding,'identity':context,'root':str(folder),'items':items,'run':str(self.run),'python':sys.executable,'guard_module':str(MP/'pro_xhs_media.py'),'timeout':3000}
   done=subprocess.run([os.environ['CROWD_PRO_NODE'],'--experimental-vm-modules','--require',str(BASE/'test_https_fixture.cjs'),str(MP/'pro_xhs_download.mjs')],input=json.dumps(payload).encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,timeout=10)
   self.assertEqual(done.returncode,0,done.stderr.decode());return json.loads(done.stdout)
  result=native.execute_payload(self.payload,launch=launch);self.assertEqual(len(result['assets']),4);self.assertEqual(self.ledger.snapshot()['used'],8);actual=[json.loads(l) for l in calls.read_text().splitlines()];self.assertEqual([r['method'] for r in actual],['HEAD','GET']*4)
 def test_typed_normal_no_image_needs_no_transport(self):
  self.row['image_list']='';self.save_row();self.payload['note']=[self.row];self.payload['response']={'xhs_plan_sha256':native.digest([])}
  result=native.execute_payload(self.payload,launch=lambda *_:self.fail('no HTTP for zero references'));self.assertEqual(result['assets'],[]);self.assertEqual(self.ledger.snapshot()['used'],0)
 def test_video_or_missing_type_is_not_verified_zero(self):
  for change in ({'type':'video','image_list':''},{'type':None,'image_list':''}):
   self.row.update(change);self.save_row()
   with self.assertRaisesRegex(ValueError,'images_only_scope'):native.plan(self.run,self.manifest)
 def test_stop_precedes_any_http(self):
  m.write(self.run/'stop.json',{});
  with self.assertRaises(SystemExit):native.execute_payload(self.payload,launch=self.launch)
  self.assertEqual(self.ledger.snapshot()['used'],0)
 def test_identity_change_between_head_and_get(self):
  def launch(items,folder):
   native.guard(self.run,{'method':'HEAD','url':items[0]['url'],'media_id':items[0]['media_id']});state=m.read(self.account/'state.json');state['generation']=2;m.write(self.account/'state.json',state)
   native.guard(self.run,{'method':'GET','url':items[0]['url'],'media_id':items[0]['media_id']})
  with self.assertRaises(ValueError):native.execute_payload(self.payload,launch=launch)
  self.assertEqual(self.ledger.snapshot()['used'],1);self.assertFalse((self.run/'hybrid-media-result.json').exists())
 def test_changed_observation_ref_denied(self):
  def launch(items,folder):self.row['image_list']+='https://ci.xhscdn.com/changed';self.save_row();native.guard(self.run,{'method':'HEAD','url':items[0]['url'],'media_id':items[0]['media_id']})
  with self.assertRaises(ValueError):native.execute_payload(self.payload,launch=launch)
  self.assertEqual(self.ledger.snapshot()['used'],0)
 def test_budget_exhausted_no_result_no_relaunch(self):
  for _ in range(13):self.ledger.debit('pro')
  with self.assertRaises(SystemExit):native.execute_payload(self.payload,launch=self.launch)
  self.assertFalse((self.run/'hybrid-media-result.json').exists())
  with self.assertRaises(FileExistsError):native.execute_payload(self.payload,launch=self.launch)
 def test_foreign_run_payload_denied(self):
  self.payload['request_hash']='0'*64
  with self.assertRaises(ValueError):native.execute_payload(self.payload,launch=self.launch)
  self.assertFalse((self.run/'xhs-pro-media-intent.json').exists())
 def test_tampered_asset_refuses_summary(self):
  result=native.execute_payload(self.payload,launch=self.launch);p=self.run/result['assets'][0]['path'];p.write_bytes(p.read_bytes()+b'changed')
  with self.assertRaises(ValueError):__import__('pro_media_integration').summary(self.run,self.manifest)
 def test_saved_attachment_native_path_preserves_old_exports(self):
  native.execute_payload(self.payload,launch=self.launch);records,refs,_=pro.import_records(self.run,self.manifest);norm={'run_id':self.rid,'run_state':'completed','source_kind':'mediacrawler_api','reward_eligible':False,'records':records,'media':refs};m.write(self.run/'normalized.json',norm);m.write(self.run/'status.json',{'run_id':self.rid,'state':'completed'})
  store=ResultsStore(self.root/'results');store.ingest(norm);old={f:store.export(f,revision=1)['data'] for f in ('json','jsonl','csv','xlsx')};adapter=SavedMediaAttachments(self.root/'assets',lambda rid:self.run,store);result=adapter.attach_native(self.rid,refs[0]['media_id']);self.assertTrue(adapter.resolve(self.rid,result['media']['path']).is_file())
  for f in old:self.assertEqual(store.export(f,revision=1)['data'],old[f])
  self.assertEqual(len(records),1);self.assertEqual(len(refs),4)
if __name__=='__main__':unittest.main()
