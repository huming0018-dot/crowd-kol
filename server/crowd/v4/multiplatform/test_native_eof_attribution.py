import json,tempfile,threading,unittest,uuid
from pathlib import Path
from unittest.mock import patch
import mc_runner
from participant_pro_native import NativeService
from participant_pro import ParticipantProWorker
from participant_native_rpc import NativeTransport
from test_participant_pro_native import Mux
class EOFAttribution(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.m=Mux();self.rid=str(uuid.uuid4());self.run=self.root/'runs'/self.rid;self.run.mkdir(parents=True)
  self.cfg={'root':str(self.root),'mc_root':str(self.root),'session_id':str(uuid.uuid4()),'purpose':'noncommercial_research','max_api_requests':14}
  self.s=NativeService(self.cfg,self.m,lambda *a,**kw:self.fail('no source'))
  rpc=NativeTransport(self.m,self.m.subject,self.m.install,29)
  self.s.worker=ParticipantProWorker(self.root,rpc,lambda *a:self.fail('no source'),task_id=29,installation_id=self.m.install,subject=self.m.subject,session_id=self.cfg['session_id'],known_ids=[])
  with self.s.worker.outbox._db()as db:db.execute('insert into participant_runs values(?,?,?,?)',(29,'running',self.rid,json.dumps({'binding':rpc.binding,'target':2,'limit':2})))
 def tearDown(self):self.tmp.cleanup()
 def row(self):
  with self.s.worker.outbox._db()as db:return db.execute('select * from participant_runs').fetchall()
 def test_eof_uses_native_reason_real_stop_marker_and_stays_unknown(self):
  before=self.row()
  with patch('mc_runner.status',return_value={'state':'running'}):self.s.stop_owned(explicit=False)
  v=json.loads((self.run/'stop.json').read_text());self.assertEqual(v['origin'],'native_host');self.assertEqual(v['reason'],'port_disconnected')
  self.assertEqual(self.s.last['state'],'unknown');self.assertIsNone(self.s.explicit_stop_run);self.assertEqual(self.row(),before);self.assertEqual(self.m.calls,[])
 def test_explicit_stop_stays_user_and_first_marker_immutable(self):
  with patch('mc_runner.status',return_value={'state':'running'}):
   self.s.stop_owned(explicit=True);before=(self.run/'stop.json').read_bytes();self.s.stop_owned(explicit=False)
  self.assertEqual((self.run/'stop.json').read_bytes(),before);v=json.loads(before);self.assertEqual((v['origin'],v['reason']),('user','user_stop'));self.assertEqual(self.s.explicit_stop_run,self.rid)
 def test_native_reason_does_not_set_explicit_evidence_even_if_stopped(self):
  with patch('mc_runner.stop',return_value={'state':'stopped','stop_context':{'origin':'native_host','reason':'port_disconnected'}}):self.s.stop_owned(explicit=False)
  self.assertEqual(self.s.last['state'],'stopped');self.assertIsNone(self.s.explicit_stop_run)
 def test_pending_rpc_remains_unknown(self):
  self.m.pending['pending']=object()
  with patch('mc_runner.stop',return_value={'state':'stopped'}):self.s.stop_owned(explicit=False)
  self.assertEqual(self.s.last['state'],'unknown');self.assertTrue(self.m.pending)
 def test_enum_exact_no_extra_authority(self):
  self.assertEqual(mc_runner.stop_metadata({'origin':'native_host','reason':'port_disconnected'}),{'origin':'native_host','reason':'port_disconnected'})
  for bad in [{'origin':'native_host','reason':'user_stop'},{'origin':'user','reason':'port_disconnected'},{'origin':'native_host','reason':'other'},{'origin':'native_host','reason':'port_disconnected','lease_epoch':1}]:
   with self.subTest(bad=bad),self.assertRaises(Exception):mc_runner.stop_metadata(bad)
if __name__=='__main__':unittest.main()
