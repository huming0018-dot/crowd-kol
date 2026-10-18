import hashlib,json,sqlite3,tempfile,threading,unittest,uuid
from pathlib import Path
from participant_pro_native import NativeService
from participant_pro import ParticipantOutbox,ParticipantError,local_runner
from participant_native_rpc import frame,ProtocolError
from pro_executor import PINNED_COMMIT
from test_participant_pro_native import Mux,record
U=lambda:str(uuid.uuid4())
class LoginRecovery(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.m=Mux();self.m.epoch=13;self.old=U();self.new=U();self.oldsession=U();self.sid=U();self.oldintent=U();self.launches=[];self.calls=[];self.received=0;self.detail=176;self.stop_control=False;self.changecount=False
  self.cfg={'root':str(self.root),'mc_root':str(self.root),'session_id':self.sid,'purpose':'noncommercial_research','max_api_requests':14}
  self.binding={'profile':'native-messaging','transport':'native','subject':self.m.subject,'installation_id':self.m.install,'generation':12,'native_session':self.oldsession}
  self.native={'subject':self.m.subject,'installation_id':self.m.install,'task_id':29,'intent':self.oldintent}
  self.context={'binding':self.binding,'native_start':self.native,'target':2,'limit':2,'task_id':29,'installation_id':self.m.install,'known_ids':[],'lease':self.m.lease,'node':None,'request_sha256':'a'*64}
  self.box=ParticipantOutbox(self.root,lambda *a:None)
  with self.box._db()as db:db.execute('insert into participant_runs values(?,?,?,?)',(29,'source_failed',self.old,json.dumps(self.context)))
  self.run=self.root/'runs'/self.old;self.run.mkdir(parents=True)
  self.manifest={'run_id':self.old,'source':{'commit':PINNED_COMMIT},'request':{'session_id':self.sid,'platform':'xhs','mode':'search'},'participant_pro':self.context}
  self.status={'state':'login_required','exit_code':77,'checkpoint_created':False};self.budget={'run_id':self.old,'used':4,'limit':14}
  self.write_run();db=sqlite3.connect(self.run/'pro-observations.sqlite3');db.execute('create table vox_crawl_observation(operation_id text,platform text,kind text,entity_id text,payload text)');db.close()
  self.m.call=self.rpc
 def tearDown(self):self.tmp.cleanup()
 def write_run(self):
  for n,v in [('manifest.json',self.manifest),('status.json',self.status),('request-budget.json',self.budget)]: (self.run/n).write_text(json.dumps(v))
 def grant(self):return {'schema':'crowd-acceptance-batch-v1','id':'13761788-0860-40b8-a8ac-69a20ae1a5a1','task_id':29,'installation_id':self.m.install,'baseline_received':0,'extra_limit':2,'remaining':2-self.received,'target':2}
 def rpc(self,method,p):
  if self.m.stopped.is_set():raise ProtocolError('participant_stopped')
  self.calls.append((method,p))
  if method=='scope':return {'subject':self.m.subject,'installation_id':self.m.install,'generation':self.m.epoch}
  task={'id':29,'received':self.received,'target':2,'status':'complete' if self.received==2 else 'leased','source_executor':'mediacrawler_pro','lease_token':self.m.lease,'query':'品牌','anchor_terms':['品牌'],'comments_capture':False,'known_note_ids':[]}
  if method=='pro_status':return {'task':task,'acceptance_supplement':self.grant()}
  if method=='pro_claim':self.m.lease=U();task['lease_token']=self.m.lease;return {'source_executor':'mediacrawler_pro','reward_eligible':False,'known_note_ids':[],'task':task,'acceptance_supplement':self.grant()}
  if method=='pro_guard':
   value=self.detail
   if self.changecount:self.detail+=1
   if self.stop_control:self.m.stop()
   return {'allowed':True,'reason':None,'counts':{'detail':value}}
  if method=='pro_receipt':return {'found':False,'receipt':None,'request':p['p_request']}
  if method=='pro_submit':
   self.received+=1;return {'request':p['p_request'],'gate':'received','inserted':True,'duplicate':False,'task_received':self.received,'proof_id':55+self.received,'source_kind':'mediacrawler_pro','reward_eligible':False,'record_hash':p['p_payload']['record']['record_hash']}
  if method=='pro_finish':return {'received':2,'status':'complete'}
  raise AssertionError(method)
 def factory(self,*a,**kw):
  inspect=local_runner(self.root,self.root)
  def run(action,p):
   if action=='inspect':return inspect(action,p) # actual saved manifest/status/budget + original SQLite observation reader
   if action=='start':self.launches.append(p);return {'run_id':self.new}
   if action=='status':return {'state':'completed'}
   if action=='import':return {'records':[record('b'*24),record('c'*24)],'manifest':{'source':{'commit':PINNED_COMMIT}}}
   raise AssertionError(action)
  return run
 def msg(self,**extra):return frame('pro_start',self.m.session,self.m.epoch,subject=self.m.subject,installation_id=self.m.install,task_id=29,intent=U(),**extra)
 def oldrow(self):
  with self.box._db()as db:return db.execute('select state,run_id,context from participant_runs where task=29').fetchone()
 def test_explicit_native_start_full_sqlite_twoack_archive_and10(self):
  originals={p.name:p.read_bytes()for p in self.run.iterdir()};s=NativeService(self.cfg,self.m,self.factory);msg=self.msg();s.start(msg);s.thread.join(3);self.assertFalse(s.thread.is_alive());self.assertEqual(s.snapshot()['state'],'complete');self.assertEqual(self.received,2);self.assertEqual(len(self.launches),1)
  context=self.launches[0]['participant_context'];self.assertEqual(self.launches[0]['request']['max_api_requests'],10);self.assertEqual(context['recovery']['total_limit'],14);self.assertEqual(context['recovery']['used_requests'],4);self.assertEqual(context['recovery']['expected_detail_count'],176);self.assertEqual(context['recovery']['old_context'],self.context);self.assertEqual(context['binding']['generation'],13);self.assertEqual(context['native_start']['intent'],msg['intent']);self.assertEqual(context['recovery']['old_context']['binding']['generation'],12)
  self.assertEqual({p.name:p.read_bytes()for p in self.run.iterdir()},originals)
  s.start({**msg,'id':U()});self.assertEqual(len(self.launches),1)
  with self.box._db()as db:self.assertEqual(db.execute("select count(*) from participant_delivery where state='delivered'").fetchone()[0],2)
 def test_status_only_reconnect_never_prepares_source(self):
  self.m.session=self.oldsession;self.m.epoch=12;before=self.oldrow();s=NativeService(self.cfg,self.m,self.factory)
  s.handle(frame('pro_status',self.m.session,12,run_id=self.old));self.assertEqual(s.snapshot()['state'],'source_failed');self.assertEqual(self.launches,[]);self.assertEqual(self.oldrow(),before)
  with self.assertRaises(ProtocolError):s.start(self.msg())
 def test_denials_preserve_row_and_no_source(self):
  # Each case constructs a separate complete real NativeService/Worker/SQLite fixture.
  cases=['unknown','exit','checkpoint','observations','budget','session','subject','intent','epoch','delivery','recovery_used','stop','count_race']
  self.assertEqual(self.launches,[])
  for case in cases:
   with self.subTest(case=case):
    other=LoginRecovery();other.setUp()
    try:
     msg=other.msg()
     if case=='unknown':
      with other.box._db()as db:db.execute("update participant_runs set state='source_unknown'")
     if case=='exit':other.status['exit_code']=86
     if case=='checkpoint':other.status['checkpoint_created']=True
     if case=='observations':
      db=sqlite3.connect(other.run/'pro-observations.sqlite3');db.execute('insert into vox_crawl_observation values(?,?,?,?,?)',(other.old,'xhs','topic','d'*24,json.dumps({'note_id':'d'*24})));db.commit();db.close()
     if case=='budget':other.budget['used']=5
     if case=='session':other.manifest['request']['session_id']=U()
     if case=='subject':msg['subject']=U()
     if case=='intent':msg['intent']=other.oldintent
     if case=='epoch':other.m.epoch=11;msg['epoch']=11
     if case=='delivery':
      with other.box._db()as db:db.execute("insert into participant_delivery(request,task,content_id,params,state,receipt) values(?,?,?,?,?,?)",(U(),29,'a'*24,'{}','pending',None))
     if case=='recovery_used':
      c={**other.context,'recovery':{'already':'archived'}}
      with other.box._db()as db:db.execute('update participant_runs set context=?',(json.dumps(c),))
     if case=='stop':other.stop_control=True
     if case=='count_race':other.changecount=True
     other.write_run();before=other.oldrow();s=NativeService(other.cfg,other.m,other.factory)
     if case=='count_race':
      s.start(msg);s.thread.join(3);self.assertEqual(len(other.launches),0)
     else:
      with self.assertRaises((ParticipantError,ProtocolError,KeyError)):s.start(msg)
      self.assertEqual(other.oldrow(),before);self.assertEqual(other.launches,[])
    finally:other.tearDown()
if __name__=='__main__':unittest.main()
