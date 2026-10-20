"""Real result/dispatch names and SQLite sidecars never certify zero source."""
import hashlib,json,sqlite3,unittest
from test_pro_media_preflight_consumer import Tests as Fixture
from pro_startup_import import failed_before_source,REASON
class Artifacts(Fixture):
 def test_future_real_artifacts_deny_zero(self):
  for name in ('hybrid-media-result.json','hybrid-media-dispatch.json','mc-source-steps.sqlite3-wal','mc-source-steps.sqlite3-shm'):
   with self.subTest(name=name):
    p=self.run/name;p.write_text('{}')
    try:self.invalid()
    finally:p.unlink()
 def signer86(self):
  (self.run/'pro-media-preflight.json').unlink()
  self.status.update(exit_code=86,api_attempts=0,failure_reason=REASON)
  self.put('status.json',self.status)
  self.put('phase.json',{'failure_reason':REASON,'phase':'failed','api_attempts':0})
  canon=json.dumps(self.manifest['request'],sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)
  self.put('request-budget.json',{'schema':'crowd-shared-request-budget-v1','run_id':self.rid,'request_hash':hashlib.sha256(canon.encode()).hexdigest(),'limit':30,'used':0,'stages':[]})
  with sqlite3.connect(self.run/'mc-source-steps.sqlite3') as c:
   c.execute('CREATE TABLE binding(run TEXT,platform TEXT)');c.execute('INSERT INTO binding VALUES (?,?)',(self.rid,'xhs'));c.execute('CREATE TABLE events(x TEXT)')
 def test_original_signer86_positive_contract_preserved(self):
  self.signer86();v=failed_before_source(self.run,self.manifest,self.status)
  self.assertEqual(v['failure_reason'],REASON);self.assertEqual(v['records'],[])
 def test_original_signer86_same_real_artifacts_deny_zero(self):
  self.signer86()
  for name in ('hybrid-media-result.json','hybrid-media-dispatch.json','mc-source-steps.sqlite3-wal','mc-source-steps.sqlite3-shm'):
   with self.subTest(name=name):
    p=self.run/name;p.write_text('{}')
    try:
     with self.assertRaises(ValueError):failed_before_source(self.run,self.manifest,self.status)
    finally:p.unlink()
if __name__=='__main__':unittest.main(defaultTest=['Artifacts.test_future_real_artifacts_deny_zero','Artifacts.test_original_signer86_positive_contract_preserved','Artifacts.test_original_signer86_same_real_artifacts_deny_zero'])
