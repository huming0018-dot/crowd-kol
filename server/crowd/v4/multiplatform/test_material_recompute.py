from pathlib import Path
import copy,json,os,shutil,sys,tempfile,unittest,uuid
from unittest.mock import patch
HERE=Path(__file__).resolve().parent;MP=HERE
if not os.environ.get('CROWD_MATERIAL_TEST_ROOT'):raise RuntimeError('CROWD_MATERIAL_TEST_ROOT required; saved Pro ACK/config inputs are not bundled; NOT verified')
ACTUAL=Path(os.environ['CROWD_MATERIAL_TEST_ROOT']).resolve()
if not(ACTUAL/'data-products/material-auto-runtime.json').is_file():raise RuntimeError('saved material config missing; NOT verified')
sys.path.insert(0,str(MP))
from automatic_materials import AutomaticMaterials,canonical,sha,private_json,write,material_context_key
from material_auto_worker import process
from participant_material_delivery import publication
from dashboard import Application
from cloud_sync import CloudWorker
from toolbox.knowledge import KnowledgeStore,AuthContext,_candidate_hash
from toolbox.pack_schema import load_pack
from owner_knowledge_publication_service import OwnerKnowledgePublicationService
from owner_knowledge_binding import BindingError
class Recompute(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve();self.dir=self.root/'data-products/material-auto';self.dir.mkdir(parents=True);runtime=self.root/'runtime';runtime.mkdir()
  for p in MP.iterdir():
   if p.is_file()and(p.suffix=='.py'or p.name.endswith('-SHA.json')or p.name=='DEPENDENCIES.json'):shutil.copyfile(p,runtime/p.name)
  cfg=private_json(ACTUAL/'data-products/material-auto-runtime.json');self.cfg={**cfg,'runtime_root':str(runtime),'runtime_cloud_sha256':sha((runtime/'cloud_sync.py').read_bytes()),'bridge_path':str(runtime/'material_bridge.py'),'bridge_sha256':sha((runtime/'material_bridge.py').read_bytes()),'worker_script':str(runtime/'material_auto_worker.py'),'worker_sha256':sha((runtime/'material_auto_worker.py').read_bytes()),'pro_snapshot_sha256':sha((runtime/'pro_ack_snapshot.py').read_bytes())}
  if 'pro_comments_sha256'in cfg:self.cfg['pro_comments_sha256']=sha((runtime/'participant_pro_comments.py').read_bytes())
  rows=[private_json(p)for p in (ACTUAL/'data-products/material-auto').glob('pro-*.json')if not p.name.endswith('.config.json')];ready=next(v for v in rows if v.get('state')=='ready'and v.get('context',{}).get('task_id')==29)
  self.c=copy.deepcopy(ready['context']);inputs=self.root/'data-products/participant-pro-ack-inputs';inputs.mkdir();p=inputs/(self.c['group_sha256']+'.json');p.write_bytes(Path(self.c['group_path']).read_bytes());p.chmod(0o600);self.c['group_path']=str(p);self.key=material_context_key(self.c);self.state=self.dir/(self.key+'.json');write(self.state,{'state':'waiting','context':self.c});write(self.root/'data-products/material-auto-runtime.json',self.cfg)
  try:process(self.root,self.state,self.cfg)
  except Exception:
   for f in self.dir.glob('*/jobs.log'):(Path(tempfile.mkdtemp(prefix='material-recompute-debug-'))/'child.log').write_bytes(f.read_bytes())
   raise
  self.old=private_json(self.state);self.oldbytes=self.exports(self.old['job_id']);self.auto=AutomaticMaterials(self.root);self.addCleanup(self.auto.close)
  self.workspace=self.root/'knowledge';self.packs=self.root/'packs-store';self.scope={'tenant':'fixture','project':'same-ack','space':'explicit-packs'};self.owner=KnowledgeStore(self.workspace,AuthContext(**self.scope,role='owner',actor_ref='fixture-owner'));self.reviewer=KnowledgeStore(self.workspace,AuthContext(**self.scope,role='reviewer',actor_ref='fixture-reviewer',approved=True));self.addCleanup(self.owner.close);self.addCleanup(self.reviewer.close);self.releases=[]
  import yaml
  baseline_version=yaml.safe_load(Path(self.cfg['pack_path'],'pack.yaml').read_bytes())['pack']['version'];major,minor,patch_=map(int,baseline_version.split('.'));versions=(baseline_version,f'{major}.{minor}.{patch_+1}')
  for version in versions:
   candidate=self.root/('candidate-'+version);shutil.copytree(self.cfg['pack_path'],candidate);import yaml
   meta=yaml.safe_load((candidate/'pack.yaml').read_bytes());meta['pack']['version']=version;(candidate/'pack.yaml').write_text(yaml.safe_dump(meta,allow_unicode=True,sort_keys=False));h=_candidate_hash(candidate);pid=meta['pack']['pack_id'];payload={'change':'fixture '+version};sid='release-'+version.replace('.','-')
   env={'contract_version':'ctfs-knowledge-envelope/0.1','submission_id':sid,'project_id':'same-ack','pack_ref':{'pack_id':pid,'version':version,'hash':'a'*64},'channel':'owner','actor':{'ref':'fixture-owner'},'purpose':'test','consent_ref':None,'consent':{'scope':'private','granted_at':'2026-10-19T00:00:00Z','granted_by':'fixture-owner'},'source_refs':[{'category':'official','locator':'fixture://saved-pack','version':version,'hash':h}],'payload_ref':{'store':'inline','key':sid,'type':'claim','hash':sha(canonical(payload))},'operation':'propose','idempotency_key':sid}
   prop=self.owner.propose(env,payload)['proposal_id'];self.owner.grant_review(prop,'a'*64,'fixture-reviewer');self.reviewer.review(prop,'approved',reason='isolated fixture',evidence_refs=[{'locator':'fixture://saved-pack','version':version,'hash':h}]);rel=self.reviewer.release(pid,version,h,self.packs,candidate_dir=candidate);self.assertEqual(rel['status'],'committed');self.releases.append({'pack_id':pid,'version':version,'hash':h})
  self.service=object.__new__(OwnerKnowledgePublicationService);self.service._check=lambda:None
  class Pub:pass
  pub=Pub();pub._check=lambda:None;pub.intents=self.root/'unused';pub.packs=self.packs;pub._store=lambda readonly:KnowledgeStore(self.workspace,AuthContext(**self.scope,role='reviewer',actor_ref='fixture-reviewer',approved=True),read_only=True);self.service.publication=pub
 def exports(self,job):
  app=object.__new__(Application);app.root=self.root;return {fmt:app.material_delivery(fmt,pro_key=self.key,job_id=job)for fmt in ('html','json','jsonl','csv')}
 def resolved(self):return self.service.material_releases(self.releases[1],resolve=True)
 def context(self):return self.auto.prepare_recompute(self.key,self.old['job_id'],self.resolved())
 def test_same_ack_two_legal_releases_old_four_formats_select_back(self):
  context=self.context();path=self.dir/(material_context_key(context)+'.json');write(path,{'state':'waiting','context':context});self.assertEqual(self.exports(self.old['job_id']),self.oldbytes);process(self.root,path,context['config']);new=private_json(path);self.assertEqual(new['state'],'ready');self.assertNotEqual(new['job_id'],self.old['job_id']);self.assertNotEqual(self.exports(new['job_id'])['json'],self.oldbytes['json']);self.assertEqual(new['snapshot_sha256'],self.old['snapshot_sha256']);self.assertEqual(self.exports(self.old['job_id']),self.oldbytes);self.assertEqual(private_json(self.state)['job_id'],self.old['job_id']);self.auto.select_version(self.key,self.old['job_id'],new['job_id']);self.assertEqual(publication(self.root,self.key)['job_id'],new['job_id']);self.auto.select_version(self.key,new['job_id'],self.old['job_id']);self.assertEqual(self.exports(self.old['job_id']),self.oldbytes)
 def test_queue_exact_request_and_conflict(self):
  w=CloudWorker(self.root/'cloud-outbox',object(),lambda*a:None);w._save({'phase':'idle'});rid=str(uuid.uuid4());ctx=self.context();first=w.enqueue_material_recompute(rid,lambda:ctx,'a'*64);self.assertEqual(first,w.enqueue_material_recompute(rid,lambda:(_ for _ in()).throw(AssertionError('no replay')),'a'*64));self.assertEqual(len(private_json(w.path)['postprocessing_runs']),1)
  with self.assertRaisesRegex(ValueError,'request_conflict'):w.enqueue_material_recompute(rid,lambda:ctx,'b'*64)
 def test_unknown_save_preserves_old(self):
  w=CloudWorker(self.root/'cloud-outbox',object(),lambda*a:None);w._save({'phase':'idle'});before=w.path.read_bytes()
  with patch.object(w,'_save',side_effect=OSError('before atomic replace')):
   with self.assertRaises(OSError):w.enqueue_material_recompute(str(uuid.uuid4()),self.context,'c'*64)
  self.assertEqual(w.path.read_bytes(),before);self.assertEqual(self.exports(self.old['job_id']),self.oldbytes)
 def test_normal_application_cloud_queue_real_owned_worker(self):
  from types import SimpleNamespace
  import time
  app=object.__new__(Application);app.root=self.root;app.cloud_client=SimpleNamespace(role='owner');app.automatic_materials=self.auto
  def callback(action,payload):
   if action=='enqueue':return self.auto.enqueue(payload['material_context'])
   return None
  worker=CloudWorker(self.root/'cloud-outbox',object(),lambda*a:(_ for _ in()).throw(AssertionError('source forbidden')),postprocessing_callback=callback);worker._save({'phase':'idle'});worker._tick=lambda state:{'state':'idle'};app.cloud_worker=worker
  def knowledge(config,cloud,body):return self.service.material_releases(body['payload'],resolve=body['action']=='material_release_resolve')
  with patch('knowledge_review_call.call',side_effect=knowledge):
   view=app.cloud('material_versions',{'pro_key':self.key});self.assertEqual(len(view['releases']),2);rid=str(uuid.uuid4());payload={'request_id':rid,'pro_key':self.key,'expected_job':view['current_job'],'release':self.releases[1]};queued=app.cloud('material_recompute',payload);self.assertEqual(queued['state'],'queued');self.assertEqual(app.cloud('material_recompute',payload),queued)
   for _ in range(100):
    worker.tick();status=app.cloud('material_recompute_status',{'request_id':rid})
    if status['state']in ('ready','blocked'):break
    time.sleep(.05)
   self.assertEqual(status['state'],'ready');self.assertEqual(self.exports(self.old['job_id']),self.oldbytes);new=status['job_id'];app.cloud('material_select_version',{'pro_key':self.key,'expected_job':self.old['job_id'],'job_id':new});self.assertEqual(publication(self.root,self.key)['job_id'],new)
   self.assertEqual(private_json(worker.path)['postprocessing_runs'],[])
 def test_mixed_pack_bytes_pending_request_and_runtime_drift(self):
  resolved=self.resolved();resolved['files']['rubric.yaml']=__import__('base64').b64encode(b'changed: true').decode()
  with self.assertRaisesRegex(ValueError,'pack_changed'):self.auto.prepare_recompute(self.key,self.old['job_id'],resolved)
  worker=CloudWorker(self.root/'cloud-outbox',object(),lambda*a:None);worker._save({'phase':'idle'});ctx=self.context();worker.enqueue_material_recompute(str(uuid.uuid4()),lambda:ctx,'a'*64)
  with self.assertRaisesRegex(ValueError,'recompute_pending'):worker.enqueue_material_recompute(str(uuid.uuid4()),lambda:ctx,'a'*64)
  self.assertEqual(self.exports(self.old['job_id']),self.oldbytes)
 def test_after_save_unknown_same_uuid_reconciles_without_new_factory(self):
  w=CloudWorker(self.root/'cloud-outbox',object(),lambda*a:None);w._save({'phase':'idle'});rid=str(uuid.uuid4());ctx=self.context();save=w._save
  def saved_then_unknown(state):save(state);raise OSError('after atomic replace')
  with patch.object(w,'_save',side_effect=saved_then_unknown):
   with self.assertRaises(OSError):w.enqueue_material_recompute(rid,lambda:ctx,'a'*64)
  result=w.enqueue_material_recompute(rid,lambda:(_ for _ in()).throw(AssertionError('unknown factory replay')),'a'*64);self.assertEqual(result['request_id'],rid);self.assertEqual(len(private_json(w.path)['postprocessing_runs']),1)
  with self.assertRaisesRegex(ValueError,'recompute_pending'):w.enqueue_material_recompute(str(uuid.uuid4()),lambda:ctx,'a'*64)
  self.assertEqual(self.exports(self.old['job_id']),self.oldbytes)
 def test_processing_failure_and_foreign_version_cannot_hide_original(self):
  ctx=self.context();path=self.dir/(material_context_key(ctx)+'.json');write(path,{'state':'blocked','context':ctx,'error':'fixture interrupted'});self.assertEqual(self.exports(self.old['job_id']),self.oldbytes)
  with self.assertRaisesRegex(ValueError,'delivery_unavailable'):publication(self.root,self.key,job_id='f'*64)
  tampered=copy.deepcopy(ctx);tampered['original']['task_id']=19
  with self.assertRaises(ValueError):material_context_key(tampered)
 def test_normal_http_old_and_new_version_routes(self):
  from dashboard import make_server
  import threading,urllib.request,urllib.error
  ctx=self.context();path=self.dir/(material_context_key(ctx)+'.json');write(path,{'state':'waiting','context':ctx});process(self.root,path,ctx['config']);new=private_json(path)
  app=object.__new__(Application);app.root=self.root;app.token='offline-fixture-csrf';app.analysis_jobs=app.owner_tasks=app.cloud_worker=app.automatic_materials=app.media_jobs=None
  class Noop:
   def close(self):pass
  app.health_events=Noop();app.watchlists=Noop();server=make_server(app,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();url='http://127.0.0.1:'+str(server.server_port)
  try:
   for job in (self.old['job_id'],new['job_id']):
    for fmt,suffix in [('html',''),('json','/report.json'),('jsonl','/materials.jsonl'),('csv','/materials.csv')]:
     with urllib.request.urlopen(url+'/materials/pro/'+self.key+'/versions/'+job+suffix,timeout=10)as response:self.assertEqual(response.read(),self.exports(job)[fmt])
   with self.assertRaises(urllib.error.HTTPError)as refused:urllib.request.urlopen(url+'/materials/pro/'+self.key+'/versions/'+'f'*64+'/report.json')
   self.assertEqual(refused.exception.code,409)
   request=urllib.request.Request(url+'/api/cloud',data=b'{"action":"material_recompute","payload":{}}',headers={'Content-Type':'application/json'},method='POST')
   with self.assertRaises(urllib.error.HTTPError)as csrf:urllib.request.urlopen(request)
   self.assertEqual(csrf.exception.code,403)
  finally:server.shutdown();server.server_close();thread.join()
 def test_application_known_prequeue_cas_failure_not_unknown(self):
  from types import SimpleNamespace
  app=object.__new__(Application);app.root=self.root;app.cloud_client=SimpleNamespace(role='owner');app.automatic_materials=self.auto;worker=CloudWorker(self.root/'cloud-outbox',object(),lambda*a:None);worker._save({'phase':'idle'});app.cloud_worker=worker
  with patch('knowledge_review_call.call',return_value=self.resolved()):
   result=app.cloud('material_recompute',{'request_id':str(uuid.uuid4()),'pro_key':self.key,'expected_job':'f'*64,'release':self.releases[1]})
  self.assertEqual(result['state'],'not_submitted');self.assertEqual(result['error_code'],'material_recompute_current_changed');self.assertEqual(private_json(worker.path).get('postprocessing_runs',[]),[])
 def test_uncommitted_hash_cas_refuse(self):
  for change in ({'version':'9.9.9'},{'hash':'0'*64}):
   with self.assertRaises(BindingError):self.service.material_releases({**self.releases[1],**change},resolve=True)
  with self.assertRaisesRegex(ValueError,'current_changed'):self.auto.prepare_recompute(self.key,'f'*64,self.resolved())
  self.assertEqual(self.exports(self.old['job_id']),self.oldbytes)
if __name__=='__main__':unittest.main()
