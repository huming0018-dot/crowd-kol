import tempfile,unittest,json,uuid
from pathlib import Path
from participant_pro import ParticipantProWorker
from participant_pro_transport import ParticipantTransportError
U=lambda:str(uuid.uuid4())
class Poll(unittest.TestCase):
 def fixture(self,root,state):
  subject,install,sid,run=U(),U(),U(),U();binding={'profile':'/original','subject':subject,'installation_id':install,'generation':7};calls=[]
  class T:
   node='/node'
   def __init__(self):self.binding=dict(binding)
   def scope(self):calls.append('scope');raise ParticipantTransportError('participant_writer_busy')
   def __call__(self,*a):raise AssertionError('NO_RPC')
  def runner(a,p):calls.append(a);assert a=='status','NO_SOURCE_OR_IMPORT';return {'state':state}
  w=ParticipantProWorker(root,T(),runner,task_id=19,installation_id=install,subject=subject,session_id=sid,known_ids=[])
  with w.outbox._db() as db:db.execute('insert into participant_runs values(?,?,?,?)',(19,'running',run,json.dumps({'binding':binding})))
  return w,calls
 def test_running_child_busy_parent_local_status_only(self):
  with tempfile.TemporaryDirectory() as td:
   w,c=self.fixture(Path(td),'running');self.assertEqual(w.tick({})['state'],'running');self.assertEqual(c,['status'])
 def test_final_completed_requires_fresh_scope_before_import_or_delivery(self):
  with tempfile.TemporaryDirectory() as td:
   w,c=self.fixture(Path(td),'completed')
   with self.assertRaisesRegex(ParticipantTransportError,'participant_writer_busy'):w.tick({})
   self.assertEqual(c,['status','scope'])
 def test_diagnostic_fixed_code_and_phase_no_raw_exception(self):
  from participant_pro import transport_diagnostic
  for code in ('participant_writer_busy','participant_scope_changed'):
   self.assertEqual(transport_diagnostic(ParticipantTransportError(code),'scope'),{'state':'blocked','reason':code,'phase':'scope'})
  self.assertEqual(transport_diagnostic(ParticipantTransportError('secret URL token'),'raw secret'),{'state':'unknown','reason':'participant_rpc_outcome_unknown','phase':'initial'})
if __name__=='__main__':unittest.main()
