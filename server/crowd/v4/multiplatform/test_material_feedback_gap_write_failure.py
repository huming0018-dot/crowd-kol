import unittest
from unittest.mock import patch
import test_material_feedback_gap_routes as routes
import material_feedback as product
class WriteFailure(unittest.TestCase):
 def test_post_intent_write_failure_remains_unknown_then_readonly_reconciles(self):
  case=routes.sdk.Gap();case.setUp()
  try:
   p=case.args()
   with patch.object(product,'write',side_effect=OSError('isolated final journal write failure')):r=case.submit(p)
   journal=product.read(case.service._gap_path(case.fid))
   self.assertEqual(r['state'],'outcome_unknown','post-intent journal write failure must remain UNKNOWN per contract')
   self.assertEqual(journal['state'],'attempted_no_retry')
   with patch.object(product.KnowledgeStore,'gap',side_effect=AssertionError('no SDK replay')):self.assertEqual(case.status()['state'],'pending_gap')
  finally:case.doCleanups()
if __name__=='__main__':unittest.main()
