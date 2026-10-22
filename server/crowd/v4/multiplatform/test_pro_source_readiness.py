"""Local preflight only, synthetic session metadata, no SDK/network/real roots."""
import hashlib,json,os,sys,tempfile,time,types,unittest,uuid
from pathlib import Path
from unittest.mock import patch
import pro_source_readiness as R

class Tests(unittest.TestCase):
 def setUp(self):
  R._CACHE.clear();R._NEGATIVE.clear();self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve();self.sid=str(uuid.uuid4());self.session=self.root/'sessions'/self.sid;self.session.mkdir(parents=True);self.account=self.root/'accounts'/self.sid;self.account.mkdir(parents=True)
  self.sdk=self.root/'sdk';self.sdk.mkdir();self.dep=self.root/'dependency.py';self.dep.write_text('original')
  self.state={'session_id':self.sid,'platform':'xhs','state':'authenticated','generation':1,'identity_status':'authenticated_self_id','account_ref':'a'*64,'login_verified':True,'recovering':False,'verified_at':1000,'verification_method':'upstream_authenticated_endpoint'}
  self.write(self.session/'identity.json',{'platform':'xhs','session_id':self.sid});self.write(self.session/'pro-binding.json',{'platform':'xhs','client_id':'fixture','cookiebridge_url':'http://127.0.0.1:8274','sign_url':'http://127.0.0.1:8990'});self.write(self.root/'pro-executor.json',{'root':str(self.sdk),'python':sys.executable});self.write(self.root/'pro-signer.json',{'source_root':str(self.sdk),'python':sys.executable});self.save_state()
  self.app=types.SimpleNamespace(_roots=lambda:[self.root],_cloud_session=lambda lease:self.sid)
  self.source=patch('pro_source_readiness._source_info',return_value={'commit':R.SOURCE_COMMIT,'dirty':False});self.source.start();self.probe=patch('pro_source_readiness._dependency_probe',return_value=[self.dep]);self.mockprobe=self.probe.start()
 def tearDown(self):self.source.stop();self.probe.stop();self.temp.cleanup();R._CACHE.clear();R._NEGATIVE.clear()
 def write(self,path,value):path.write_text(json.dumps(value));path.chmod(0o600)
 def save_state(self):self.write(self.account/'state.json',self.state)
 def test_valid_cached_identity_exact_scope_and_no_private_fields(self):
  value=R.produce(self.app,now=80000);self.assertEqual(value['state'],'ready');scope=value['source_readiness'][0];self.assertEqual(scope['scope'],'xhs_detail_body_comments_v1');self.assertIs(scope['media'],False);self.assertEqual(scope['identity_verified_at_ms'],1000000);self.assertEqual(scope['max_comments'],200);self.assertEqual(scope['session_ref'],hashlib.sha256(self.sid.encode()).hexdigest());text=json.dumps(value);self.assertNotIn(str(self.root),text);self.assertNotIn(self.sid,text);self.assertNotIn('a'*64,text)
 def test_not_merely_authenticated_or_importable(self):
  for changed in({'account_ref':None},{'identity_status':'session_only_unverified'},{'generation':True},{'login_verified':False},{'recovering':True},{'state':'account_changed'},{'state':'logged_out'},{'verified_at':0}):
   with self.subTest(changed=changed):
    original=dict(self.state);self.state.update(changed);self.save_state();self.assertEqual(R.produce(self.app,now=80000)['state'],'not_ready');self.state=original;self.save_state()
 def test_dependency_failure_and_source_drift_refuse(self):
  self.mockprobe.side_effect=RuntimeError('private exception path');self.assertEqual(R.produce(self.app,now=80000)['reason_code'],'dependency_unavailable');self.assertNotIn('private exception',json.dumps(R.produce(self.app,now=80000)))
  self.assertEqual(self.mockprobe.call_count,1)
  R._CACHE.clear();self.mockprobe.side_effect=None
  with patch('pro_source_readiness._source_info',return_value={'commit':'0'*40,'dirty':False}):self.assertEqual(R.produce(self.app,now=80000)['reason_code'],'source_changed')
 def test_short_cache_invalidates_on_dependency_or_session_change(self):
  self.assertEqual(R.produce(self.app,now=80000)['state'],'ready');self.assertEqual(R.produce(self.app,now=80001)['state'],'ready');self.assertEqual(self.mockprobe.call_count,1)
  self.dep.write_text('changed');self.assertEqual(R.produce(self.app,now=80002)['state'],'ready');self.assertEqual(self.mockprobe.call_count,2)
  self.state['state']='account_changed';self.save_state();self.assertEqual(R.produce(self.app,now=80003)['state'],'not_ready')
 def test_real_session_lock_busy_refuses(self):
  import fcntl
  with (self.session/'active.lock').open('w')as stream:
   fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB);self.assertEqual(R.produce(self.app,now=80000)['reason_code'],'login_in_progress')
 def test_host_projection_is_truthful_not_support_claim(self):
  with patch('pro_source_readiness.platform.system',return_value='Windows'),patch('pro_source_readiness.platform.machine',return_value='AMD64'):
   value=R.produce(self.app,now=80000);self.assertEqual(value['host'],{'os':'windows','arch':'x64'});self.assertEqual(value['state'],'not_ready');self.assertEqual(value['reason_code'],'unsupported_scope')
 def test_ambiguous_root_and_symlink_refuse(self):
  self.app._roots=lambda:[self.root,self.root];self.assertEqual(R.produce(self.app,now=80000)['state'],'not_ready');self.app._roots=lambda:[self.root]
  path=self.session/'pro-binding.json';saved=path.read_bytes();path.unlink();target=self.root/'elsewhere';target.write_bytes(saved);target.chmod(0o600);path.symlink_to(target);self.assertEqual(R.produce(self.app,now=80000)['state'],'not_ready')
 def test_selected_signer_venv_entry_is_not_resolved_before_invocation(self):
  import pro_executor as P
  self.probe.stop()
  selected=self.root/'venv/bin/python';selected.parent.mkdir(parents=True);selected.symlink_to(sys.executable);self.write(self.root/'pro-signer.json',{'source_root':str(self.sdk),'python':str(selected)})
  node=self.root/'resource/bin/node';node.parent.mkdir(parents=True);node.write_bytes(b'fixture')
  results=[types.SimpleNamespace(returncode=0,stdout=json.dumps({'ok':True,'files':[str(self.dep)]}).encode()),types.SimpleNamespace(returncode=0,stdout=(json.dumps({'ok':True,'validate_only':True,'listening':False,'source_requests':0,'browser_started':False,'platforms':['xhs','dy','zhihu']})+'\n'+json.dumps({'files':[str(self.dep)],'node':str(node)})).encode())]
  with patch.object(P,'probe',return_value={'protocol':'vox-acquisition-v1','native_protocol_platforms':['xhs','dy','bili']}),patch.object(R.subprocess,'run',side_effect=results)as run:
   files=R._dependency_probe({'root':str(self.sdk),'python':sys.executable},self.root);self.assertIn(node,files);self.assertEqual(run.call_args_list[1].args[0][0],str(selected));self.assertNotEqual(str(selected),str(selected.resolve()))
  self.probe.start()
 def test_empty_public_module_is_hashable_but_private_json_is_not(self):
  empty=self.root/'__init__.py';empty.write_bytes(b'');empty.chmod(0o600);self.assertEqual(R._sha(empty),hashlib.sha256(b'').hexdigest())
  with self.assertRaises(R.Unavailable):R._sha(empty,True)
if __name__=='__main__':unittest.main()
