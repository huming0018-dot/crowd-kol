import hashlib,json,os,socket,tempfile,threading,time,unittest,uuid
from pathlib import Path
from unittest.mock import patch
import mc_runner
from participant_pro_native import NativeService,load_config
from participant_native_rpc import frame,validate,ProtocolError,FrameIO,NativeMux,ChildTransport,relay_child,from_context
from participant_pro import ParticipantOutbox
from pro_executor import PINNED_COMMIT
U=lambda:str(uuid.uuid4())
def record(cid):
 r={'kind':'content','platform':'xiaohongshu','content_id':cid,'title':'fixture','body':'fixture正文','source_kind':'mediacrawler_api','reward_eligible':False}
 r['record_hash']=hashlib.sha256(mc_runner.canonical(r).encode()).hexdigest();return r
class Mux:
 def __init__(self):
  self.session=U();self.epoch=7;self.stopped=threading.Event();self.disconnected=threading.Event();self.lock=threading.Lock();self.pending={};self.frames=[];self.port=self;self.calls=[];self.commands=__import__('queue').Queue();self.subject=U();self.install=U();self.lease=U();self.received=2
 def send(self,v):validate(v);self.frames.append(v)
 def stop(self):self.stopped.set()
 def call(self,m,p):
  self.calls.append((m,p))
  if m=='scope':return {'subject':self.subject,'installation_id':self.install,'generation':7}
  if m=='pro_claim':return {'source_executor':'mediacrawler_pro','reward_eligible':False,'known_note_ids':['a'*24], 'task':{'id':201,'received':2,'target':4,'lease_token':self.lease,'query':'原关键词','anchor_terms':['品牌'],'comments_capture':False,'known_note_ids':['a'*24]},'acceptance_supplement':{'schema':'crowd-acceptance-batch-v1','id':U(),'task_id':201,'installation_id':self.install,'baseline_received':2,'extra_limit':2,'remaining':2,'target':4}}
  if m=='pro_receipt':return {'found':False,'request':p['p_request'],'receipt':None}
  if m=='pro_submit':
   self.received+=1;return {'request':p['p_request'],'gate':'received','inserted':True,'duplicate':False,'task_received':self.received,'proof_id':self.received,'source_kind':'mediacrawler_pro','reward_eligible':False,'record_hash':p['p_payload']['record']['record_hash']}
  if m=='pro_finish':return {'status':'complete','received':4}
  if m=='pro_status':return {'task':{'id':201,'received':4,'target':4,'status':'complete','source_executor':'mediacrawler_pro'}}
  raise AssertionError(m)
class Tests(unittest.TestCase):
 def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.m=Mux();self.config={'root':str(self.root),'mc_root':str(self.root),'session_id':U(),'purpose':'noncommercial_research','max_api_requests':14};self.run=U();self.calls=[]
 def tearDown(self):self.temp.cleanup()
 def factory(self,*a,**kw):
  def runner(action,p):
   self.calls.append(action)
   if action=='start':
    self.assertEqual(p['request']['targets'],['品牌']);self.assertEqual(p['request']['max_items'],2);self.assertEqual(p['request']['max_api_requests'],14);self.assertFalse(p['request']['comments']);self.assertNotIn('participant_rpc_fd',p['participant_context']);self.assertNotIn('CROWD_PARTICIPANT_RPC_FD',p['participant_context']['binding']);return {'run_id':self.run}
   if action=='status':return {'state':'completed'}
   if action=='import':return {'records':[record('b'*24),record('c'*24)],'manifest':{'source':{'commit':PINNED_COMMIT}}}
   self.fail(action)
  return runner
 def start_frame(self):return frame('pro_start',self.m.session,7,subject=self.m.subject,installation_id=self.m.install,task_id=201,intent=U())
 def test_hello_no_scope_source_and_fixed_state(self):
  service=NativeService(self.config,self.m,self.factory);service.handle(frame('pro_hello',self.m.session,7,version=1));self.assertEqual(self.m.frames[-1]['state'],'ready');self.assertEqual(self.m.calls,[]);self.assertEqual(self.calls,[])
 def test_whole_worker_none_request_durable_two_receipts_stop_and_idempotent(self):
  service=NativeService(self.config,self.m,self.factory);msg=self.start_frame();service.handle(msg);service.thread.join(2)
  self.assertFalse(service.thread.is_alive());self.assertEqual(service.snapshot()['state'],'complete');self.assertEqual(service.snapshot()['received'],4);self.assertEqual(service.snapshot()['pending'],0);self.assertEqual(self.calls.count('start'),1)
  service.handle({**msg,'id':U()});self.assertEqual(self.calls.count('start'),1);self.assertEqual(len({v['id'] for v in self.m.frames}),len(self.m.frames))
  with self.assertRaises(ProtocolError):service.handle({**msg,'id':U(),'intent':U()})
  restored=NativeService(self.config,self.m,self.factory);before=len(self.m.calls);restored.handle(frame('pro_status',self.m.session,7,run_id=self.run));self.assertEqual(restored.snapshot()['state'],'complete');self.assertEqual(len(self.m.calls),before)
  with self.assertRaises(ProtocolError):restored.handle(msg)
 def test_reconnect_wrong_session_has_no_source(self):
  service=NativeService(self.config,self.m,self.factory)
  with self.assertRaises(ProtocolError):service.handle(frame('pro_status',self.m.session,7,run_id=self.run))
  self.assertEqual(self.calls,[]);self.assertEqual(self.m.calls,[])
 def test_eof_existing_runner_stop_not_new_source(self):
  service=NativeService(self.config,self.m,self.factory);msg=self.start_frame();service.handle(msg);service.thread.join(2)
  with patch('participant_pro_native.mc_runner.status',return_value={'state':'running'}),patch('participant_pro_native.mc_runner.stop',return_value={'state':'running','stop_requested':True}) as stop:
   service.stop_owned();stop.assert_called_once_with(str(self.root),{'run_id':self.run,'origin':'user','reason':'user_stop'});self.assertEqual(service.last['state'],'unknown')
 def test_fd_environment_is_socket_only_not_manifest(self):
  a,b=socket.socketpair()
  try:
   context={'binding':{'transport':'native'}};env,fds=mc_runner.participant_fd_environment(context,b.fileno());self.assertEqual(fds,(b.fileno(),));self.assertEqual(env['CROWD_PARTICIPANT_RPC_FD'],str(b.fileno()))
   with patch.dict(os.environ,env,clear=True):self.assertEqual(mc_runner.participant_fd_environment(context,inherited=True)[1],fds)
   with self.assertRaises(mc_runner.BridgeError):mc_runner.participant_fd_environment(context,1)
   with self.assertRaises(mc_runner.BridgeError):mc_runner.participant_fd_environment(None,b.fileno())
  finally:a.close();b.close()
 def test_child_own_endpoint_relay_and_context_factory_no_cdp(self):
  a,b=socket.socketpair();binding={'transport':'native','profile':'native-messaging','subject':self.m.subject,'installation_id':self.m.install,'generation':7,'native_session':self.m.session}
  c={'binding':binding,'task_id':201}
  class Remote:
   session=self.m.session;epoch=7;disconnected=threading.Event()
   def call(self,m,p):return {'matched':True,'kind':m}
  t=threading.Thread(target=relay_child,args=(a,Remote()),daemon=True);t.start()
  try:
   with patch.dict(os.environ,{'CROWD_PARTICIPANT_RPC_FD':str(b.fileno())}):rpc=from_context(c)
   self.assertIsInstance(rpc,ChildTransport);self.assertTrue(rpc('verify_platform_principal',{'uid':'a'*24})['matched'])
  finally:b.close();rpc.socket.close()
 def test_real_two_process_fd_inheritance_original_hook_factory(self):
  import subprocess,sys
  a,b=socket.socketpair();calls=[]
  context={'schema':'crowd-participant-pro-local-v1','binding':{'transport':'native','profile':'native-messaging','subject':self.m.subject,'installation_id':self.m.install,'generation':7,'native_session':self.m.session},'task_id':201,'lease':U(),'installation_id':self.m.install,'known_ids':[],'limit':2}
  class Remote:
   session=self.m.session;epoch=7;disconnected=threading.Event()
   def call(inner,method,params):
    calls.append(method)
    if method=='verify_platform_principal':return {'matched':True,'subject':self.m.subject,'installation_id':self.m.install}
    if method=='pro_guard':return {'allowed':True,'reason':None}
    raise AssertionError(method)
  threading.Thread(target=relay_child,args=(a,Remote(),201,self.m.install),daemon=True).start()
  second="import os,json,asyncio;from participant_native_rpc import from_context;from participant_pro_hooks import ParticipantNativeHooks;c=json.loads(os.environ['TEST_CONTEXT']);h=ParticipantNativeHooks(c,from_context(c));asyncio.run(h.identity('xhs','a'*24));asyncio.run(h.guard('detail','b'*24));print('hook_ok')"
  first="import os,subprocess,sys;from mc_runner import participant_fd_environment;e,f=participant_fd_environment({'binding':{'transport':'native'}},inherited=True);r=subprocess.run([sys.executable,'-B','-c',os.environ['TEST_SECOND']],env=e,pass_fds=f,capture_output=True,text=True);print(r.stdout.strip());sys.exit(r.returncode)"
  env={**os.environ,'CROWD_PARTICIPANT_RPC_FD':str(b.fileno()),'TEST_CONTEXT':json.dumps(context),'TEST_SECOND':second}
  try:
   result=subprocess.run([sys.executable,'-B','-c',first],env=env,pass_fds=(b.fileno(),),capture_output=True,text=True,timeout=5)
   self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(result.stdout.strip(),'hook_ok');self.assertEqual(calls,['verify_platform_principal','pro_guard'])
  finally:b.close()
 def test_stop_before_and_during_launch_uses_original_stop_only(self):
  service=NativeService(self.config,self.m,self.factory);self.m.stop()
  with self.assertRaises(ProtocolError):service.runner()('start',{})
  self.assertEqual(self.calls,[])
  self.m.stopped.clear()
  def racing_factory(*a,**kw):
   def call(action,p):self.m.stop();return {'run_id':self.run}
   return call
  service=NativeService(self.config,self.m,racing_factory)
  with patch('participant_pro_native.mc_runner.stop',return_value={'state':'running'}) as stop:
   service.runner()('start',{});stop.assert_called_once_with(str(self.root),{'run_id':self.run,'origin':'user','reason':'user_stop'})
 def test_missing_installation_main_output_is_only_framed_not_ready(self):
  import io,subprocess,sys,participant_pro_native
  out=io.BytesIO();FrameIO(io.BytesIO(),out).send(frame('pro_hello',self.m.session,7,version=1))
  result=subprocess.run([sys.executable,'-B',participant_pro_native.__file__,'--config',str(self.root/'absent.json')],input=out.getvalue(),capture_output=True,timeout=5)
  self.assertEqual(result.returncode,0);self.assertEqual(result.stderr,b'')
  answer=FrameIO(io.BytesIO(result.stdout),io.BytesIO()).read();self.assertEqual(answer['state'],'not_ready');self.assertEqual(answer['error'],'participant_installation_invalid');self.assertNotIn(str(self.root),result.stdout.decode('utf8',errors='ignore'))
 def test_explicit_stop_status_readonly_final_gate_and_unknown_negatives(self):
  from participant_pro import ParticipantProWorker
  from participant_native_rpc import NativeTransport
  service=NativeService(self.config,self.m,self.factory);rpc=NativeTransport(self.m,self.m.subject,self.m.install,201)
  service.worker=ParticipantProWorker(self.root,rpc,lambda *a:self.fail('no source'),task_id=201,installation_id=self.m.install,subject=self.m.subject,session_id=self.config['session_id'],known_ids=[])
  context={'binding':rpc.binding,'target':2,'limit':2}
  with service.worker.outbox._db() as db:db.execute('insert into participant_runs values(?,?,?,?)',(201,'running',self.run,json.dumps(context)))
  class Ended:
   def is_alive(self):return False
  service.thread=Ended();evidence={'origin':'user','reason':'user_stop'}
  with patch('participant_pro_native.mc_runner.stop',return_value={'state':'running','stop_requested':True,'stop_context':evidence}) as stop:
   service.handle(frame('pro_stop',self.m.session,7,run_id=self.run));self.assertEqual(service.last['state'],'unknown')
   before=None
   with service.worker.outbox._db() as db:before=db.execute('select * from participant_runs').fetchall()
   cases=[({'state':'stopped','stop_context':evidence},'stopped'),({'state':'interrupted_unknown','stop_context':evidence},'unknown'),({'state':'running','stop_context':evidence},'unknown'),({'state':'completed','stop_context':evidence},'unknown'),({'state':'stopped'},'unknown'),({'state':'stopped','stop_context':{'origin':'cloud_worker','reason':'lease_lost'}},'unknown')]
   for source,expected in cases:
    service.last={'state':'unknown'}
    with patch('participant_pro_native.mc_runner.status',return_value=source):service.handle(frame('pro_status',self.m.session,7,run_id=self.run))
    self.assertEqual(service.last['state'],expected)
   with service.worker.outbox._db() as db:self.assertEqual(db.execute('select * from participant_runs').fetchall(),before)
   stop.assert_called_once()
   # Native RPC outstanding, running parent, durable delivery, changed owned run all hold UNKNOWN.
   for barrier in ('rpc','thread','delivery','run'):
    service.last={'state':'unknown'}
    if barrier=='rpc':self.m.pending['outstanding']=object()
    if barrier=='thread':service.thread=type('Active',(),{'is_alive':lambda s:True})()
    if barrier=='delivery':service.worker.outbox.stage(record('d'*24),{'task_id':201,'lease':self.m.lease,'installation_id':self.m.install},{'local_run_id':self.run,'upstream_commit':PINNED_COMMIT,'request_sha256':'e'*64,'captured_at':'2026-10-18T10:00:00Z'})
    if barrier=='run':
     with service.worker.outbox._db() as db:db.execute('update participant_runs set run_id=?',(U(),))
    with patch('participant_pro_native.mc_runner.status',return_value={'state':'stopped','stop_context':evidence}):service.reconcile_stopped()
    self.assertEqual(service.last['state'],'unknown')
    self.m.pending.clear();service.thread=Ended()
    with service.worker.outbox._db() as db:
     if barrier=='delivery':db.execute('delete from participant_delivery')
     if barrier=='run':db.execute('update participant_runs set run_id=?',(self.run,))
   # Implicit EOF is not promoted by this explicit-stop reconciliation.
   service.explicit_stop_run=None;service.last={'state':'unknown'}
   with patch('participant_pro_native.mc_runner.status',return_value={'state':'stopped','stop_context':evidence}):service.reconcile_stopped()
   self.assertEqual(service.last['state'],'unknown');stop.assert_called_once()
 def test_config_hash_permissions_no_browser_paths(self):
  import participant_pro_native as entry
  cfg={'schema':'crowd-participant-pro-install-v1','python':__import__('sys').executable,'entry':str(Path(entry.__file__).resolve()),'entry_sha256':hashlib.sha256(Path(entry.__file__).read_bytes()).hexdigest(),**self.config}
  p=self.root/'config.json';p.write_text(json.dumps(cfg));p.chmod(0o600);self.assertEqual(load_config(p)['session_id'],cfg['session_id'])
  p.chmod(0o644)
  with self.assertRaises(ProtocolError):load_config(p)
  p.chmod(0o600);cfg['entry_sha256']='0'*64;p.write_text(json.dumps(cfg))
  with self.assertRaises(ProtocolError):load_config(p)
if __name__=='__main__':unittest.main()
