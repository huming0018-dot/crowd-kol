import hashlib,json,tempfile,unittest,uuid
from pathlib import Path
from types import SimpleNamespace
import media_cloud as m
from cloud_sync import CloudError
class Client:
 role='owner';endpoint='https://project.supabase.co/functions/v1/crowd-machine'
 def __init__(self,t):self.t=t;self.calls=[];self.asset=None;self.aid=str(uuid.uuid4());self.receipt=None
 def call(self,a,p=None):
  self.calls.append(a);t=self.t
  if a=='task_list':return {'tasks':[{'task_id':t.task,'children':[{'child_id':t.child,'attempts':[{'local_run_id':t.run,'run_id':t.crun,'lease_epoch':1}]}]}]}
  if a=='results':return {'items':[{'record':{'kind':'content','platform':'douyin','content_id':'123','origin':{'run_id':t.run,'file_sha256':'f'*64}},'receipt':{'task_id':t.task,'child_id':t.child,'run_id':t.crun,'lease_epoch':1,'status':'received','reward_eligible':False,'capture_id':t.capture,'envelope_hash':'a'*64}}]}
  if a=='media_prepare':
   self.payload=p;self.path='crowd-owner-main/'+self.aid+'/'+p['asset_sha256']+'.mp4'
   return {'artifact_id':self.aid,'state':'pending','manifest_hash':m._hash(p),'upload_url':'https://project.supabase.co/storage/v1/object/upload/sign/crowd-machine-media/'+self.path+'?token=private'}
  if a=='media_commit':
   if self.asset is None:raise CloudError('media_object_missing')
   self.receipt={'artifact_id':self.aid,'artifact_kind':'video_object','status':'received','verification':'server_storage_bytes_sha256','reward_eligible':False,'manifest':self.payload,'manifest_hash':m._hash(self.payload),'bucket_id':'crowd-machine-media','object_path':self.path}
   return {'receipt':self.receipt,'replayed':True}
  if a=='media_get':return {'receipt':self.receipt,'download_url':'https://project.supabase.co/storage/v1/object/sign/crowd-machine-media/'+self.path+'?token=private'}
  raise AssertionError(a)
class Response:
 status=200;headers={}
 def __init__(self,data=b''):self.data=data
 def __enter__(self):return self
 def __exit__(self,*a):pass
 def read(self,n):return self.data[:n]
class Opener:
 def __init__(self,c,lost=False,committed=True):self.c=c;self.calls=0;self.lost=lost;self.committed=committed
 def open(self,r,timeout):
  self.calls+=1;assert r.get_header('X-crowd-owner-key') is None
  if r.get_method()=='PUT':
   assert r.get_header('X-upsert')=='false'
   if self.committed:self.c.asset=r.data
   if self.lost:raise OSError('https://signed?token=NEVER_LOG')
   return Response()
  return Response(self.c.asset)
class Tests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve();self.jobs=SimpleNamespace(root=self.root/'media-processing');self.job=str(uuid.uuid4());self.run=str(uuid.uuid4());self.task=str(uuid.uuid4());self.child=str(uuid.uuid4());self.crun=str(uuid.uuid4());self.capture=str(uuid.uuid4());f=self.jobs.root/self.job;f.mkdir(parents=True)
  self.data=b'\0\0\0\x10ftypisom'+b'x'*100;self.sha=hashlib.sha256(self.data).hexdigest();e={'source_run_id':self.run,'source_reference_sha256':'e'*64,'source_file_sha256':'f'*64,'source_asset_sha256':'d'*64,'asset_sha256':self.sha,'bytes':len(self.data),'duration_seconds':2.0,'source_duration_seconds':2.0,'full_source_decode':True,'full_output_decode':True,'derivative':True};raw=json.dumps([{'kind':'processed_video','platform':'douyin','content_id':'123','evidence':e}]).encode();(f/'result.json').write_bytes(raw);(f/'video.mp4').write_bytes(self.data)
  state={'job_id':self.job,'kind':'complete_video','state':'completed','platform':'douyin','content_id':'123','run_id':self.run,'result_sha256':hashlib.sha256(raw).hexdigest(),'source_reference_sha256':'e'*64,'asset_sha256':self.sha};(f/'state.json').write_text(json.dumps(state));self.client=Client(self)
 def tearDown(self):self.temp.cleanup()
 def test_publish_readback_replay_download(self):
  op=Opener(self.client);a=m.publish_media_video(self.jobs,self.client,self.job,op);b=m.publish_media_video(self.jobs,self.client,self.job,op);self.assertEqual(a['receipt'],b['receipt']);self.assertEqual(op.calls,1);v=m.download_media_video(self.jobs,self.client,self.job,op);self.assertEqual(v['data'],self.data);self.assertEqual(v['sha256'],self.sha);self.assertNotIn('token=',(self.root/'media-cloud-receipts'/(self.job+'.json')).read_text())
 def test_lost_upload_ack_recovers(self):
  op=Opener(self.client,lost=True);v=m.publish_media_video(self.jobs,self.client,self.job,op);self.assertEqual(op.calls,1);self.assertEqual(v['receipt']['manifest']['asset_sha256'],self.sha)
 def test_unknown_not_reuploaded(self):
  op=Opener(self.client,lost=True,committed=False)
  for _ in range(2):
   with self.assertRaisesRegex(ValueError,'media_upload_outcome_unknown'):m.publish_media_video(self.jobs,self.client,self.job,op)
  self.assertEqual(op.calls,1);self.assertNotIn('NEVER_LOG',(self.root/'media-cloud-receipts'/(self.job+'.json')).read_text())
 def test_changed_asset_before_network(self):
  (self.jobs.root/self.job/'video.mp4').write_bytes(self.data+b'bad')
  with self.assertRaises(ValueError):m.prepare_media_video(self.jobs,self.client,self.job)
  self.assertEqual(self.client.calls,[])
 def test_symlink_before_network(self):
  p=self.jobs.root/self.job/'video.mp4';p.unlink();p.symlink_to(self.root/'outside')
  with self.assertRaises(ValueError):m.prepare_media_video(self.jobs,self.client,self.job)
  self.assertEqual(self.client.calls,[])
 def test_lock_busy(self):
  with m._job_lock(self.jobs,self.job):
   with self.assertRaisesRegex(ValueError,'media_cloud_busy'):m.publish_media_video(self.jobs,self.client,self.job)
 def test_wrong_urls(self):
  for u in ('https://evil.invalid/storage/v1/object/sign/crowd-machine-media/crowd-owner-main/x','https://u:p@project.supabase.co/x','https://project.supabase.co:443/x','http://project.supabase.co/x'):
   with self.assertRaises(ValueError):m._url(self.client,u,'sign')
 def test_download_mismatch(self):
  op=Opener(self.client);m.publish_media_video(self.jobs,self.client,self.job,op);self.client.asset=b'bad'
  with self.assertRaisesRegex(ValueError,'media_cloud_download_mismatch'):m.download_media_video(self.jobs,self.client,self.job,op)
 def test_invalid_job_id_fixed_valueerror_before_network(self):
  for bad in ('bad-uuid',None,'../outside',{},True):
   for action in (m.prepare_media_video,m.publish_media_video,m.download_media_video,m.media_video_cloud_status):
    with self.assertRaisesRegex(ValueError,'^invalid_media_job_id$'):action(self.jobs,self.client,bad)
  self.assertEqual(self.client.calls,[])
 def test_worker_binding(self):
  self.client.role='worker';b={'task_id':self.task,'child_id':self.child,'run_id':self.crun,'lease_epoch':1,'local_run_id':self.run,'capture_id':self.capture,'envelope_hash':'a'*64};p,_=m.prepare_media_video(self.jobs,self.client,self.job,b);self.assertEqual(p['capture_id'],self.capture);self.assertEqual(self.client.calls,[])
  with self.assertRaises(ValueError):m.prepare_media_video(self.jobs,self.client,self.job,{**b,'lease_epoch':True})
if __name__=='__main__':unittest.main()
