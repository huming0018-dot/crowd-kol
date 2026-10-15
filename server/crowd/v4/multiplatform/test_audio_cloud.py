import unittest,uuid,hashlib,json,tempfile,importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import audio_cloud as a
import media_cloud as m
from cloud_sync import canonical,CloudError
class Response:
 status=200;headers={'Content-Type':'audio/mp4'}
 def __init__(self,data=b''):self.data=data
 def __enter__(self):return self
 def __exit__(self,*_):pass
 def read(self,n):return self.data[:n]
class Client:
 role='worker';endpoint='https://project.supabase.co/functions/v1/crowd-machine'
 def __init__(self):self.aid=str(uuid.uuid4());self.data=None;self.calls=[]
 def call(self,action,payload=None):
  self.calls.append(action)
  if action=='media_prepare':
   self.payload=payload;self.path='crowd-owner-main/'+self.aid+'/'+payload['asset_sha256']+'.m4a'
   return {'artifact_id':self.aid,'manifest_hash':m._hash(payload),'upload_url':'https://project.supabase.co/storage/v1/object/upload/sign/crowd-machine-media/'+self.path+'?token=private'}
  if action=='media_commit':
   if self.data is None:raise CloudError('media_object_missing')
   self.receipt={'artifact_id':self.aid,'artifact_kind':'audio_object','status':'received','verification':'server_storage_bytes_sha256','reward_eligible':False,'manifest':self.payload,'manifest_hash':m._hash(self.payload),'bucket_id':'crowd-machine-media','object_path':self.path};return {'receipt':self.receipt}
  if action=='media_get':return {'receipt':self.receipt,'download_url':'https://project.supabase.co/storage/v1/object/sign/crowd-machine-media/'+self.path+'?token=private'}
  raise AssertionError(action)
class Opener:
 def __init__(self,client,unknown=False):self.c=client;self.puts=0;self.unknown=unknown
 def open(self,request,timeout):
  if request.get_method()=='PUT':
   self.puts+=1;assert request.get_header('Content-type')=='audio/mp4';assert request.get_header('X-upsert')=='false'
   if self.unknown:raise OSError('synthetic_private_url_not_logged')
   self.c.data=request.data;return Response()
  assert request.get_header('Accept')=='audio/mp4';return Response(self.c.data)
class AudioTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve();self.jobs=SimpleNamespace(root=self.root/'media-processing');self.jobs.root.mkdir();self.run=str(uuid.uuid4());self.client=Client();self.body={'platform':'bilibili','kind':'content','content_id':'123','body':'synthetic source','origin':{'run_id':self.run,'operation_id':self.run,'executor':'mediacrawler_pro','observation_sha256':'b'*64}};self.body['record_hash']=a.sha(self.body);self.data=b'\0\0\0\x18ftypM4A '+b'x'*100;self.digest=a.sha(self.data);self.ident={'local_run_id':self.run,'platform':'bilibili','content_id':'123','entity_ref':'bilibili:content:123','asset_sha256':self.digest};self.item={'path':'output/bili/media/BV1popx6zEe1/audio.m4a'};self.binding={**{k:str(uuid.uuid4()) for k in ['task_id','child_id','run_id','capture_id']},'lease_epoch':1,'local_run_id':self.run,'envelope_hash':'a'*64}
  self.mock=patch('media_native._identity',return_value=('old-video-domain-not-reused',self.ident,self.body,self.item,'c'*64,self.data));self.mock.start();self.duration=patch('media_native._duration',return_value=1000);self.duration.start()
 def tearDown(self):self.duration.stop();self.mock.stop();self.temp.cleanup()
 def prepare(self):return a.prepare_native_audio(self.jobs,self.client,self.root/self.run,'123',self.digest,binding=self.binding)
 def test_exact_31_fields_and_honest_hash_domains(self):
  payload,data=self.prepare();self.assertEqual(len(payload),31);self.assertEqual(set(payload),a.AUDIO_FIELDS);self.assertNotIn('source_file_sha256',payload);self.assertEqual(payload['source_observation_sha256'],'b'*64);self.assertNotEqual(payload['source_observation_sha256'],payload['asset_sha256']);self.assertEqual(payload['container'],'m4a');self.assertEqual(payload['content_mime'],'audio/mp4');self.assertFalse(payload['video_track_present']);self.assertTrue(payload['audio_track_present']);self.assertNotIn('record_hash',json.loads(payload['source_record_canonical']));self.assertEqual(a.validate_audio_manifest(payload)['manifest_hash'],m._hash(payload));self.assertEqual(data,self.data)
 def test_capture_derived_author_id_must_match_source_author(self):
  source={**self.body,'author':{'author_id':'synthetic-author'}};digest=a.sha({k:v for k,v in source.items() if k!='record_hash'})
  self.assertTrue(a._same_record(source,{**source,'record_hash':digest,'author_id':'synthetic-author'},digest))
  for wrong in ['other-author',None,True,7]:self.assertFalse(a._same_record(source,{**source,'record_hash':digest,'author_id':wrong},digest))
  self.assertFalse(a._same_record(self.body,{**self.body,'author_id':'unknown'},a.sha({k:v for k,v in self.body.items() if k!='record_hash'})))
 def test_source_python_domain_control_characters_and_capture_hash(self):
  self.body['body']='line1\nline2\tcontrol\x01😀';self.body['platform_fields']={'中':'文','emoji':'😀','a':'值'}
  source={k:v for k,v in self.body.items() if k!='record_hash'};expected=hashlib.sha256(a.source_canonical(source).encode()).hexdigest();self.body['record_hash']=expected
  payload,_=self.prepare();self.assertEqual(payload['source_record_hash'],expected);self.assertEqual(payload['source_record_canonical'],a.source_canonical(source));self.assertNotEqual(expected,a.sha(source));self.assertEqual(self.body['record_hash'],expected)
  self.assertTrue(a._same_record(self.body,dict(self.body),expected));self.assertTrue(a._same_record(self.body,source,expected));a.validate_audio_manifest(payload)
 def test_same_audio_identity_stable_and_separate_from_old_video(self):
  x,_=self.prepare();y,_=self.prepare();self.assertEqual(x['local_job_id'],y['local_job_id']);self.assertEqual(x['idempotency_key'],'audio:'+x['local_job_id'])
 def test_publish_get_real_journal_no_signed_url(self):
  payload,_=self.prepare();op=Opener(self.client)
  r=a.publish_native_audio(self.jobs,self.client,self.root/self.run,'123',self.digest,opener=op,binding=self.binding);self.assertEqual(r['receipt']['artifact_kind'],'audio_object');self.assertTrue(r['receipt']['object_path'].endswith('.m4a'));self.assertEqual(op.puts,1)
  r=m.download_media_video(self.jobs,self.client,payload['local_job_id'],op);self.assertEqual(r['data'],self.data);self.assertEqual(r['mime'],'audio/mp4');self.assertNotIn('token=',(self.root/'media-cloud-receipts'/(payload['local_job_id']+'.json')).read_text());self.assertEqual(m.media_video_cloud_status(self.jobs,self.client,payload['local_job_id'])['state'],'received')
 def test_large_valid_audio_journal_and_legacy_limit(self):
  self.body['body']='x'*70000;self.body['record_hash']=a.sha({k:v for k,v in self.body.items() if k!='record_hash'})
  payload,_=self.prepare();op=Opener(self.client);a.publish_native_audio(self.jobs,self.client,self.root/self.run,'123',self.digest,opener=op,binding=self.binding)
  self.assertEqual(m.media_video_cloud_status(self.jobs,self.client,payload['local_job_id'])['state'],'received')
  self.assertEqual(m.download_media_video(self.jobs,self.client,payload['local_job_id'],op)['mime'],'audio/mp4')
  legacy=self.root/'legacy.json';legacy.write_text(json.dumps({'manifest':{'manifest_version':2},'padding':'x'*70000}))
  with self.assertRaises(ValueError):m._read_journal(legacy)
 def test_unknown_same_journal_never_reuploads(self):
  op=Opener(self.client,True)
  for _ in range(2):
   with self.assertRaisesRegex(ValueError,'media_upload_outcome_unknown'):a.publish_native_audio(self.jobs,self.client,self.root/self.run,'123',self.digest,opener=op,binding=self.binding)
  self.assertEqual(op.puts,1)
 def test_wrong_audio_track_type_canonical_and_fields_rejected(self):
  payload,_=self.prepare()
  for delta in [{'manifest_version':True},{'video_track_present':True},{'audio_track_present':1},{'container':'mp4'},{'source_file_sha256':'b'*64},{'content_mime':'video/mp4'},{'content_id':{}},{'asset_bytes':True},{'asset_bytes':50*1024*1024+1},{'source_observation_sha256':self.digest},{'source_record_canonical':'[]'}]:
   with self.assertRaises(ValueError):a.validate_audio_manifest({**payload,**delta})
 def test_owner_binds_exact_original_observation_and_capture(self):
  self.client.role='owner';original=self.client.call
  def call(action,payload=None):
   if action=='task_list':return {'tasks':[{'task_id':self.binding['task_id'],'children':[{'child_id':self.binding['child_id'],'attempts':[{'local_run_id':self.run,'run_id':self.binding['run_id'],'lease_epoch':1}]}]}]}
   if action=='results':return {'items':[{'record':self.body,'receipt':{**self.binding,'status':'received','reward_eligible':False}}]}
   return original(action,payload)
  self.client.call=call
  payload,_=a.prepare_native_audio(self.jobs,self.client,self.root/self.run,'123',self.digest)
  self.assertEqual(payload['capture_id'],self.binding['capture_id'])
  self.body['origin']['observation_sha256']='e'*64
  with self.assertRaises(ValueError):a.prepare_native_audio(self.jobs,self.client,self.root/self.run,'123',self.digest)
 def test_old_video_v1_v2_hash_receipt_domain_unchanged(self):
  spec=importlib.util.spec_from_file_location('legacy_media_cloud',Path(__file__).with_name('BASE-media_cloud.py'));old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
  for version in [None,1,2,True]:
   value={'asset_sha256':'d'*64,'local_job_id':str(uuid.uuid4())}
   if version is not None:value['manifest_version']=version
   self.assertEqual(m._hash(value),old._hash(value));self.assertEqual(m._object_contract(value)['suffix'],'.mp4')
 def test_audio_receipt_not_accepted_as_video_or_wrong_suffix(self):
  payload,_=self.prepare();op=Opener(self.client);a.publish_native_audio(self.jobs,self.client,self.root/self.run,'123',self.digest,opener=op,binding=self.binding)
  r=self.client.receipt
  for delta in [{'artifact_kind':'video_object'},{'object_path':r['object_path'].replace('.m4a','.mp4')}]:
   with self.assertRaisesRegex(ValueError,'media_cloud_receipt_mismatch'):m._receipt({'receipt':{**r,**delta}},payload)
if __name__=='__main__':unittest.main()
