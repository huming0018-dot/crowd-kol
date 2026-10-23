"""Import preflight discriminator preserves the prior non-dict result boundary."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from dashboard import Application
class Tests(unittest.TestCase):
 def test_non_dict_import_result_ignored_without_store(self):
  for result in ([],None,'not-a-record-object',0):
   with self.subTest(result=result):
    response={'ok':True,'result':result}
    app=SimpleNamespace(mc_root='unused',_registered_run_root=lambda _: 'unused',_call_runner=lambda *_:response)
    with patch('results_store.ResultsStore',side_effect=AssertionError('NO_STORE')):
     self.assertIs(Application.run(app,'import',{'run_id':'original'}),response)
 def test_verified_preflight_dict_preserves_empty_library_guard(self):
  response={'ok':True,'result':{'media_preflight_verified':True,'records':[]}}
  app=SimpleNamespace(mc_root='unused',_registered_run_root=lambda _: 'unused',_call_runner=lambda *_:response)
  with patch('results_store.ResultsStore',side_effect=AssertionError('NO_STORE')):
   self.assertIs(Application.run(app,'import',{'run_id':'original'}),response)
if __name__=='__main__':unittest.main()
