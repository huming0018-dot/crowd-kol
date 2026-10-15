import unittest,sys,tempfile,json,uuid,os,importlib.util,hashlib
from pathlib import Path
from unittest.mock import patch
import mc_runner as m,pro_executor as p,owner_tasks as o
class Route(unittest.TestCase):
 def request(self,**delta):return dict(platform='bili',mode='detail',targets=['BV1popx6zEe1'],max_items=1,max_api_requests=12,max_comments=3,comments=True,replies=True,media=False,purpose='noncommercial_research',session_id=str(uuid.uuid4()),**delta)
 def test_absent_field_has_original_owner_hash_and_no_added_engine(self):
  r=self.request();out=m.validate(r);self.assertNotIn('source_executor',out)
  payload={'platforms':['bili'],'mode':'detail','targets_by_platform':{'bili':r['targets']},'desired_items':1,'max_api_requests':12,'max_comments':3,'purpose':r['purpose'],'idempotency_key':'original-key','session_by_platform':{'bili':r['session_id']}}
  plan=o.plan(payload);self.assertEqual(plan['request'],payload);self.assertEqual(plan['request_hash'],hashlib.sha256(m.canonical(payload).encode()).hexdigest());self.assertNotIn('source_executor',plan['children'][0]['request'])
 def test_explicit_mc_overrides_legacy_environment(self):
  r=self.request(source_executor='mc');self.assertEqual(p.selection(m.validate(r),{'CROWD_EXECUTOR':'pro'})['backend'],'mc')
 def test_strict_engine_values(self):
  for v in [None,True,1,{},[], 'auto','PRO','']:
   with self.subTest(value=v),self.assertRaises(m.BridgeError):m.validate(self.request(source_executor=v))
 def test_explicit_pro_validated_forwarded_no_global_mutation(self):
  r=m.validate(self.request(source_executor='pro'));before=dict(os.environ);chosen=p.selection(r,{},installation={'root':'/private/tmp/pro-fixture','python':'/usr/bin/true'});self.assertEqual(chosen['backend'],'pro');self.assertEqual(os.environ,before)
  payload={'platforms':['bili'],'mode':'detail','targets_by_platform':{'bili':r['targets']},'desired_items':1,'max_api_requests':12,'max_comments':3,'purpose':r['purpose'],'idempotency_key':'pro-key','source_executor':'pro'};self.assertEqual(o.plan(payload)['children'][0]['request']['source_executor'],'pro')
 def test_explicit_pro_capability_failures_never_fallback(self):
  for delta,code in [({'media':True},'pro_media_pipeline_unavailable'),({'platform_options':{'quality':16},'media':True},'pro_media_pipeline_unavailable'),({'platform_options':{'quality':16}},'pro_options_unsupported'),({'platform':'wb'},'pro_operation_platform_not_adapted'),({'mode':'homefeed'},'pro_mode_unsupported'),({'comments':True,'max_comments':0},'pro_zero_comments_means_unlimited')]:
   r=self.request(source_executor='pro');r.update(delta)
   with self.subTest(code=code),self.assertRaisesRegex(m.BridgeError,code):p.selection(r,{},installation={'root':'/private/tmp/pro-fixture','python':'/usr/bin/true'})
 def test_installation_only_explicit_and_strict(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);self.assertIsNone(p.task_installation(root,self.request()));r=self.request(source_executor='pro')
   with self.assertRaisesRegex(m.BridgeError,'pro_task_installation_missing'):p.task_installation(root,r)
   f=root/'pro-executor.json';external=root/'external';external.mkdir();good={'root':str(external),'python':'/usr/bin/true'};f.write_text(json.dumps(good));f.chmod(0o600);self.assertEqual(p.task_installation(root,r),good)
   for value in [[],None,dict(good,root=12),dict(good,python={}),dict(good,extra='bad'),dict(good,root='relative')]:
    f.write_text(json.dumps(value))
    with self.assertRaises(m.BridgeError):p.task_installation(root,r)
   f.write_text(json.dumps(good));f.chmod(0o644)
   with self.assertRaisesRegex(m.BridgeError,'pro_task_installation_invalid'):p.task_installation(root,r)
 def test_real_cloud_worker_passes_exact_engine_lease_without_global_change(self):
  import cloud_sync as cs
  from test_cloud_sync import FakeCloud,lease
  with tempfile.TemporaryDirectory() as tmp:
   l=lease();l.update(platform='bili',request=self.request(source_executor='pro'));cloud=FakeCloud(l);calls=[];local=str(uuid.uuid4())
   def runner(action,payload):
    calls.append((action,payload));return {'ok':True,'result':{'run_id':local}} if action=='start' else {'ok':True,'result':{'state':'running','api_attempts':0}}
   worker=cs.CloudWorker(tmp,cloud,runner);before=dict(os.environ);worker.tick();start=[p for a,p in calls if a=='start'];self.assertEqual(len(start),1);self.assertEqual(start[0]['source_executor'],'pro');self.assertEqual(start[0]['max_api_requests'],12);self.assertEqual(start[0]['session_id'],l['request']['session_id']);self.assertEqual(os.environ,before);state=json.loads(worker.path.read_text());self.assertEqual(state['lease']['request']['source_executor'],'pro')
 def test_actual_start_consumes_local_installation_and_persists_pro_manifest(self):
  from types import SimpleNamespace
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/'collector';root.mkdir();external=Path(tmp)/'pro';external.mkdir();mc=Path(tmp)/'mc';mc.mkdir();desc=root/'pro-executor.json';desc.write_text(json.dumps({'root':str(external),'python':'/usr/bin/true'}));desc.chmod(0o600);r=self.request(source_executor='pro');before=dict(os.environ);chosen=[]
   def prepare(root_arg,mc_arg,request,value):chosen.append(value);return value,{'root':str(external),'commit':'synthetic-only'},Path('/usr/bin/true')
   with patch.object(p,'prepare',side_effect=prepare),patch.object(m.subprocess,'Popen',return_value=SimpleNamespace(pid=12345)) as spawn:
    result=m.start(root,mc,r)
   self.assertEqual(len(chosen),1);self.assertEqual(chosen[0]['backend'],'pro');self.assertEqual(chosen[0]['python'],'/usr/bin/true');self.assertEqual(result['executor'],'pro');manifest=json.loads((root/'runs'/result['run_id']/'manifest.json').read_text());self.assertEqual(manifest['request']['source_executor'],'pro');self.assertEqual(manifest['request']['max_api_requests'],12);self.assertEqual(manifest['request']['max_comments'],3);self.assertEqual(os.environ,before);self.assertEqual(spawn.call_count,1)
 def test_legacy_environment_fallback_preserved(self):
  r=self.request();r['media']=True;self.assertEqual(p.selection(r,{'CROWD_EXECUTOR':'pro'})['fallback_reason'],'media_bytes_and_subtitles_retain_original_executor')
if __name__=='__main__':unittest.main()
