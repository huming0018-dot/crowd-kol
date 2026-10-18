import hashlib,json,subprocess,tempfile,types,unittest,uuid
from pathlib import Path
from unittest.mock import patch
from transcript_artifact import load_transcript
HERE=Path(__file__).parent
class OCRGlue(unittest.TestCase):
 def test_visual_reading_groups_exact_lines_keeps_timeline_original(self):
  src=(HERE/'media-ui.js').read_text();fn=src.split('  function visualLineInventory(',1)[1].split('\n',1)[0]
  script="const assert=require('node:assert/strict');function visualLineInventory("+fn+"\nconst rows=[{start:0,end:1,text:'同一行\\n第二次偶遇…'},{start:1,end:2,text:'同一行\\n同一行\\n第二次偶遇⋯'},{start:3,end:4,text:'同一行'}];const before=JSON.stringify(rows);const v=visualLineInventory(rows);assert.equal(v.length,3);assert.deepEqual(v[0],{text:'同一行',segment_count:3,first_start:0,last_end:4});assert.equal(v[1].text,'第二次偶遇…');assert.equal(v[2].text,'第二次偶遇⋯');assert.equal(JSON.stringify(rows),before);"
  done=subprocess.run(['/Users/hubowen/.local/node/bin/node','-e',script],capture_output=True,text=True)
  self.assertEqual(done.returncode,0,done.stderr)

 def test_actual_retry_preserves_top_full_and_refuses_unknown(self):
  src=(HERE/'media-ui.js').read_text();fn=src.split('  async function retryVideoOCR(',1)[1].split('\n',1)[0]
  script="const assert=require('node:assert/strict');let calls=[];const openVideoOCR=async(...args)=>calls.push(args);async function retryVideoOCR("+fn+"\n(async()=>{let s={kind:'video_ocr',state:'failed',run_id:'r',video_source_job_id:'p',crop_top:.12,crop_bottom:.32};await retryVideoOCR(s);assert.deepEqual(calls.pop(),['r','p',true,'top']);await retryVideoOCR({...s,state:'cancelled',crop_top:0,crop_bottom:1});assert.deepEqual(calls.pop(),['r','p',true,'full']);await assert.rejects(()=>retryVideoOCR({...s,crop_top:.2}),/region_requires_selection/);await assert.rejects(()=>retryVideoOCR({...s,state:'interrupted_unknown'}),/retry_not_allowed/);assert.equal(calls.length,0);})().catch(e=>{console.error(e);process.exitCode=1});"
  done=subprocess.run(['/Users/hubowen/.local/node/bin/node','-e',script],capture_output=True,text=True)
  self.assertEqual(done.returncode,0,done.stderr)

 def test_report_keeps_visual_provenance_not_audio(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);job=str(uuid.uuid4());folder=root/job;folder.mkdir();(folder/'state.json').write_text('{"kind":"video_ocr"}')
   state={'video_source_job_id':str(uuid.uuid4()),'run_id':str(uuid.uuid4()),'platform':'douyin','content_id':'123','entity_ref':'douyin:content:123','asset_sha256':'a'*64,'input_hash':'b'*64,'source_reference_sha256':'c'*64,'source_record_sha256':'d'*64,'processing_profile':'apple_vision_video_hard_text_2fps_v1'}
   evidence={'segments':[{'start':1,'end':1.5,'text':'字幕','first_frame':2,'last_frame':2}],'sample_fps':2,'sample_start':0,'sample_end':2,'sampled_frames':4,'expected_frames':4,'crop_top_origin':[.67,.82],'timestamp_kind':'resampled_frame_time','timestamp_uncertainty_seconds':.5,'frame_evidence_sha256':'e'*64,'duration_seconds':2,'processor':'apple_vision_sampled_video_text'}
   with patch('video_ocr_jobs.load_video_ocr',return_value={'state':state,'evidence':evidence,'result_sha256':'f'*64}):
    saved,report,raw=load_transcript(types.SimpleNamespace(root=root),job)
   self.assertNotIn('audio_source_job_id',report)
   self.assertEqual(report['schema'],'crowd-video-ocr-report-v1')
   self.assertFalse(report['visual_provenance']['spoken_transcript'])
   self.assertEqual(report['visual_provenance']['source_record_sha256'],'d'*64)
   self.assertEqual(report['text_sha256'],hashlib.sha256('字幕'.encode()).hexdigest())
   self.assertEqual(report['segments'],[{'start':1,'end':1.5,'text':'字幕'}])
   self.assertFalse(report['human_groundtruth']);self.assertIsNone(report['cer'])
 def test_late_start_does_not_open_or_steal_view(self):
  src=(HERE/'media-ui.js').read_text();fn=src.split('  async function openVideoOCR(',1)[1].split('\n',1)[0]
  script="""const assert=require('node:assert/strict');let generation=0,jobGeneration=0,selectedRun={},resolve,opened=[],calls=[];const call=(a,b)=>{calls.push([a,b]);return new Promise(r=>resolve=r);};const openSaved=async(...a)=>opened.push(a);async function openVideoOCR("""+fn+"""
(async()=>{let p=openVideoOCR('run','source');generation++;resolve({job_id:'job'});await p;assert.equal(opened.length,0);p=openVideoOCR('run','source');selectedRun={};resolve({job_id:'job'});await p;assert.equal(opened.length,0);p=openVideoOCR('run','source');resolve({job_id:'job'});await p;assert.deepEqual(opened,[['run','job']]);p=openVideoOCR('run','source',true);assert.deepEqual(calls.at(-1),['video_ocr_start',{run_id:'run',source_job_id:'source',retry:true}]);resolve({job_id:'retry-job'});await p;assert.equal(opened.at(-1)[1],'retry-job');})().catch(e=>{console.error(e);process.exitCode=1});"""
  done=subprocess.run(['/Users/hubowen/.local/node/bin/node','-e',script],capture_output=True,text=True)
  self.assertEqual(done.returncode,0,done.stderr)
if __name__=='__main__':unittest.main()
