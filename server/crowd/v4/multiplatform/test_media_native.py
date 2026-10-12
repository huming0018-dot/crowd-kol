import hashlib,json,os,tempfile,unittest,uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import media_native as n
import media_cloud as m
from mc_runner import canonical
from test_media_cloud import Client,Opener

class NativeClient(Client):
 def call(self,a,p=None):
  if a=='results':
   self.calls.append(a);t=self.t
   return {'items':[{'record':t.body,'receipt':{'task_id':t.task,'child_id':t.child,'run_id':t.crun,'lease_epoch':1,'status':'received','reward_eligible':False,'capture_id':t.capture,'envelope_hash':'a'*64}}]}
  return super().call(a,p)

class Tests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve();self.jobs=SimpleNamespace(root=self.root/'media-processing')
  self.run=str(uuid.uuid4());self.task=str(uuid.uuid4());self.child=str(uuid.uuid4());self.crun=str(uuid.uuid4());self.capture=str(uuid.uuid4());self.folder=self.root/'runs'/self.run
  self.data=b'\0\0\0\x10ftypisom'+b'x'*100;self.sha=hashlib.sha256(self.data).hexdigest();self.client=NativeClient(self);self.seed('dy')
 def tearDown(self):self.temp.cleanup()
 def save(self):
  (self.folder/'normalized.json').write_text(json.dumps(self.normalized))
 def seed(self,p,kind='content',ctype=None):
  platform=n.PLATFORMS[p];self.platform=platform
  (self.folder/'output'/platform/'jsonl').mkdir(parents=True,exist_ok=True)
  raw=b'{"test":"existing native fixture"}\n';source=self.folder/'output'/platform/'jsonl'/'contents.jsonl';source.write_bytes(raw);self.file_sha=hashlib.sha256(raw).hexdigest()
  self.body={'kind':kind,'platform':platform,'content_id':'123','body':'original body','source_kind':'mediacrawler_api','reward_eligible':False,'origin':{'run_id':self.run,'file_sha256':self.file_sha,'line':1}}
  if ctype:self.body['content_type']=ctype
  self.body['record_hash']=hashlib.sha256(canonical(self.body).encode()).hexdigest()
  directory=self.folder/'output'/platform/'media'/'123'
  if ctype:directory=directory/ctype
  directory.mkdir(parents=True,exist_ok=True);self.asset=directory/'video.mp4';self.asset.write_bytes(self.data)
  self.item={'path':str(self.asset.relative_to(self.folder)),'bytes':len(self.data),'sha256':self.sha,'content_id':'123','platform':platform,'source_kind':'mediacrawler_api','reward_eligible':False,'content_identity_status':'reported_directory_id'}
  if ctype:self.item['source_content_type']=ctype
  self.normalized={'run_id':self.run,'source_kind':'mediacrawler_api','reward_eligible':False,'records':[self.body],'media':[self.item],'files':[{'path':str(source.relative_to(self.folder)),'sha256':self.file_sha}]};self.save()
  (self.folder/'manifest.json').write_text(json.dumps({'run_id':self.run,'request':{'platform':p}}));(self.folder/'status.json').write_text(json.dumps({'run_id':self.run,'state':'completed'}))
 def prepare(self,entity=None):
  with patch.object(n,'_duration',return_value=35000):return n.prepare_native_video(self.jobs,self.client,self.folder,'123',self.sha,entity)
 def test_seven_platforms_body_identity(self):
  for p in n.PLATFORMS:
   with self.subTest(p=p):
    self.seed(p,ctype='answer' if p=='zhihu' else None);entity='zhihu:content:123:answer' if p=='zhihu' else None
    payload,data=self.prepare(entity);self.assertEqual(payload['platform'],n.PLATFORMS[p]);self.assertEqual(payload['source_record_hash'],self.body['record_hash']);self.assertEqual(data,self.data);self.assertEqual(payload['manifest_version'],2);self.assertEqual(payload['completeness'],'saved_asset_not_full_length_verified');self.assertNotIn('full_source_decode',payload)
 def test_publish_replay_download_and_status(self):
  op=Opener(self.client)
  with patch.object(n,'_duration',return_value=35000):
   a=n.publish_native_video(self.jobs,self.client,self.folder,'123',self.sha,opener=op);b=n.publish_native_video(self.jobs,self.client,self.folder,'123',self.sha,opener=op)
  self.assertEqual(a['receipt'],b['receipt']);self.assertEqual(op.calls,1);self.assertEqual(n.native_video_cloud_status(self.jobs,self.client,self.folder,'123',self.sha)['state'],'received');self.assertEqual(n.download_native_video(self.jobs,self.client,self.folder,'123',self.sha,opener=op)['data'],self.data)
  self.assertNotIn('token=',next((self.root/'media-cloud-receipts').glob('*.json')).read_text())
 def test_unknown_no_second_upload(self):
  op=Opener(self.client,lost=True,committed=False)
  with patch.object(n,'_duration',return_value=35000):
   for _ in range(2):
    with self.assertRaisesRegex(ValueError,'media_upload_outcome_unknown'):n.publish_native_video(self.jobs,self.client,self.folder,'123',self.sha,opener=op)
  self.assertEqual(op.calls,1)
 def test_zhihu_typed_collision(self):
  self.seed('zhihu',ctype='answer');answer=dict(self.body)
  self.seed('zhihu',ctype='article');article=dict(self.body)
  self.normalized['records']=[answer,article];self.save()
  with self.assertRaisesRegex(ValueError,'media_native_source_ambiguous'):self.prepare()
  with self.assertRaisesRegex(ValueError,'media_native_source_ambiguous'):self.prepare('zhihu:content:123:answer')
  payload,_=self.prepare('zhihu:content:123:article');self.assertEqual(payload['content_type'],'article')
 def test_bili_dynamic_and_numeric_collision_rejected(self):
  self.seed('bili',kind='dynamic');p,_=self.prepare();self.assertEqual(p['entity_ref'],'bilibili:dynamic:123')
  self.normalized['records'].append({**self.body,'kind':'content'});self.save()
  with self.assertRaises(ValueError):self.prepare('bilibili:dynamic:123')
 def test_cover_audio_unreported_duplicate(self):
  for changes in ({'path':self.item['path'].replace('.mp4','.jpg')},{'kind':'audio'},{'content_identity_status':'missing'},{'reward_eligible':True}):
   self.normalized['media']=[{**self.item,**changes}];self.save()
   with self.assertRaises(ValueError):self.prepare()
  self.normalized['media']=[self.item,self.item];self.save()
  with self.assertRaises(ValueError):self.prepare()
  self.assertEqual(self.client.calls,[])
 def test_path_symlink_hardlink_missing_changed(self):
  for value in ('../outside.mp4','/outside.mp4','output/douyin/media/123/../video.mp4','output\\douyin\\video.mp4'):
   self.normalized['media']=[{**self.item,'path':value}];self.save()
   with self.assertRaises(ValueError):self.prepare()
  self.normalized['media']=[self.item];self.save();outside=self.root/'outside';outside.write_bytes(self.data);self.asset.unlink();self.asset.symlink_to(outside)
  with self.assertRaises(ValueError):self.prepare()
  self.asset.unlink();os.link(outside,self.asset)
  with self.assertRaises(ValueError):self.prepare()
  self.asset.unlink();self.asset.write_bytes(self.data+b'changed')
  with self.assertRaises(ValueError):self.prepare()
  self.assertEqual(self.client.calls,[])
 def test_source_record_or_jsonl_changed_before_cloud(self):
  self.normalized['records'][0]['body']='changed';self.save()
  with self.assertRaises(ValueError):self.prepare()
  self.seed('dy');(self.folder/self.normalized['files'][0]['path']).write_bytes(b'changed')
  with self.assertRaises(ValueError):self.prepare()
  self.assertEqual(self.client.calls,[])
 def test_running_bad_ids_rejected(self):
  (self.folder/'status.json').write_text(json.dumps({'run_id':self.run,'state':'running'}))
  with self.assertRaises(ValueError):self.prepare()
  for bad in (None,True,'../bad'):
   with self.assertRaises(ValueError):n.prepare_native_video(self.jobs,self.client,self.folder,bad,self.sha)
  self.assertEqual(self.client.calls,[])
 def test_size_boundary_and_cloud_record_hash(self):
  with self.asset.open('wb') as stream:stream.write(self.data);stream.truncate(m.LIMIT+1)
  self.normalized['media'][0]['bytes']=m.LIMIT+1;self.save()
  with self.assertRaises(ValueError):self.prepare()
  self.assertEqual(self.client.calls,[])
  self.seed('dy');original=self.client.call
  def wrong(action,payload=None):
   response=original(action,payload)
   if action=='results':response['items'][0]['record']={**self.body,'record_hash':'0'*64}
   return response
  self.client.call=wrong
  with self.assertRaisesRegex(ValueError,'media_cloud_identity_mismatch'):self.prepare()
 def test_worker_exact_binding_no_management_calls(self):
  self.client.role='worker';binding={'task_id':self.task,'child_id':self.child,'run_id':self.crun,'lease_epoch':1,'local_run_id':self.run,'capture_id':self.capture,'envelope_hash':'a'*64}
  with patch.object(n,'_duration',return_value=35000):p,_=n.prepare_native_video(self.jobs,self.client,self.folder,'123',self.sha,binding=binding)
  self.assertEqual(p['capture_id'],self.capture);self.assertEqual(self.client.calls,[])
  with patch.object(n,'_duration',return_value=35000):
   with self.assertRaises(ValueError):n.prepare_native_video(self.jobs,self.client,self.folder,'123',self.sha,binding={**binding,'lease_epoch':True})
 def test_metadata_video_only_and_finite_duration(self):
  def response(text):return SimpleNamespace(stderr=text.encode())
  with patch.dict(os.environ,{'CROWD_FFMPEG':'/fake/ffmpeg'}):
   for text in ('Duration: 00:00:02.00\nStream #0:0: Audio: aac','Duration: N/A\nStream #0:0: Video: h264','Duration: 02:00:01.00\nStream #0:0: Video: h264'):
    with patch.object(n.subprocess,'run',return_value=response(text)):
     with self.assertRaises(ValueError):n._duration(self.data)
   with patch.object(n.subprocess,'run',return_value=response('Duration: 00:00:35.10\nStream #0:0: Video: h264')) as call:
    self.assertEqual(n._duration(self.data),35100);self.assertIn('file,pipe',call.call_args.args[0]);self.assertNotIn('https',str(call.call_args))
if __name__=='__main__':unittest.main()
