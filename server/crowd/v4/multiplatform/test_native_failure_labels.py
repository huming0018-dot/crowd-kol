from pathlib import Path
import sys,tempfile,unittest
H=Path(__file__).resolve().parent
F=Path('/Users/hubowen/Desktop/桌面 - 胡博文的MacBook Pro/pushpull/crowd-kol/server/crowd/v4/multiplatform')
sys.path[:0]=[str(H),str(F)]
import test_discovery_unavailable as fixtures
class NativeFailures(unittest.TestCase):
 def supervise(self,reason,code=86,stop=False):
  with tempfile.TemporaryDirectory() as folder:
   return fixtures.UnavailableTests().supervisor(folder,{'failure_reason':reason,'account_state':'authenticated'},mode='detail',code=code,stop=stop)
 def test_real_supervisor_preserves_fixed_native_diagnostics(self):
  for reason in ('pro_cookiebridge_unavailable','pro_native_credentials_unavailable','pro_bili_wbi_unavailable'):
   with self.subTest(reason=reason):
    result=self.supervise(reason);self.assertEqual((result['state'],result['reason'],result['exit_code']),('failed',reason,86));self.assertEqual(result['account_state'],'authenticated')
 def test_unknown_diagnostic_not_adopted_as_public_reason(self):
  for reason in ('Cookie=PRIVATE_SECRET',None,{'bad':'shape'},True):
   with self.subTest(reason=reason):self.assertEqual(self.supervise(reason)['reason'],'pro_login_verification_failed')
 def test_real_logout_and_account_change_still_require_login(self):
  for code,reason in ((77,'login_required'),(78,'account_changed')):
   result=self.supervise('pro_bili_wbi_unavailable',code);self.assertEqual((result['state'],result['reason']),('login_required',reason))
 def test_owner_stop_dominates_and_content_denial_remains_separate(self):
  result=self.supervise('pro_bili_wbi_unavailable',stop=True);self.assertEqual((result['state'],result['reason']),('stopped','user_stop'))
  result=self.supervise('pro_content_access_denied',87);self.assertEqual((result['state'],result['reason']),('failed','pro_content_access_denied'))
if __name__=='__main__':unittest.main()
