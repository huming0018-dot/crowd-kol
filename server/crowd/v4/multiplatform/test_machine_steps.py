import sys,tempfile,uuid,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from machine_steps import MachineSteps
class Client:
 def __init__(self):self.calls=[];self.fail=None
 def call(self,action,payload):
  self.calls.append(payload)
  if self.fail:raise ValueError(self.fail)
  return {'event_ids':[e['event_id'] for e in payload['events']]}
with tempfile.TemporaryDirectory() as t:
 c=Client();path=Path(t)/'events.db';q=MachineSteps(path,c)
 s={'phase':'authorized','lease':{'run_id':str(uuid.uuid4()),'lease_epoch':1},'cookie':'SECRET'}
 q.observe(s);q.observe(s);assert q.status()['pending']==1
 c.fail='cloud_outcome_unknown';q.flush();original=c.calls[-1];assert q.status()['pending']==1
 q=MachineSteps(path,c);c.fail=None;q.flush();assert original==c.calls[-1] and q.status()['pending']==0
 page={'page_index':1,'scope':'reply','checkpoint_committed':False,'saved_rows':4,'page_sha256':'a'*64}
 q.observe(s,'comments_page',**page);q.observe(s,'comments_page',**page);assert q.status()['pending']==1
 q.flush();assert q.status()['pending']==0
 s['phase']='running';q.observe(s);s['phase']='authorized';q.observe(s);assert q.status()['pending']==2
 c.fail='lease_binding_denied';q.flush();assert q.status()['blocked']==2
 other={'phase':'running','lease':{'run_id':str(uuid.uuid4()),'lease_epoch':2}};q.observe(other);c.fail=None;q.flush();assert q.status()['pending']==2
 assert 'SECRET' not in path.read_bytes().decode(errors='ignore')
 q.path=Path(t)/'missing'/'bad';assert q.status()['error']=='machine_steps_store_failed'
 q=MachineSteps(Path(t)/'async.db',c);c.fail=None;q.observe(other)
 import threading,time
 reached=threading.Event();release=threading.Event()
 original_call=c.call
 def slow(*args):reached.set();release.wait(2);return original_call(*args)
 c.call=slow;q.start();assert reached.wait(1)
 started=time.monotonic();q.observe(s);assert time.monotonic()-started<.2
 release.set();q.close()
 print(json.dumps({'gate':'PASS_SQLITE_REPLAY_PRIVACY_ISOLATION','checks':8}))
