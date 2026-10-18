import hashlib,unittest,uuid,os,subprocess,json,urllib.error,time,threading
from pathlib import Path
from unittest.mock import patch
import light_transcripts as light
import media_native,mc_runner,test_media_native,test_cloud_sync
from cloud_sync import CloudWorker

class Jobs:
 def __init__(self):self.calls=[];self.states={};self.ready=True;self.error=None
 def capabilities(self):return {'asr':self.ready}
 def start(self,path,platform,cid,kind,run_id,entity_ref=None,**options):
  if self.error:raise ValueError(self.error)
  if not options.get('native_run_folder'):assert path.stat().st_mode&0o777==0o600
  data=path.read_bytes();job={'job_id':str(uuid.uuid4()),'state':'queued','asset_sha256':hashlib.sha256(data).hexdigest(),'platform':platform,'content_id':cid,'kind':kind,'run_id':run_id,'entity_ref':entity_ref,'created_at':time.time()}
  self.calls.append((data,entity_ref));self.states[job['job_id']]=job;return job
 def status(self,job_id):return self.states[job_id]
 def list(self,run_id):return {'jobs':[job for job in self.states.values() if job['run_id']==run_id]}

class Tests(unittest.TestCase):
 def setUp(self):
  self.f=test_media_native.Tests();self.f.setUp();self.f.seed('bili');self.f.asset.rename(self.f.asset.with_name('audio.m4a'));self.f.asset=self.f.asset.with_name('audio.m4a')
  self.f.item.update(path=str(self.f.asset.relative_to(self.f.folder)),kind='audio');self.f.save()
  mc_runner.write(self.f.folder/'manifest.json',{'run_id':self.f.run,'request':{'platform':'bili','media':True,'platform_options':{'long_audio':True,'transcript_only':True}}})
  self.jobs=Jobs();self.queue=light.LightTranscripts(self.f.root,self.jobs,lambda run:self.f.folder)
  self.duration=patch.object(light,'_duration',return_value=35000);self.duration.start()
 def tearDown(self):self.duration.stop();self.f.tearDown()
 def test_five_platform_native_audio_queue_and_typed_identity(self):
  for p in ('ks','wb','xhs','tieba','zhihu'):
   with self.subTest(platform=p):
    fixture=test_media_native.Tests();fixture.setUp()
    try:
     fixture.seed(p,ctype='zvideo' if p=='zhihu' else None)
     mc_runner.write(fixture.folder/'manifest.json',{'run_id':fixture.run,'request':{'platform':p,'media':True,'platform_options':{'transcript_only':True}}})
     jobs=Jobs();queue=light.LightTranscripts(fixture.root,jobs,lambda run:fixture.folder)
     queued=queue.enqueue(fixture.run);self.assertEqual(len(queued['assets']),1)
     queue.tick();self.assertEqual(len(jobs.calls),1);queue.tick();self.assertEqual(len(jobs.calls),1)
     self.assertEqual(jobs.calls[0][1],fixture.platform+':content:123'+(':zvideo' if p=='zhihu' else ''))
    finally:fixture.tearDown()
 def test_zhihu_subtitle_does_not_hide_same_cid_other_type_video(self):
  import copy,test_media_native
  fixture=test_media_native.Tests();fixture.setUp()
  try:
   fixture.seed('zhihu',ctype='zvideo')
   answer=copy.deepcopy(fixture.body);answer['content_type']='answer'
   fixture.normalized['records'].append(answer);fixture.save()
   mc_runner.write(fixture.folder/'manifest.json',{'run_id':fixture.run,'request':{'platform':'zhihu','media':True,'platform_options':{'transcript_only':True}}})
   directory=fixture.folder/'output/zhihu/declared-subtitles';directory.mkdir(parents=True)
   (directory/'123.answer.json').write_text('{}')
   jobs=Jobs();queue=light.LightTranscripts(fixture.root,jobs,lambda run:fixture.folder)
   # Isolate downstream identity selection; declared source proof has its own full tests.
   with patch('declared_subtitles.register',return_value={'entity_ref':'zhihu:content:123:answer','job_id':'answer-subtitle'}):
    queued=queue.enqueue(fixture.run)
    self.assertEqual([asset['entity_ref'] for asset in queued['assets']],['zhihu:content:123:zvideo'])
    self.assertEqual(queued['subtitle_jobs'][0]['entity_ref'],'zhihu:content:123:answer')
    queue.tick();queue.tick();self.assertEqual(len(jobs.calls),1)
    reopened=light.LightTranscripts(fixture.root,jobs,lambda run:fixture.folder)
    reopened.enqueue(fixture.run);reopened.tick();self.assertEqual(len(jobs.calls),1)
  finally:fixture.tearDown()
 def test_durable_serial_start_preserves_source_and_restart_no_repeat(self):
  before=hashlib.sha256(self.f.asset.read_bytes()).hexdigest();self.queue.enqueue(self.f.run);self.queue.enqueue(self.f.run)
  self.queue.tick();state=self.queue.status(self.f.run);job=state['assets'][0]['job_id'];self.assertEqual(len(self.jobs.calls),1)
  self.assertEqual(self.jobs.calls[0][1],'bilibili:content:123');self.assertEqual(hashlib.sha256(self.f.asset.read_bytes()).hexdigest(),before)
  self.assertFalse(list(self.queue.root.glob('snapshot-*')))
  restarted=light.LightTranscripts(self.f.root,self.jobs,lambda run:self.f.folder);restarted.tick();self.assertEqual(len(self.jobs.calls),1)
  self.jobs.states[job]['state']='completed';restarted.tick();self.assertEqual(restarted.status(self.f.run)['state'],'completed')
 def test_running_job_prevents_next_audio_metadata_or_dispatch(self):
  self.queue.enqueue(self.f.run);self.queue.tick();state=self.queue.status(self.f.run)
  state['assets'].append({**state['assets'][0],'content_id':'second','job_id':None,'state':'waiting'})
  mc_runner.write(self.queue._path(self.f.run),state)
  with patch.object(light,'_identity') as identity:
   self.queue.tick();identity.assert_not_called()
  self.assertEqual(len(self.jobs.calls),1);self.assertEqual(self.queue.status(self.f.run)['state'],'processing')
 def test_job_id_entity_and_saved_run_binding_reject_drift(self):
  self.queue.enqueue(self.f.run);self.queue.tick();state=self.queue.status(self.f.run);job_id=state['assets'][0]['job_id'];original=dict(self.jobs.states[job_id])
  before=self.queue._path(self.f.run).read_bytes()
  for change in ({'entity_ref':'bilibili:dynamic:123'},{'run_id':str(uuid.uuid4())},{'job_id':str(uuid.uuid4())}):
   self.jobs.states[job_id]={**original,**change}
   with self.assertRaisesRegex(ValueError,'job_changed'):self.queue.tick()
   self.assertEqual(self.queue._path(self.f.run).read_bytes(),before)
  self.assertEqual(len(self.jobs.calls),1)
 def test_reused_existing_job_retains_original_run(self):
  old_run=str(uuid.uuid4());job_id=str(uuid.uuid4())
  cached={'job_id':job_id,'run_id':old_run,'asset_sha256':self.f.sha,'platform':'bilibili','content_id':'123','entity_ref':'bilibili:content:123','kind':'asr','state':'completed','created_at':1}
  self.jobs.states[job_id]=cached;self.queue.enqueue(self.f.run)
  with patch.object(self.jobs,'start',return_value=cached):self.queue.tick()
  self.queue.tick();state=self.queue.status(self.f.run)
  self.assertEqual(state['run_id'],self.f.run);self.assertEqual(state['assets'][0]['asr_run_id'],old_run)
  self.assertEqual(state['state'],'completed');self.assertEqual(self.jobs.calls,[])
 def test_actual_application_concurrent_queue_initialization_once(self):
  from dashboard import Application
  app=Application.__new__(Application);app.root=self.f.root;app.light_transcripts=None;app.media_jobs=self.jobs;app.lock=threading.Lock()
  barrier=threading.Barrier(2);created=[];ticks=[];errors=[]
  def caps(*args):barrier.wait(timeout=2);return {'asr':True}
  app.process_media=caps
  class Queue:
   def __init__(self,*args):created.append(self);time.sleep(.05)
   def tick(self):ticks.append(id(self))
  def call():
   try:app._light_postprocessing('tick',{})
   except Exception as error:errors.append(type(error).__name__)
  with patch.object(light,'LightTranscripts',Queue):
   threads=[threading.Thread(target=call) for _ in range(2)]
   for thread in threads:thread.start()
   for thread in threads:thread.join(3)
  self.assertEqual(errors,[]);self.assertEqual(len(created),1);self.assertEqual(len(ticks),2);self.assertEqual(len(set(ticks)),1)
 def test_unknown_failed_cancelled_never_automatic_restart(self):
  self.queue.enqueue(self.f.run);self.queue.tick();job=self.queue.status(self.f.run)['assets'][0]['job_id']
  for outcome in ('interrupted_unknown','failed','cancelled'):
   self.jobs.states[job]['state']=outcome;self.queue.tick();self.queue.tick();self.assertEqual(len(self.jobs.calls),1);self.assertEqual(self.queue.status(self.f.run)['state'],'needs_attention')
 def test_lost_dispatch_response_or_disk_commit_never_restarts_model(self):
  self.queue.enqueue(self.f.run)
  original=self.jobs.start
  def lost(*args,**kwargs):original(*args,**kwargs);raise OSError('fixed synthetic')
  with patch.object(self.jobs,'start',side_effect=lost):self.queue.tick()
  self.queue.tick();self.queue.tick();self.assertEqual(len(self.jobs.calls),1)
  self.assertEqual(self.queue.status(self.f.run)['state'],'needs_attention')
  state=self.queue.status(self.f.run);asset=state['assets'][0];asset.update(state='dispatching',dispatch_at=0,job_id=None)
  mc_runner.write(self.queue._path(self.f.run),state)
  restarted=light.LightTranscripts(self.f.root,self.jobs,lambda run:self.f.folder);restarted.tick()
  self.assertEqual(len(self.jobs.calls),1);self.assertEqual(restarted.status(self.f.run)['assets'][0]['job_id'],next(iter(self.jobs.states)))
 def test_busy_model_missing_and_source_changed(self):
  self.queue.enqueue(self.f.run);self.jobs.ready=False;self.queue.tick();self.assertFalse(self.jobs.calls)
  self.jobs.ready=True;self.jobs.error='media_processor_busy';self.queue.tick();self.assertFalse(self.jobs.calls)
  self.jobs.error=None;self.f.asset.write_bytes(self.f.data+b'changed');self.queue.tick();self.assertFalse(self.jobs.calls)
  self.assertEqual(self.queue.status(self.f.run)['assets'][0]['state'],'failed')
 def test_not_opted_in_unknown_source_and_default_audio_cloud_rejection(self):
  with self.assertRaises(ValueError):media_native._identity(self.f.folder,'123',self.f.sha,None)
  mc_runner.write(self.f.folder/'status.json',{'run_id':self.f.run,'state':'interrupted_unknown'})
  with self.assertRaisesRegex(ValueError,'source_not_completed'):self.queue.enqueue(self.f.run)
  self.assertIsNone(self.queue.status(self.f.run))
  mc_runner.write(self.f.folder/'manifest.json',{'run_id':self.f.run,'request':{'platform':'bili','platform_options':{}}})
  self.assertIsNone(self.queue.enqueue(self.f.run))
 def test_duplicate_and_unsafe_audio_identity_no_dispatch(self):
  self.f.normalized['media']=[self.f.item,self.f.item];self.f.save()
  with self.assertRaises(ValueError):self.queue.enqueue(self.f.run)
  self.assertFalse(self.jobs.calls)
 def test_option_strict_and_others_unsupported(self):
  base={'platform':'bili','mode':'detail','media':True,'platform_options':{'long_audio':True,'transcript_only':True}}
  mc_runner.validate_options(dict(base))
  for options in ({'transcript_only':True},{'long_audio':True,'transcript_only':1},{'long_audio':True,'transcript_only':'true'}):
   with self.assertRaises(mc_runner.BridgeError):mc_runner.validate_options({**base,'platform_options':options})
  with self.assertRaises(mc_runner.BridgeError):mc_runner.validate_options({**base,'platform':'ks'})
 def test_real_local_audio_metadata_and_video_rejection(self):
  binary=Path(__file__).resolve().parents[5]/'outputs/unified-crawler-implementation-2026-10-11/long-media-tools/lib/python3.9/site-packages/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1'
  self.assertTrue(binary.is_file())
  output=self.f.root/'synthetic.m4a'
  subprocess.run([str(binary),'-loglevel','error','-f','lavfi','-i','sine=frequency=440:duration=1.2','-c:a','aac',str(output)],check=True,timeout=10)
  with patch.dict(os.environ,{'CROWD_FFMPEG':str(binary)}):
   duration=media_native._duration(output.read_bytes(),audio_only=True);self.assertGreaterEqual(duration,1000)
   with self.assertRaisesRegex(ValueError,'video_track_missing'):media_native._duration(output.read_bytes())
 def test_finish_durable_handoff_retry_without_source_or_ack_repeat(self):
  f=test_cloud_sync.Tests();f.setUp();seen=[]
  try:
   def callback(action,payload):
    seen.append(action)
    if action=='enqueue' and seen.count('enqueue')==1:raise ValueError('synthetic')
   worker=CloudWorker(f.root,f.cloud,f.runner,postprocessing_callback=callback)
   f.cloud.lease['request']['platform_options']={'transcript_only':True}
   worker._save({'phase':'finishing','lease':f.cloud.lease,'outcome':'completed','api_attempts':2,'local_run_id':f.local_id})
   self.assertEqual(worker.tick()['state'],'finished');self.assertEqual(mc_runner.read(worker.path)['postprocessing_runs'],[f.local_id])
   with patch.object(worker,'_tick',return_value={'state':'idle'}):worker.tick()
   self.assertEqual(mc_runner.read(worker.path)['postprocessing_runs'],[]);self.assertFalse(f.actions)
   self.assertEqual(len([x for x in f.cloud.calls if x[0]=='finish']),1)
  finally:f.tearDown()

class HttpTests(unittest.TestCase):
 def setUp(self):
  import test_dashboard
  self.f=test_dashboard.DashboardTests();self.f.setUp()
 def tearDown(self):self.f.tearDown()
 def test_normal_preview_processor_preflight_and_multi_platform_rejection(self):
  payload={'platforms':['bili'],'mode':'detail','desired_items':1,'max_api_requests':8,'targets_by_platform':{'bili':['BV1234567890']},'media':True,'purpose':'noncommercial_research','platform_options_by_platform':{'bili':{'long_audio':True,'transcript_only':True}}}
  with patch.object(self.f.app,'process_media',return_value={'asr':False,'ffmpeg':True}),patch.object(self.f.app.owner_tasks,'preview') as preview:
   with self.assertRaises(urllib.error.HTTPError) as error:self.f.post('/api/tasks',{'action':'preview','payload':payload})
   self.assertEqual(error.exception.code,400);preview.assert_not_called()
  with patch.object(self.f.app,'process_media',return_value={'asr':True,'ffmpeg':True}),patch.object(self.f.app.owner_tasks,'preview',return_value={'ready':True}) as preview:
   response=json.load(self.f.post('/api/tasks',{'action':'preview','payload':payload}));self.assertTrue(response.get('result',response)['ready']);self.assertEqual(preview.call_args.args[0],payload)
   self.f.post('/api/tasks',{'action':'preview','payload':{**payload,'platforms':['bili','ks']}})
   self.assertEqual(preview.call_count,2)
   with self.assertRaises(urllib.error.HTTPError) as error:self.f.post('/api/tasks',{'action':'preview','payload':payload},token='wrong')
   self.assertEqual(error.exception.code,403);self.assertEqual(preview.call_count,2)

if __name__=='__main__':unittest.main()
