import sys,unittest,ast
from pathlib import Path
import pro_executor,mc_runner
class Capabilities(unittest.TestCase):
 def test_pro_descriptor(self):
  value=pro_executor.owner_task_capabilities()
  self.assertEqual(value['schema'],'crowd-owner-pro-capabilities-v1')
  self.assertEqual(value['default_new_owner_executor'],'pro')
  self.assertEqual({p['id'] for p in value['platforms']},set(mc_runner.PLATFORMS))
  for p in value['platforms']:
   self.assertEqual(p['adapter_state'],'adapted' if p['id'] in pro_executor.SUPPORTED else 'not_adapted')
  self.assertEqual(value['account_verified'],False)
 def test_normal_handler_is_local_only(self):
  from dashboard import Application
  app=Application.__new__(Application)
  # No lock, owner service, runner or cloud configured: this must only return code facts.
  result=app.tasks('capabilities',{})
  self.assertTrue(result['ok']);self.assertEqual(result['source_actions_started'],0)
  self.assertEqual(result['platforms'],pro_executor.owner_task_capabilities()['platforms'])
 def test_public_capabilities_preserve_legacy(self):
  from unittest.mock import patch
  with patch.object(mc_runner,'source_info',return_value={'commit':'offline'}):value=mc_runner.capabilities('/offline')
  self.assertEqual(len(value['platforms']),7)
  self.assertEqual(value['optional_pro_executor']['default_executor'],'mc')
  self.assertEqual(value['owner_pro_task_capabilities'],pro_executor.owner_task_capabilities())
 def test_history_default_unchanged(self):
  for p in mc_runner.PLATFORMS:
   self.assertEqual(pro_executor.selection({'platform':p,'mode':'search'},environ={}),{'backend':'mc','requested_backend':'mc'})
if __name__=='__main__':unittest.main()
