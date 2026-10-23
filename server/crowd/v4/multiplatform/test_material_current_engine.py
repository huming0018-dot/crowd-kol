from pathlib import Path
import os,sys,json,tempfile,shutil,unittest,uuid,subprocess,copy
from unittest.mock import patch
from types import SimpleNamespace
HERE=Path(__file__).resolve().parent;MP=HERE;SRC=Path(os.environ.get('CROWD_F1_SOURCE',HERE)).resolve();sys.path[:0]=[str(SRC),str(MP)]
from automatic_materials import AutomaticMaterials,private_json,write,sha,canonical,material_context_key,validate_context
from material_auto_worker import process
from dashboard import Application
from cloud_sync import CloudWorker
from participant_material_delivery import publication
from workbench_material_call import command
ACTUAL=Path(os.environ['CROWD_MATERIAL_TEST_ROOT'])
OLD_RUNTIME=Path(os.environ['CROWD_PREVIOUS_MATERIAL_RUNTIME']).resolve()
class Engine(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='engine-recompute-');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve();self.directory=self.root/'data-products/material-auto';self.directory.mkdir(parents=True)
  old=self.root/'old-runtime';old.mkdir()
  for p in OLD_RUNTIME.glob('*.py'):shutil.copyfile(p,old/p.name)
  cfg=private_json(ACTUAL/'data-products/material-auto-runtime.json');pack=self.root/'original-pack';shutil.copytree(cfg['pack_path'],pack);cfg={**cfg,'pack_path':str(pack)};self.cfg=self.config(cfg,old)
  self.group=json.loads(Path(os.environ['CROWD_PRO_ACK_FIXTURE']).read_text());raw=canonical(self.group);h=sha(raw);inputs=self.root/'data-products/participant-pro-ack-inputs';inputs.mkdir();gp=inputs/(h+'.json');gp.write_bytes(raw);gp.chmod(0o600)
  self.ctx={k:self.group[k]for k in ('task_id','subject','installation_id','dispatch_id','group_cursor')};self.ctx.update(schema='crowd-participant-pro-material-context-v1',group_path=str(gp),group_sha256=h);self.key=material_context_key(self.ctx);self.state=self.directory/(self.key+'.json');write(self.state,{'state':'waiting','context':self.ctx});write(self.root/'data-products/material-auto-runtime.json',self.cfg);process(self.root,self.state,self.cfg);self.old=private_json(self.state);self.oldbytes=self.exports(self.old)
  new=self.root/'new-runtime';shutil.copytree(old,new)
  for p in SRC.glob('*.py'):shutil.copyfile(p,new/p.name)
  self.newcfg=self.config(cfg,new);write(self.root/'data-products/material-auto-runtime.json',self.newcfg);self.auto=AutomaticMaterials(self.root);self.addCleanup(self.auto.close)
  self.worker=CloudWorker(self.root/'cloud-outbox',object(),lambda*a:(_ for _ in()).throw(AssertionError('source forbidden')));self.worker._save({'phase':'idle'});self.app=object.__new__(Application);self.app.root=self.root;self.app.cloud_client=SimpleNamespace(role='owner');self.app.cloud_worker=self.worker;self.app.automatic_materials=self.auto
 def config(self,cfg,runtime):
  out={**cfg,'runtime_root':str(runtime),'runtime_cloud_sha256':sha((runtime/'cloud_sync.py').read_bytes()),'bridge_path':str(runtime/'material_bridge.py'),'bridge_sha256':sha((runtime/'material_bridge.py').read_bytes()),'worker_script':str(runtime/'material_auto_worker.py'),'worker_sha256':sha((runtime/'material_auto_worker.py').read_bytes()),'pro_snapshot_sha256':sha((runtime/'pro_ack_snapshot.py').read_bytes())}
  if 'pro_comments_sha256'in out:out['pro_comments_sha256']=sha((runtime/'participant_pro_comments.py').read_bytes())
  return out
 def exports(self,row):return {fmt:subprocess.check_output(command(row['publication_pointer'],'read',fmt))for fmt in ('html','json','jsonl','csv')}
 def payload(self):return {'request_id':str(uuid.uuid4()),'pro_key':self.key,'expected_job':self.old['job_id'],'mode':'current_engine'}
 def test_zero_committed_normal_endpoint_queue_select_back(self):
  payload=self.payload()
  with patch('knowledge_review_call.call',return_value={'releases':[]}):
   view=self.app.cloud('material_versions',{'pro_key':self.key})
  self.assertEqual(view['releases'],[]);self.assertEqual(view['current_engine'],{'available':True,'reason':None});self.assertEqual(private_json(self.worker.path).get('postprocessing_runs',[]),[])
  with patch('knowledge_review_call.call',side_effect=AssertionError('engine mode must not resolve/create knowledge release')):
   result=self.app.cloud('material_recompute',payload)
  self.assertEqual(result['state'],'queued');self.assertIsNone(result['target_release']);self.assertEqual(self.app.cloud('material_recompute',payload),result)
  queue=private_json(self.worker.path);ctx=queue['postprocessing_contexts'][result['key']];self.assertEqual(ctx['mode'],'current_engine');self.assertIsNone(ctx['target_release']);self.assertEqual(ctx['config']['pack_sha256'],self.cfg['pack_sha256']);self.assertEqual(ctx['original'],self.ctx)
  path=self.directory/(result['key']+'.json');write(path,{'state':'waiting','context':ctx});process(self.root,path,ctx['config']);new=private_json(path);self.assertNotEqual(new['job_id'],self.old['job_id']);self.assertEqual(new['snapshot_sha256'],self.old['snapshot_sha256']);self.assertEqual(publication(self.root,self.key)['job_id'],self.old['job_id']);self.assertEqual(self.exports(self.old),self.oldbytes)
  output=self.exports(new)
  for item in json.loads(output['json'])['items']:
   rec=item['metadata']['capture']['pro_payload']['record'];self.assertEqual(item['identity']['title'],rec['title']);self.assertEqual(item['draft']['text'],rec['body'])
   for fmt in output:self.assertIn(rec['title'].encode(),output[fmt])
  self.app.cloud('material_select_version',{'pro_key':self.key,'expected_job':self.old['job_id'],'job_id':new['job_id']});self.app.cloud('material_select_version',{'pro_key':self.key,'expected_job':new['job_id'],'job_id':self.old['job_id']});self.assertEqual(self.exports(self.old),self.oldbytes)
  (self.root/'ENGINE-VERSION-EVIDENCE.json').write_text(json.dumps({'old_job':self.old['job_id'],'new_job':new['job_id'],'same_ack_snapshot':True,'knowledge_calls':0,'new_four_formats':{k:sha(v)for k,v in output.items()},'old_four_formats':{k:sha(v)for k,v in self.oldbytes.items()},'select_and_back':True,'source_calls':0},indent=2)+'\n')
 def test_reject_unchanged_wrong_pack_mixed_modes_and_foreign_current(self):
  for cfg in [self.cfg,{**self.newcfg,'pack_sha256':{**self.newcfg['pack_sha256'],'fields.yaml':'f'*64}}]:
   write(self.root/'data-products/material-auto-runtime.json',cfg);out=self.app.cloud('material_recompute',self.payload());self.assertEqual(out['state'],'not_submitted');self.assertEqual(private_json(self.worker.path).get('postprocessing_runs',[]),[])
  write(self.root/'data-products/material-auto-runtime.json',self.newcfg)
  packfile=Path(self.cfg['pack_path'])/'fields.yaml';saved=packfile.read_bytes();packfile.write_bytes(saved+b'\n# file drift')
  try:
   with self.assertRaises(ValueError):self.app.cloud('material_recompute',self.payload())
  finally:packfile.write_bytes(saved)
  only_worker=self.root/'worker-only.py';only_worker.write_bytes(Path(self.cfg['worker_script']).read_bytes()+b'\n# worker-only build change')
  worker_cfg={**self.cfg,'worker_script':str(only_worker),'worker_sha256':sha(only_worker.read_bytes())};write(self.root/'data-products/material-auto-runtime.json',worker_cfg);self.assertEqual(self.app.cloud('material_recompute',self.payload())['error_code'],'material_engine_unchanged')
  pathonly=self.root/'path-only-runtime';shutil.copytree(Path(self.cfg['runtime_root']),pathonly);path_cfg=self.config(self.cfg,pathonly);write(self.root/'data-products/material-auto-runtime.json',path_cfg);self.assertEqual(self.app.cloud('material_recompute',self.payload())['error_code'],'material_engine_unchanged')
  write(self.root/'data-products/material-auto-runtime.json',self.newcfg)
  for change in ({'release':None},{'config':self.newcfg},{'path':'/tmp/not-permitted'},{'mode':'unknown'},{'expected_job':'f'*64},{'pro_key':'pro-'+'f'*64}):
   payload={**self.payload(),**change}
   try:out=self.app.cloud('material_recompute',payload)
   except (ValueError,FileNotFoundError):
    self.assertEqual(private_json(self.worker.path).get('postprocessing_runs',[]),[]);continue
   self.assertEqual(out['state'],'not_submitted');self.assertEqual(private_json(self.worker.path).get('postprocessing_runs',[]),[])
  ctx=self.auto.prepare_current_engine(self.key,self.old['job_id'])
  for bad in ({**ctx,'target_release':{'pack_id':'fake','version':'1.0.0','hash':'a'*64}},{k:v for k,v in ctx.items()if k!='mode'},{**ctx,'mode':'release'}):
   with self.assertRaises(ValueError):validate_context(bad)
 def test_unknown_uuid_and_pending_cross_mode_are_preserved(self):
  payload=self.payload();save=self.worker._save;initial=self.worker.path.read_bytes()
  with patch.object(self.worker,'_save',side_effect=OSError('before atomic save')):
   with self.assertRaises(OSError):self.app.cloud('material_recompute',payload)
  self.assertEqual(self.worker.path.read_bytes(),initial)
  def after_save(state):save(state);raise OSError('after atomic save')
  with patch.object(self.worker,'_save',side_effect=after_save):
   with self.assertRaises(OSError):self.app.cloud('material_recompute',payload)
  first=self.app.cloud('material_recompute',payload);self.assertEqual(first['request_id'],payload['request_id']);before=self.worker.path.read_bytes()
  rejected=self.app.cloud('material_recompute',self.payload());self.assertEqual(rejected['error_code'],'material_recompute_pending');self.assertEqual(self.worker.path.read_bytes(),before)
  ctx=self.auto.prepare_current_engine(self.key,self.old['job_id']);release_variant={k:v for k,v in ctx.items()if k!='mode'};release_variant['target_release']={'pack_id':'social-observations','version':'1.0.0','hash':'a'*64}
  with self.assertRaisesRegex(ValueError,'material_recompute_pending'):self.worker.enqueue_material_recompute(str(uuid.uuid4()),lambda:release_variant,'b'*64)
  self.assertEqual(self.worker.path.read_bytes(),before);self.assertEqual(self.exports(self.old),self.oldbytes)
  cfg={**self.newcfg,'pro_snapshot_sha256':'0'*64};write(self.root/'data-products/material-auto-runtime.json',cfg)
  blocked=self.app.cloud('material_recompute',self.payload());self.assertEqual(blocked['state'],'not_submitted');self.assertEqual(self.worker.path.read_bytes(),before)
 def test_original_committed_release_branch_still_runs(self):
  import importlib.util
  spec=importlib.util.spec_from_file_location('formal_recompute_regression',MP/'test_material_recompute.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
  original=m.Recompute('test_same_ack_two_legal_releases_old_four_formats_select_back')
  result=unittest.TestResult();original.run(result);self.assertEqual(result.errors,[]);self.assertEqual(result.failures,[])
if __name__=='__main__':unittest.main()
