import sys,json,tempfile,threading,time,unittest
from pathlib import Path
HERE=Path(__file__).resolve().parent
MP=HERE
sys.path[:0]=[str(MP)]
from test_participant_pro_native import Mux,U
from participant_pro_native import NativeService
from participant_native_rpc import frame
from pro_executor import PINNED_COMMIT
class Login(unittest.TestCase):
 def test_source_failure_then_status_only_preserves_platform_reason(self):
  with tempfile.TemporaryDirectory() as t:
   mux=Mux();calls=[];run=U();config={'root':t,'mc_root':t,'session_id':U(),'purpose':'noncommercial_research','max_api_requests':14}
   def factory(*a,**kw):
    def runner(action,p):
     calls.append(action)
     if action=='start':return {'run_id':run}
     if action=='status':return {'state':'login_required','reason':'login_required','phase':'login_required','account':{'state':'logged_out'}}
     if action=='import':return {'records':[],'manifest':{'source':{'commit':PINNED_COMMIT}}}
     self.fail(action)
    return runner
   service=NativeService(config,mux,factory);msg=frame('pro_start',mux.session,7,subject=mux.subject,installation_id=mux.install,task_id=201,intent=U());service.handle(msg);service.thread.join(2);self.assertFalse(service.thread.is_alive());v=mux.frames[-1];self.assertEqual(v['state'],'source_failed');self.assertEqual(v['error'],'login_required');self.assertEqual(v['received'],2);self.assertEqual(v['pending'],0);self.assertNotIn('pro_finish',[m for m,p in mux.calls]);self.assertNotIn('pro_submit',[m for m,p in mux.calls]);self.assertEqual(calls.count('start'),1)
   before=list(calls);service.worker.tick(None);self.assertEqual(calls,before)
   other=NativeService(config,mux,factory);other.restore_status(run);other.emit(msg);self.assertEqual(mux.frames[-1]['error'],'login_required');self.assertEqual(calls,before)
 def test_only_exact_platform_reason_is_exposed(self):
  from participant_pro import source_failure_error
  self.assertEqual(source_failure_error({'state':'login_required','reason':'login_required'}),'login_required')
  for v in ({'state':'failed','reason':'private https://secret'},{'state':'interrupted_unknown','reason':'login_required'},{'state':'completed','reason':'login_required'},{'state':'login_required','reason':'backend_login_required'},{},None):self.assertIsNone(source_failure_error(v))
if __name__=='__main__':unittest.main()
