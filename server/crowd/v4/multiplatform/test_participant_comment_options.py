"""Real NativeService/Worker and temporary SQLite; transport/source are controlled, no HTTP."""
import copy,json,tempfile,threading,unittest,uuid
from pathlib import Path
from participant_pro_native import NativeService
from participant_native_rpc import frame
from participant_pro import ParticipantOutbox
from test_participant_pro_native import Mux
from pro_executor import argv_for
U=lambda:str(uuid.uuid4())
class Options(unittest.TestCase):
 def scenario(self,opts=None,native=None,authority_extra=None):
  tmp=tempfile.TemporaryDirectory();root=Path(tmp.name);m=Mux();m.received=0;calls=[];launches=[];d=U();requested=copy.deepcopy(opts)
  def rpc(method,p):
   calls.append(method)
   if method=='scope':return {'subject':m.subject,'installation_id':m.install,'generation':7}
   if method=='pro_claim':
    claim={'source_executor':'mediacrawler_pro','reward_eligible':False,'known_note_ids':[],'task':{'id':201,'received':0,'target':1,'lease_token':m.lease,'query':'原关键词','anchor_terms':['品牌'],'comments_capture':opts is not None,'known_note_ids':[]},'acceptance_supplement':{'schema':'crowd-acceptance-batch-v1','id':d,'task_id':201,'installation_id':m.install,'baseline_received':0,'extra_limit':1,'remaining':1,'target':1}}
    if requested is not None:claim['pro_comment_options']={'schema':'crowd-participant-pro-comment-options-v1','task_id':201,'dispatch_id':d,'request_hash':'a'*64,'max_api_requests':8,**requested,**(authority_extra or {})}
    return claim
   raise AssertionError(method)
  m.call=rpc
  def factory(*a,**kw):
   def run(action,p):
    if action=='comment_options':return native or {'comments':True,'replies':False,'max_comments':0}
    if action=='start':launches.append(p);return {'run_id':U()}
    if action=='status':return {'state':'running'}
    raise AssertionError(action)
   return run
  cfg={'root':str(root),'mc_root':str(root),'session_id':U(),'purpose':'noncommercial_research','max_api_requests':14};s=NativeService(cfg,m,factory)
  msg=frame('pro_start',m.session,7,subject=m.subject,installation_id=m.install,task_id=201,intent=U());s.handle(msg);s.thread.join(.05);m.stopped.set();s.thread.join(1)
  return tmp,s,launches,calls,root
 def test_task_overrides_original_native_default_without_editing_config(self):
  for opt in [{'comments':True,'replies':True,'max_comments':150},{'comments':True,'replies':False,'max_comments':0},{'comments':True,'replies':True,'max_comments':350}]:
   t,s,r,c,root=self.scenario(opt)
   try:
    self.assertEqual(len(r),1,s.last);p=r[0];self.assertEqual({k:p['request'][k]for k in opt},opt);self.assertEqual(p['participant_context']['comment_options'],opt);self.assertEqual(p['participant_context']['task_comment_options']['request_hash'],'a'*64);self.assertEqual(p['request']['max_api_requests'],8);self.assertEqual(p['request']['max_items'],1)
    args=argv_for(p['request']);self.assertEqual(args[args.index('--max_comments_count')+1],str(opt['max_comments']));self.assertIn('--enable_sub_comments'if opt['replies']else'--no-enable_sub_comments',args)
    with ParticipantOutbox(root,lambda*a:None)._db()as db:self.assertEqual(db.execute('select count(*)from participant_delivery').fetchone()[0],0)
   finally:t.cleanup()
 def test_no_options_old_false_preserved(self):
  t,s,r,c,root=self.scenario()
  try:self.assertEqual(len(r),1);self.assertFalse(r[0]['request']['comments']);self.assertNotIn('task_comment_options',r[0]['participant_context'])
  finally:t.cleanup()
 def test_task_budget_and_scope_tamper_never_launch(self):
  for extra in [{'max_api_requests':15},{'max_api_requests':0},{'max_api_requests':True},{'task_id':202},{'dispatch_id':'not-uuid'},{'request_hash':'bad'},{'unexpected':'field'}]:
   t,s,r,c,root=self.scenario({'comments':True,'replies':True,'max_comments':150},authority_extra=extra)
   try:self.assertEqual(r,[]);self.assertNotEqual(s.snapshot()['state'],'running')
   finally:t.cleanup()
 def test_malformed_authoritative_options_never_launch(self):
  for opts in [{'comments':True,'replies':True,'max_comments':-1},{'comments':True,'replies':True,'max_comments':True},{'comments':False,'replies':True,'max_comments':0}]:
   t,s,r,c,root=self.scenario(opts)
   try:self.assertEqual(r,[]);self.assertNotEqual(s.snapshot()['state'],'running')
   finally:t.cleanup()
if __name__=='__main__':unittest.main()
