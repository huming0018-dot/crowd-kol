import json,time,unittest,uuid
from types import SimpleNamespace
from unittest.mock import patch
import test_media_native,mc_runner
import light_audio_fallback as fallback
from light_transcripts import LightTranscripts
class Jobs:
 def __init__(self,root):self.root=root/'media-processing';self.states={};self.calls=[];self.busy=False;self.lost=False
 def capabilities(self):return {'asr':True,'asr_engines':['cpu','mlx']}
 def list(self,run):return {'jobs':list(self.states.values())}
 def status(self,identity):return self.states[identity]
 def start_audio_reference(self,ref):
  if self.busy:raise ValueError('media_processor_busy')
  job={'job_id':str(uuid.uuid4()),'kind':'complete_audio','state':'queued','run_id':ref['run_id'],'platform':'douyin','content_id':ref['content_id'],
       'source_reference_sha256':ref['reference_sha256'],'created_at':time.time()}
  if ref.get('variant'):job.update(audio_reference_variant=ref['variant'],previous_audio_job_id=ref['previous_job_id'],network_budget={'max_request_attempts':ref['max_request_attempts']})
  self.states[job['job_id']]=job;self.calls.append('audio')
  if self.lost:raise OSError('lost response')
  return job
 def start_asr_from_audio_job(self,job_id,folder,entity_ref=None,asr_engine='cpu'):
  job=self.states[job_id];state={**job,'job_id':str(uuid.uuid4()),'kind':'asr','state':'queued','entity_ref':entity_ref,'created_at':time.time(),
   'audio_reference_binding':{'source_job_id':job_id},'asset_sha256':job['asset_sha256'],'asr_engine':asr_engine}
  self.states[state['job_id']]=state;self.calls.append('asr');return state
class Tests(unittest.TestCase):
 def setUp(self):
  self.f=test_media_native.Tests();self.f.setUp();self.f.normalized['media']=[];self.f.save()
  mc_runner.write(self.f.folder/'manifest.json',{'run_id':self.f.run,'request':{'platform':'dy','media':True,'platform_options':{'transcript_only':True},'max_api_requests':8}})
  mc_runner.write(self.f.folder/'status.json',{'run_id':self.f.run,'state':'completed','api_attempts':3})
  mc_runner.write(self.f.folder/'phase.json',{'media_reason':'single_response_byte_limit'})
  self.jobs=Jobs(self.f.root);self.queue=LightTranscripts(self.f.root,self.jobs,lambda run:self.f.folder)
  self.ref={'run_id':self.f.run,'platform':'douyin','content_id':'123','source_reference_sha256':'r','reference_sha256':'a'*64,'source_file_sha256':self.f.file_sha,'url':'https://v.douyincdn.com/video.mp4'}
  self.patch=patch.object(fallback,'source_reference',return_value=self.ref);self.patch.start()
 def tearDown(self):self.patch.stop();self.f.tearDown()
 def status(self):return self.queue.status(self.f.run)
 def test_full_download_audio_asr_and_stop_no_double_dispatch(self):
  self.queue.enqueue(self.f.run);self.assertEqual(self.status()['state'],'waiting');self.queue.tick()
  asset=self.status()['fallback_assets'][0];audio=asset['audio_job_id'];self.jobs.states[audio].update(state='completed',asset_sha256='b'*64,network_attempts=2)
  self.queue.tick();self.queue.tick();asset=self.status()['fallback_assets'][0]
  self.assertEqual(self.jobs.calls,['audio','asr']);self.assertEqual(self.jobs.states[asset['job_id']]['asr_engine'],'mlx')
  self.jobs.states[asset['job_id']]['state']='completed';self.queue.tick();self.queue.tick()
  self.assertEqual(self.status()['state'],'completed');self.assertEqual(self.jobs.calls,['audio','asr'])
 def test_lost_dispatch_response_reconciles_unique_job_not_restarts(self):
  self.queue.enqueue(self.f.run);self.jobs.lost=True;self.queue.tick()
  self.assertEqual(self.status()['state'],'needs_attention')
  # A unique durable local job resolves uncertainty without sending another request.
  self.queue.tick()
  self.assertEqual(self.jobs.calls,['audio']);self.assertIsNotNone(self.status()['fallback_assets'][0]['audio_job_id'])
 def test_insufficient_or_changed_budget_no_request(self):
  mc_runner.write(self.f.folder/'status.json',{'run_id':self.f.run,'state':'completed','api_attempts':6})
  self.queue.enqueue(self.f.run);self.queue.tick();self.assertEqual(self.jobs.calls,[]);self.assertEqual(self.status()['fallback_reason'],'light_fallback_insufficient_request_budget')
 def test_budget_drift_and_unresolved_dispatch_reserve_no_retry(self):
  self.queue.enqueue(self.f.run)
  mc_runner.write(self.f.folder/'status.json',{'run_id':self.f.run,'state':'completed','api_attempts':4})
  self.queue.tick();self.queue.tick();self.assertEqual(self.jobs.calls,[])
  self.assertEqual(self.status()['fallback_assets'][0]['budget']['reserved_audio_attempts'],4)
 def test_audio_attempt_over_reservation_never_asr(self):
  self.queue.enqueue(self.f.run);self.queue.tick();audio=self.status()['fallback_assets'][0]['audio_job_id']
  self.jobs.states[audio].update(state='completed',asset_sha256='b'*64,network_attempts=5)
  self.queue.tick();self.queue.tick();self.assertEqual(self.jobs.calls,['audio']);self.assertEqual(self.status()['state'],'needs_attention')
 def test_unmatched_lost_start_never_network_retry(self):
  self.queue.enqueue(self.f.run)
  with patch.object(self.jobs,'start_audio_reference',side_effect=OSError('unknown before durable reply')):
   self.queue.tick()
  self.queue.tick();self.queue.tick();self.assertEqual(self.jobs.calls,[])
  self.assertEqual(self.status()['fallback_assets'][0]['phase'],'dispatching_audio');self.assertEqual(self.status()['state'],'needs_attention')
 def test_busy_and_source_tamper_no_request(self):
  self.queue.enqueue(self.f.run);self.jobs.busy=True;self.queue.tick();self.assertEqual(self.jobs.calls,[])
  changed=mc_runner.read(self.f.folder/'normalized.json');changed['records'][0]['body']='changed'
  mc_runner.write(self.f.folder/'normalized.json',changed);self.jobs.busy=False;self.queue.tick();self.assertEqual(self.jobs.calls,[]);self.assertEqual(self.status()['state'],'needs_attention')
 def test_safe_old_unsent_queue_upgrade_but_subtitle_never_downloads(self):
  old={'schema_version':1,'run_id':self.f.run,'platform':'douyin','state':'audio_unavailable','assets':[],'subtitle_jobs':[], 'source_requests':0,'remote_model_calls':0}
  mc_runner.write(self.queue._path(self.f.run),old);self.queue.enqueue(self.f.run);self.assertEqual(self.status()['fallback_assets'][0]['budget']['remaining'],5)
  old['subtitle_jobs']=[{'job_id':str(uuid.uuid4())}];self.assertFalse(fallback.prepare(old,self.f.folder,self.jobs));self.assertEqual(self.jobs.calls,[])
 def test_old_completed_source_queue_upgrades_by_tick_without_enqueue(self):
  old={'schema_version':1,'run_id':self.f.run,'platform':'douyin','state':'audio_unavailable','assets':[],'subtitle_jobs':[], 'source_requests':0,'remote_model_calls':0}
  mc_runner.write(self.queue._path(self.f.run),old)
  self.queue.tick();self.assertEqual(self.jobs.calls,['audio'])
  self.assertEqual(self.status()['fallback_assets'][0]['phase'],'audio_processing')
  self.assertIsNone(self.status()['source_requests']);self.assertEqual(self.status()['source_requests_upper_bound'],4)
  self.queue.tick();self.assertEqual(self.jobs.calls,['audio'])
 def test_tick_upgrade_requires_original_authorized_text_mode(self):
  old={'schema_version':1,'run_id':self.f.run,'platform':'douyin','state':'audio_unavailable','assets':[],'subtitle_jobs':[], 'source_requests':0,'remote_model_calls':0}
  mc_runner.write(self.queue._path(self.f.run),old)
  manifest=mc_runner.read(self.f.folder/'manifest.json');manifest['request']['platform_options']['transcript_only']=False
  mc_runner.write(self.f.folder/'manifest.json',manifest);self.queue.tick();self.assertEqual(self.jobs.calls,[])
  self.assertNotIn('fallback_assets',self.status())
 def test_failed_cancelled_unknown_actual_attempts_or_null_keep_reservation(self):
  self.queue.enqueue(self.f.run);self.queue.tick();audio=self.status()['fallback_assets'][0]['audio_job_id']
  baseline=mc_runner.read(self.queue._path(self.f.run))
  for state,attempts in [('failed',3),('cancelled',None),('interrupted_unknown',2),('failed',None)]:
   mc_runner.write(self.queue._path(self.f.run),baseline)
   self.jobs.states[audio].update(state=state,network_attempts=attempts)
   self.queue.tick();self.queue.tick();saved=self.status()
   self.assertEqual(saved['source_requests'],attempts);self.assertEqual(saved['source_requests_upper_bound'],4)
   self.assertEqual(saved['fallback_assets'][0]['budget']['reserved_audio_attempts'],4)
   self.assertEqual(self.jobs.calls,['audio'])
 def test_verified_no_audio_default_variant_once_total_budget_four(self):
  self.queue.enqueue(self.f.run);self.queue.tick();old=self.status()['fallback_assets'][0]['audio_job_id']
  self.jobs.states[old].update(state='failed',reason='complete_audio_codec_not_supported',network_attempts=1)
  newref={**self.ref,'variant':'native_default_after_verified_no_audio','previous_job_id':old,'max_request_attempts':3,'reference_sha256':'c'*64}
  with patch.object(self.jobs,'recover_audio_reference_after_no_audio',return_value=newref,create=True):
   self.queue.tick();self.assertEqual(self.status()['source_requests'],1)
   self.jobs.busy=True;self.queue.tick();self.assertEqual(self.status()['source_requests'],1)
   self.jobs.busy=False;self.queue.tick();current=self.status()['fallback_assets'][0]['audio_job_id']
   self.assertNotEqual(current,old);self.assertEqual(self.jobs.calls,['audio','audio'])
   self.jobs.states[current].update(state='completed',asset_sha256='b'*64,network_attempts=3)
   self.queue.tick();self.assertEqual(self.status()['source_requests'],4)
   self.assertEqual([r['network_attempts'] for r in self.status()['fallback_assets'][0]['audio_attempt_chain']],[1,3])
   self.queue.tick();self.assertEqual(self.jobs.calls,['audio','audio','asr'])
 def test_variant_helper_proof_rejected_does_not_retry_codec_failure(self):
  self.queue.enqueue(self.f.run);self.queue.tick();old=self.status()['fallback_assets'][0]['audio_job_id']
  self.jobs.states[old].update(state='failed',reason='complete_audio_codec_not_supported',network_attempts=1)
  with patch.object(self.jobs,'recover_audio_reference_after_no_audio',side_effect=ValueError('source actually has unsupported audio'),create=True) as verify:
   self.queue.tick();self.queue.tick();self.assertEqual(verify.call_count,1)
   self.assertEqual(self.jobs.calls,['audio']);self.assertEqual(self.status()['state'],'needs_attention')
 def test_variant_new_job_more_than_three_never_asr(self):
  self.queue.enqueue(self.f.run);self.queue.tick();old=self.status()['fallback_assets'][0]['audio_job_id']
  self.jobs.states[old].update(state='failed',reason='complete_audio_stream_missing',network_attempts=1)
  newref={**self.ref,'variant':'native_default_after_verified_no_audio','previous_job_id':old,'max_request_attempts':3,'reference_sha256':'c'*64}
  with patch.object(self.jobs,'recover_audio_reference_after_no_audio',return_value=newref,create=True):
   self.queue.tick();self.queue.tick();current=self.status()['fallback_assets'][0]['audio_job_id']
   self.jobs.states[current].update(state='completed',asset_sha256='b'*64,network_attempts=4)
   self.queue.tick();self.queue.tick();self.assertEqual(self.jobs.calls,['audio','audio']);self.assertEqual(self.status()['state'],'needs_attention')
 def test_terminal_audio_failure_never_asr_or_network_again(self):
  self.queue.enqueue(self.f.run);self.queue.tick();audio=self.status()['fallback_assets'][0]['audio_job_id'];self.jobs.states[audio].update(state='failed',reason='video_source_network_error')
  self.queue.tick();self.queue.tick();self.assertEqual(self.jobs.calls,['audio']);self.assertEqual(self.status()['state'],'needs_attention')
if __name__=='__main__':unittest.main()
