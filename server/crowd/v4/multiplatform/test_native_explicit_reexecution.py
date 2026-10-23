import json,sqlite3,uuid,unittest,shutil,fcntl
from pathlib import Path
from test_native_login_recovery import LoginRecovery
from participant_pro_native import NativeService
from participant_pro import ParticipantError
U=lambda:str(uuid.uuid4())
class Reexecution(unittest.TestCase):
 write_run=LoginRecovery.write_run;grant=LoginRecovery.grant;factory=LoginRecovery.factory;msg=LoginRecovery.msg;oldrow=LoginRecovery.oldrow;tearDown=LoginRecovery.tearDown
 def setUp(self):
  LoginRecovery.setUp(self);self.m.subject='2fc8765e-700a-41c1-b325-a21c5faa22ce';self.m.install='3cde2858-39a5-42e1-b7ab-dd62053d2dac';self.sid='903d6888-6397-426c-a5e4-8080597c7101';self.cfg['session_id']=self.sid;self.m.epoch=16
  original=self.run;self.old='356dbc9f-3692-47d7-8c3c-74f5ed101c9b';self.run=self.root/'runs'/self.old;original.rename(self.run)
  self.binding.update(subject=self.m.subject,installation_id=self.m.install);self.native.update(subject=self.m.subject,installation_id=self.m.install)
  self.context.update(binding=self.binding,native_start=self.native,installation_id=self.m.install)
  self.manifest.update(run_id=self.old,participant_pro=self.context);self.manifest['request']['session_id']=self.sid;self.budget['run_id']=self.old;self.write_run()
  self.context['captured_at']='2026-10-18T16:00:00+00:00' # actual first-run DB adds capture time after immutable manifest
  self.seed='729d6565-1cc6-4222-a6bd-670a502f1d05';self.seedrun=self.root/'runs'/self.seed;shutil.copytree(self.run,self.seedrun)
  self.seedcontext={**{k:v for k,v in self.context.items()if k!='captured_at'},'binding':{**self.binding,'generation':15,'native_session':U()},'native_start':{**self.native,'intent':U()},'recovery':{'old_run_id':self.old,'old_context':self.context,'used_requests':4,'total_limit':14,'expected_received':0,'expected_detail_count':176}}
  manifest={**self.manifest,'run_id':self.seed,'participant_pro':self.seedcontext}
  self.seedstatus={'state':'stopped','exit_code':-15,'checkpoint_created':False}
  from shared_request_budget import request_fingerprint
  self.seedbudget={'run_id':self.seed,'used':4,'limit':10,'request_hash':request_fingerprint(manifest['request'])}
  self.cp={'id':self.seed,'platform':'xhs','mode':'search','crawled_note_list':[],'acquisition_committed':False,'is_completed':False,'current_search_page':1,'current_search_id':None,'failed_search_pages':[]}
  (self.seedrun/'data/checkpoints/vox').mkdir(parents=True)
  self.seedmanifest=manifest;self.write_seed()
  session=self.root/'sessions'/self.sid;session.mkdir(parents=True);(session/'active.lock').touch()
  with self.box._db()as db:db.execute('update participant_runs set state=?,run_id=?,context=?where task=29',('running',self.seed,json.dumps(self.seedcontext)))
 def write_seed(self):
  for name,v in [('manifest.json',self.seedmanifest),('status.json',self.seedstatus),('request-budget.json',self.seedbudget),('participant-pro-guard.json',{'events':[{'action':'search','outcome':'rpc_unknown','reason':None}]})]:(self.seedrun/name).write_text(json.dumps(v))
  (self.seedrun/'data/checkpoints/vox'/f'{self.seed}.json').write_text(json.dumps(self.cp))
 def rpc(self,method,p):
  if method=='pro_guard':self.assertIsInstance(p['p_lease'],str);self.assertEqual(p['p_lease'],self.m.lease)
  result=LoginRecovery.rpc(self,method,p)
  if method=='pro_status':result['task']={k:result['task'][k]for k in ['id','received','source_executor','status','target']}
  return result
 def test_explicit_same_task_third_run14_total22_preserves_chain(self):
  oldfiles={str(p.relative_to(self.root)):p.read_bytes()for r in [self.run,self.seedrun]for p in r.rglob('*')if p.is_file()}
  s=NativeService(self.cfg,self.m,self.factory);msg=self.msg();s.start(msg);s.thread.join(3)
  self.assertEqual(s.snapshot()['state'],'complete');self.assertEqual(self.received,2);self.assertEqual(len(self.launches),1)
  p=self.launches[0];self.assertEqual(p['request']['max_api_requests'],14);r=p['participant_context']['recovery'];self.assertEqual(r['used_requests'],8);self.assertEqual(r['total_limit'],22);self.assertEqual(r['old_context'],self.seedcontext);self.assertTrue(r['explicit_reexecution']);self.assertEqual(r['old_context']['recovery']['old_run_id'],self.old)
  self.assertEqual({name:(self.root/name).read_bytes()for name in oldfiles},oldfiles)
  s.start({**msg,'id':U()});self.assertEqual(len(self.launches),1)
 def test_null_status_never_reexecutes(self):
  s=NativeService(self.cfg,self.m,self.factory);before=self.oldrow()
  with self.assertRaises(Exception):s.restore_status(None)
  self.assertEqual(before,self.oldrow());self.assertEqual(self.launches,[])
 def test_fail_closed(self):
  for kind in ['busy','data','delivery','changedbudget','changedcheckpoint','changedstate','changedintent','subject','countchange']:
   with self.subTest(kind=kind):
    x=Reexecution();x.setUp();fd=None
    try:
     msg=x.msg()
     if kind=='busy':fd=open(x.root/'sessions'/x.sid/'active.lock','r');fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
     if kind=='data':
      db=sqlite3.connect(x.seedrun/'pro-observations.sqlite3');db.execute('insert into vox_crawl_observation values(?,?,?,?,?)',(x.seed,'xhs','topic','b'*24,json.dumps({'note_id':'b'*24})));db.commit();db.close()
     if kind=='delivery':
      with x.box._db()as db:db.execute('insert into participant_delivery(request,task,content_id,params,state)values(?,?,?,?,?)',(U(),29,'a'*24,'{}','pending'))
     if kind=='changedbudget':x.seedbudget['used']=5
     if kind=='changedcheckpoint':x.cp['current_search_page']=2
     if kind=='changedstate':x.seedstatus['state']='interrupted_unknown'
     if kind=='changedintent':msg['intent']=x.seedcontext['native_start']['intent']
     if kind=='subject':msg['subject']=U()
     if kind=='countchange':x.changecount=True
     x.write_seed();before=x.oldrow();s=NativeService(x.cfg,x.m,x.factory)
     if kind=='countchange':s.start(msg);s.thread.join(3);self.assertEqual(x.launches,[])
     else:
      with self.assertRaises(Exception):s.start(msg)
      self.assertEqual(before,x.oldrow());self.assertEqual(x.launches,[])
    finally:
     if fd:fd.close()
     x.tearDown()
