import hashlib,io,json,os,subprocess,sys,tempfile,unittest,uuid
from pathlib import Path
from participant_native_rpc import frame,FrameIO,ProtocolError
G=Path(__file__).parent;MP=Path(os.environ.get('CROWD_MP_SOURCE',str(G)));C=Path(os.environ.get('CROWD_TEST_OVERLAY',str(MP)));U=lambda:str(uuid.uuid4())
class Capability(unittest.TestCase):
 def test_actual_imports_manifest_and_tamper(self):
  with tempfile.TemporaryDirectory()as t:
   root=Path(t)
   for p in MP.glob('*.py'):
    if not p.name.startswith('test_'):(root/p.name).write_bytes(p.read_bytes())
   for p in C.glob('*.py'):
    if not p.name.startswith('test_'):(root/p.name).write_bytes(p.read_bytes())
   files={p.name:hashlib.sha256(p.read_bytes()).hexdigest()for p in root.glob('*.py')};(root/'PRO-RUNTIME.json').write_text(json.dumps({'files':files}))
   config={'entry':str(root/'participant_pro_native.py'),'entry_sha256':files['participant_pro_native.py'],'max_api_requests':14}
   cmd="import json;from participant_pro_native import ready_capability;print(json.dumps(ready_capability(json.loads(__import__('sys').argv[1]))))"
   env={**os.environ,'PYTHONPATH':str(root)};r=subprocess.run([sys.executable,'-B','-c',cmd,json.dumps(config)],cwd=root,env=env,capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stderr);v=json.loads(r.stdout);self.assertEqual(v['max_api_requests'],14);self.assertTrue(v['comment_options_v1']);self.assertNotIn(str(root),r.stdout);self.assertEqual(v['worker_sha256'],files['participant_pro.py'])
   (root/'participant_pro.py').write_text((root/'participant_pro.py').read_text()+'\n#tamper\n');bad=subprocess.run([sys.executable,'-B','-c',cmd,json.dumps(config)],cwd=root,env=env,capture_output=True,text=True);self.assertNotEqual(bad.returncode,0);self.assertNotIn('runtime_sha256',bad.stdout)
 def test_optional_frame_legacy_and_bounds(self):
  v=frame('pro_state',U(),1,run_id=None,state='ready',phase='initial',received=None,target=None,pending=0,error=None);cap={'schema':'crowd-participant-pro-capability-v1','runtime_sha256':'a'*64,'entry_sha256':'b'*64,'worker_sha256':'c'*64,'upstream_commit':'d'*40,'comment_options_v1':True,'max_api_requests':14}
  for x in [v,{**v,'capabilities':cap},frame('pro_hello',U(),1,version=1),frame('pro_hello',U(),1,version=1,capability_request='pro_comment_options_v1')]:
   b=io.BytesIO();FrameIO(io.BytesIO(),b).send(x);self.assertEqual(FrameIO(io.BytesIO(b.getvalue()),io.BytesIO()).read(),x)
  for key,value in [('comment_options_v1',1),('max_api_requests',True),('max_api_requests',101),('worker_sha256',['c'*64]),('root','/private/path')]:
   with self.assertRaises(ProtocolError):FrameIO(io.BytesIO(),io.BytesIO()).send({**v,'capabilities':{**cap,key:value}})
  with self.assertRaises(ProtocolError):frame('pro_hello',U(),1,version=1,capability_request='arbitrary')
if __name__=='__main__':unittest.main()
