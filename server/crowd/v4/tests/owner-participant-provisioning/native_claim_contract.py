"""Consume the exact preceding isolated PG claim, not a hand-made extra task contract."""
import argparse,json,tempfile,uuid
from pathlib import Path
from participant_pro_native import NativeService
from participant_native_rpc import frame
from participant_pro import ParticipantOutbox
from pro_executor import argv_for
from test_participant_pro_native import Mux
ap=argparse.ArgumentParser();ap.add_argument('--wire',type=Path,required=True);args=ap.parse_args();wire=json.loads(args.wire.read_text());m=Mux();m.subject=wire['subject'];m.install=wire['installation_id'];m.received=0;calls=[];launches=[]
def rpc(method,p):
 calls.append(method)
 if method=='scope':return {'subject':m.subject,'installation_id':m.install,'generation':7}
 assert method=='pro_claim' and p=={'p_task':wire['task_id'],'p_installation_id':m.install};return wire['claim']
m.call=rpc
with tempfile.TemporaryDirectory()as t:
 root=Path(t)
 def factory(*a,**kw):
  def run(action,p):
   if action=='start':launches.append(p);return {'run_id':str(uuid.uuid4())}
   if action=='status':return {'state':'running'}
   raise AssertionError('unexpected/source action '+action)
  return run
 cfg={'root':str(root),'mc_root':str(root),'session_id':str(uuid.uuid4()),'purpose':'noncommercial_research','max_api_requests':14};service=NativeService(cfg,m,factory)
 service.start(frame('pro_start',m.session,7,subject=m.subject,installation_id=m.install,task_id=wire['task_id'],intent=str(uuid.uuid4())));service.thread.join(.05);m.stopped.set();service.thread.join(1)
 assert len(launches)==1,service.last
 request=launches[0]['request'];context=launches[0]['participant_context'];authority=wire['claim']['pro_comment_options']
 assert context['task_comment_options']==authority and context['binding']['subject']==wire['subject'] and context['installation_id']==wire['installation_id']
 assert {k:request[k]for k in ('comments','replies','max_comments')}=={k:authority[k]for k in ('comments','replies','max_comments')}
 assert request['max_api_requests']==8 and request['max_items']==1 and context['target']==1 and context['limit']==1
 argv=argv_for(request);assert '--enable_comments'in argv and '--enable_sub_comments'in argv and argv[argv.index('--max_comments_count')+1]=='0'
 with ParticipantOutbox(root,lambda*a:None)._db()as db:
  row=db.execute('select state,context from participant_runs where task=?',(wire['task_id'],)).fetchone();assert row[0]=='running'and json.loads(row[1])['task_comment_options']==authority
  assert db.execute('select count(*)from participant_delivery').fetchone()[0]==0
 print(json.dumps({'status':'PASS','chain':'isolated_PG_claim_to_real_NativeService_Worker_SQLite_original_Pro_argv','body_target':1,'max_api_requests':8,'max_comments':0,'replies':True,'sdk_source_started':False,'delivery_rpc':False}))
