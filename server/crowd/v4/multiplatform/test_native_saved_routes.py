"""Offline actual Application.cloud method routing; no server or SDK needed."""
import ast,sys,types,unittest
from pathlib import Path
from unittest.mock import patch
class Routes(unittest.TestCase):
 def setUp(self):
  tree=ast.parse(Path(__file__).with_name('dashboard.py').read_text());cls=next(x for x in tree.body if isinstance(x,ast.ClassDef)and x.name=='Application');method=next(x for x in cls.body if isinstance(x,ast.FunctionDef)and x.name=='cloud')
  # Execute the actual method, retaining every original branch. Only the first new branch runs.
  ns={};exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])),'actual-cloud-method','exec'),ns);self.call=ns['cloud'];self.app=types.SimpleNamespace(cloud_client=types.SimpleNamespace(role='owner'))
 def test_put_get_delegate_exact_payload(self):
  module=types.SimpleNamespace(dispatch=lambda app,action,payload:{'action':action,'key':payload['idempotency_key']})
  with patch.dict(sys.modules,{'owner_native_saved':module}):
   for action in ('native_saved_put','native_saved_get'):
    self.assertEqual(self.call(self.app,action,{'idempotency_key':'fixture'}),{'ok':True,'storage_scope':'cloud','action':action,'key':'fixture'})
 def test_nonowner_cannot_delegate(self):
  for client in (None,types.SimpleNamespace(role='worker')):
   self.app.cloud_client=client
   with self.assertRaisesRegex(ValueError,'owner_authorization_required'):self.call(self.app,'native_saved_put',{'idempotency_key':'fixture'})
 def test_invalid_payload_keeps_original_guard(self):
  with self.assertRaisesRegex(ValueError,'invalid_cloud_request'):self.call(self.app,'native_saved_get',[])
if __name__=='__main__':unittest.main()
