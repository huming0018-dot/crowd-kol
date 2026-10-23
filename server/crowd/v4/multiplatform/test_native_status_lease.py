"""Five-key production status + strict lease; real Service/Worker/temp SQLite."""
import unittest,uuid
from test_native_login_recovery import LoginRecovery
from participant_pro_native import NativeService
from participant_native_rpc import ProtocolError
class ActualStatusLease(LoginRecovery):
 def rpc(self,method,p):
  if method=='pro_guard':
   try:uuid.UUID(p.get('p_lease'))
   except (ValueError,TypeError,AttributeError):raise ProtocolError('participant_protocol_invalid')
   if p['p_lease']!=self.m.lease:raise ProtocolError('participant_scope_changed')
  value=super().rpc(method,p)
  if method=='pro_status':value['task']={k:value['task'][k]for k in ['id','received','source_executor','status','target']}
  return value
 def test_real_status_shape_source_recovery_preserves_second_guard(self):
  s=NativeService(self.cfg,self.m,self.factory);s.start(self.msg());s.thread.join(3)
  self.assertEqual(s.snapshot()['state'],'complete');self.assertEqual(self.received,2);self.assertEqual(len(self.launches),1)
  self.assertEqual(self.launches[0]['request']['max_api_requests'],10)
  guard=[p for method,p in self.calls if method=='pro_guard'];self.assertGreaterEqual(len(guard),2)
  self.assertEqual(guard[0]['p_lease'],self.context['lease']);self.assertNotEqual(guard[1]['p_lease'],guard[0]['p_lease'])
  self.assertEqual(self.launches[0]['participant_context']['recovery']['expected_detail_count'],176)
 def test_denied_or_unknown_control_never_archives_or_launches(self):
  for outcome in ['denied','unknown']:
   other=ActualStatusLease();other.setUp()
   try:
    original=other.rpc
    def rpc(method,p):
     if method=='pro_guard':
      if outcome=='unknown':raise ProtocolError('participant_rpc_outcome_unknown')
      return {'allowed':False,'reason':'lease_lost','counts':{'detail':176}}
     return original(method,p)
    other.m.call=rpc;before=other.oldrow();s=NativeService(other.cfg,other.m,other.factory)
    with self.assertRaises(Exception):s.start(other.msg())
    self.assertEqual(other.oldrow(),before);self.assertEqual(other.launches,[])
   finally:other.tearDown()
 def test_authoritative_count_not_hardcoded(self):
  self.detail=181;s=NativeService(self.cfg,self.m,self.factory);s.start(self.msg());s.thread.join(3)
  self.assertEqual(self.launches[0]['participant_context']['recovery']['expected_detail_count'],181)
 def test_missing_invalid_foreign_saved_lease_preserves_old(self):
  for kind in ['missing','invalid','foreign']:
   with self.subTest(kind=kind):
    other=ActualStatusLease();other.setUp()
    try:
     if kind=='missing':other.context.pop('lease')
     else:other.context['lease']='not-a-uuid' if kind=='invalid' else str(uuid.uuid4())
     import json
     with other.box._db()as db:db.execute('update participant_runs set context=?where task=29',(json.dumps(other.context),))
     other.manifest['participant_pro']=other.context;other.write_run();before=other.oldrow();s=NativeService(other.cfg,other.m,other.factory)
     with self.assertRaises(Exception):s.start(other.msg())
     self.assertEqual(other.oldrow(),before);self.assertEqual(other.launches,[])
    finally:other.tearDown()
if __name__=='__main__':unittest.main()
