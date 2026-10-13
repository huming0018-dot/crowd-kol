import asyncio
import hashlib
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
import uuid
from unittest.mock import patch
from mc_runner import canonical,write,normalize
from declared_subtitles import fetch,register,load_job,subtitle_report

class Response:
 status_code=200
 async def aiter_bytes(self,size):yield b'WEBVTT\n\n00:00.000 --> 00:10.000\nhello\n'
class Context:
 async def __aenter__(self):return Response()
 async def __aexit__(self,*args):pass
class Client:
 def __init__(self):self.calls=0;self.headers={}
 def stream(self,*args,**kwargs):self.calls+=1;assert kwargs['follow_redirects'] is False;return Context()

class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve();self.run=self.root/str(uuid.uuid4());self.output=self.run/'output';self.output.mkdir(parents=True)
  write(self.run/'manifest.json',{'run_id':self.run.name,'request':{'platform':'wb','media':True,'max_api_requests':2}})
  write(self.run/'status.json',{'run_id':self.run.name,'state':'running'});write(self.run/'phase.json',{'api_attempts':1})
  self.detail={'id':'123','subtitles':{'zh':[{'url':'https://weibo.com/fixture.vtt','ext':'vtt'}]}}
  runtime=Path(__file__).resolve().parents[5]/'outputs/subtitle-native-207/yt-dlp-runtime';self.env=patch.dict(os.environ,{'CROWD_YTDLP_RUNTIME':str(runtime)});self.env.start()
 def tearDown(self):self.env.stop();self.tmp.cleanup()
 def call(self,client=None,detail=None):return asyncio.run(fetch('weibo',detail if detail is not None else self.detail,self.output,'123',10,client=client or Client()))
 def normalize(self):
  f=self.output/'weibo/jsonl/content.jsonl';f.parent.mkdir(parents=True,exist_ok=True);f.write_text('{"note_id":"123","title":"native title","content":"original body"}\n');sha=hashlib.sha256(f.read_bytes()).hexdigest()
  origin={'run_id':self.run.name,'file_sha256':sha,'line':1}
  b=normalize('wb','content',json.loads(f.read_text()),origin)
  write(self.run/'normalized.json',{'run_id':self.run.name,'source_kind':'mediacrawler_api','reward_eligible':False,'records':[b],'files':[{'sha256':sha,'path':str(f.relative_to(self.run))}]})
  write(self.run/'status.json',{'run_id':self.run.name,'state':'completed'})
  jobs=types.SimpleNamespace(root=self.root/'media-processing',subtitle_run_folder=lambda run:self.run)
  return jobs
 def test_complete_fetch_job_replay(self):
  c=Client();r=self.call(c);self.assertEqual(r['status'],'available');self.assertEqual(c.calls,1);self.assertEqual(self.call(c),r);self.assertEqual(c.calls,1)
  j=self.normalize();state=register(j,self.run,'123');self.assertEqual(state['state'],'completed');self.assertEqual(load_job(j,state['job_id'])['result'][0]['evidence']['segments'][0]['text'],'hello')
  _,report,raw=subtitle_report(j,state['job_id']);self.assertEqual(report['schema'],'crowd-declared-subtitle-report-v1');self.assertEqual(report['subtitle_provenance']['semantic_completeness'],'unknown');self.assertNotIn('audio_source_job_id',report);self.assertNotIn('https:',raw)
 def test_exhausted_unavailable_no_fetch(self):
  write(self.run/'phase.json',{'api_attempts':2});c=Client();self.assertEqual(self.call(c)['reason'],'subtitle_request_budget_exhausted');self.assertEqual(c.calls,0)
 def test_missing_track_no_fetch(self):
  c=Client();self.assertEqual(self.call(c,{'id':'123','photo':{'caption':'title'}})['status'],'unavailable');self.assertEqual(c.calls,0)
 def test_transport_failure_unknown_no_retry(self):
  c=Client()
  def fail(*args,**kwargs):c.calls+=1;raise OSError('network')
  c.stream=fail;r=self.call(c);self.assertEqual(r['status'],'failed');self.assertIsNone(r['source_requests']);self.assertEqual(r['reserved_requests'],1);self.call(c);self.assertEqual(c.calls,1)
 def test_response_limit(self):
  c=Client()
  class Large(Response):
   async def aiter_bytes(self,size):yield b'x'*200001
  class L(Context):
   async def __aenter__(self):return Large()
  c.stream=lambda *args,**kwargs:L();self.assertEqual(self.call(c)['status'],'failed')
 def test_redirect_not_followed(self):
  c=Client()
  class Redirect(Response):status_code=302
  class R(Context):
   async def __aenter__(self):return Redirect()
  c.stream=lambda *args,**kwargs:R();self.assertEqual(self.call(c)['status'],'failed')
 def test_source_body_tamper(self):
  self.call();j=self.normalize();state=register(j,self.run,'123');p=self.run/'normalized.json';x=json.loads(p.read_text());x['records'][0]['text']='changed';write(p,x)
  with self.assertRaises(ValueError):load_job(j,state['job_id'])
 def test_forged_normalized_body_and_hash_before_register(self):
  self.call();j=self.normalize();p=self.run/'normalized.json';x=json.loads(p.read_text());body=x['records'][0];body['body']='forged body';body['title']='forged title';body['record_hash']=hashlib.sha256(canonical({k:v for k,v in body.items() if k not in ('record_hash','discovery_kind')}).encode()).hexdigest();write(p,x)
  with self.assertRaisesRegex(ValueError,'subtitle_source_changed'):register(j,self.run,'123')
  self.assertFalse((j.root.parent/'subtitle-jobs').exists())
 def test_wrong_origin_line_before_register(self):
  self.call()
  for line in (0,True,2):
   j=self.normalize();p=self.run/'normalized.json';x=json.loads(p.read_text());body=x['records'][0];body['origin']['line']=line;body['record_hash']=hashlib.sha256(canonical({k:v for k,v in body.items() if k not in ('record_hash','discovery_kind')}).encode()).hexdigest();write(p,x)
   with self.assertRaisesRegex(ValueError,'subtitle_source_changed'):register(j,self.run,'123')
   self.assertFalse((j.root.parent/'subtitle-jobs').exists())
 def test_wrong_valid_origin_line_before_register(self):
  self.call();j=self.normalize();f=self.output/'weibo/jsonl/content.jsonl';f.write_text(f.read_text()+'{"note_id":"456","title":"other title","content":"other body"}\n');sha=hashlib.sha256(f.read_bytes()).hexdigest();p=self.run/'normalized.json';x=json.loads(p.read_text());body=x['records'][0];body['origin'].update(file_sha256=sha,line=2);x['files'][0]['sha256']=sha;body['record_hash']=hashlib.sha256(canonical({k:v for k,v in body.items() if k not in ('record_hash','discovery_kind')}).encode()).hexdigest();write(p,x)
  with self.assertRaisesRegex(ValueError,'subtitle_source_changed'):register(j,self.run,'123')
  self.assertFalse((j.root.parent/'subtitle-jobs').exists())
 def test_original_jsonl_tamper(self):
  self.call();j=self.normalize();state=register(j,self.run,'123');(self.output/'weibo/jsonl/content.jsonl').write_text('changed')
  with self.assertRaises(ValueError):load_job(j,state['job_id'])
 def test_cross_run_origin(self):
  self.call();j=self.normalize();state=register(j,self.run,'123');p=self.run/'normalized.json';x=json.loads(p.read_text());x['records'][0]['origin']['run_id']=str(uuid.uuid4());write(p,x)
  with self.assertRaises(ValueError):load_job(j,state['job_id'])
 def test_raw_caption_tamper(self):
  self.call();j=self.normalize();state=register(j,self.run,'123');(self.output/'weibo/declared-subtitles/123.source').write_text('broken')
  with self.assertRaises(ValueError):load_job(j,state['job_id'])
 def test_projection_and_partial_tamper(self):
  self.call();j=self.normalize();state=register(j,self.run,'123');p=self.output/'weibo/declared-subtitles/123.metadata.json';x=json.loads(p.read_text());x['content_id']='456';write(p,x)
  with self.assertRaises(ValueError):load_job(j,state['job_id'])
 def test_completed_run_never_new_dispatch(self):
  write(self.run/'status.json',{'run_id':self.run.name,'state':'completed'});c=Client()
  with self.assertRaises(ValueError):self.call(c)
  self.assertEqual(c.calls,0)
 def test_credentials_not_sent(self):
  c=Client();c.headers={'Authorization':'private'}
  with self.assertRaises(ValueError):self.call(c)
  self.assertEqual(c.calls,0)

if __name__=='__main__':unittest.main()
