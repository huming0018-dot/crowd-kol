"""Actual supervisor; fake child only. No source process or external network."""
import json,os,sys,tempfile,uuid
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parent),'/Users/hubowen/Desktop/桌面 - 胡博文的MacBook Pro/pushpull/crowd-kol/server/crowd/v4/multiplatform']
import mc_runner as m
rows=[]
for fixture in ('missing','malformed','list','symlink','oversize','fifo','deep_json','valid','bridge'):
 for code in (0,77,84,85,86):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);rid=str(uuid.uuid4());run=root/'runs'/rid;run.mkdir(parents=True)
   m.write(run/'manifest.json',{'run_id':rid,'request':{'platform':'xhs','mode':'detail','timeout_seconds':60},'executor':{'backend':'pro','python':'unused-fake'}})
   m.write(run/'status.json',{'state':'running','phase':'running'})
   phase=run/'phase.json'
   if fixture=='malformed':phase.write_text('bad JSON')
   elif fixture=='list':phase.write_text('[]')
   elif fixture=='symlink':
    (root/'target').write_text('{"phase":"running"}');phase.symlink_to(root/'target')
   elif fixture=='oversize':phase.write_bytes(b' '*(1024*1024+1))
   elif fixture=='fifo':os.mkfifo(phase)
   elif fixture=='deep_json':phase.write_text('['*1200+']'*1200)
   elif fixture=='valid':m.write(phase,{'phase':'running','api_attempts':1})
   elif fixture=='bridge':m.write(phase,{'phase':'failed','api_attempts':1,'failure_reason':'pro_cookiebridge_unavailable','bridge_reason':'extension_disconnected'})
   class Child:
    pid=999999
    polls=0
    def poll(self):self.polls+=1;return None if self.polls==1 else code
    def wait(self,*a,**kw):return code
   fd=os.open(root/'fixture.lock',os.O_CREAT|os.O_RDWR,0o600)
   with patch.object(m.subprocess,'Popen',return_value=Child()),patch.object(m.time,'sleep',return_value=None):m.worker(root,root,rid,fd)
   state=m.read(run/'status.json')
   expected='login_required' if code==77 else 'failed' if code in (84,85,86) or fixture not in ('missing','valid','bridge') else 'completed'
   assert state['state']==expected,(fixture,code,state)
   assert state['exit_code']==code and state['coverage']=='unverified'
   if fixture=='bridge' and code==86:assert state['reason']=='pro_cookiebridge_unavailable'
   elif code in (77,84,85,86):assert state['reason']=={77:'login_required',84:'pro_self_check_unsupported',85:'pro_pending_run_resolution_required',86:'pro_login_verification_failed'}[code]
   if code==0 and fixture not in ('missing','valid','bridge'):assert state['reason']=='phase_observation_failed'
   rows.append({'fixture':fixture,'exit_code':code,'final':state['state'],'reason':state['reason']})
# Stop and timeout reasons retain precedence over a broken diagnostic.
for cause in ('stop','timeout'):
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);rid=str(uuid.uuid4());run=root/'runs'/rid;run.mkdir(parents=True)
  m.write(run/'manifest.json',{'run_id':rid,'request':{'platform':'xhs','mode':'detail','timeout_seconds':-1 if cause=='timeout' else 60},'executor':{'backend':'pro','python':'unused-fake'}})
  m.write(run/'status.json',{'state':'running'});(run/'phase.json').write_text('bad JSON')
  if cause=='stop':m.write(run/'stop.json',{'origin':'user','reason':'user_stop'})
  class Child:
   pid=999999
   def poll(self):return 0
   def wait(self,*a,**kw):return 0
  fd=os.open(root/'fixture.lock',os.O_CREAT|os.O_RDWR,0o600)
  with patch.object(m.subprocess,'Popen',return_value=Child()):m.worker(root,root,rid,fd)
  state=m.read(run/'status.json');assert state['reason']==('user_stop' if cause=='stop' else 'wall_timeout'),state
  rows.append({'case':cause,'reason':state['reason'],'final':state['state']})
Path(__file__).with_name('WORKER-PHASE-REGRESSION.json').write_text(json.dumps({'all_pass':True,'cases':rows,'source_processes_started':0},indent=2)+'\n')
print(json.dumps({'passed':len(rows),'source_processes_started':0}))
