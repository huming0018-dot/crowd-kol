"""Actual Edge plan and original Owner Python validators, no source or installation."""
import copy,json,subprocess,unittest
from pathlib import Path
import mc_runner,pro_executor
G=Path(__file__).parent
class OwnerFallback(unittest.TestCase):
 def test_original_valid_and_new_native_only_boundaries(self):
  js="""import{unifiedPlan}from '../supabase/functions/crowd-machine/unified_dispatch.mjs';const r={idempotency_key:'fallback-native-bounds',platforms:['xhs'],mode:'search',targets:['synthetic'],desired_items:20,max_api_requests:14,comments:true,replies:true,purpose:'noncommercial_research',source_executor:'pro'};const a=[];for(const max_comments of[20,0,350]){const p=await unifiedPlan({...r,max_comments});a.push({max_comments,request:p.proposal.children[0].request,fallback:!!p.machine_fallback});}console.log(JSON.stringify(a));"""
  r=subprocess.run(['node','--input-type=module','-e',js],cwd=G,text=True,capture_output=True,timeout=10);self.assertEqual(r.returncode,0,r.stderr);rows=json.loads(r.stdout)
  self.assertTrue(rows[0]['fallback']);valid=mc_runner.validate(copy.deepcopy(rows[0]['request']));self.assertEqual(valid['max_comments'],20)
  selected=pro_executor.selection(valid,{},installation={'root':'/isolated/not-used','python':'/isolated/not-used'});self.assertEqual(selected['backend'],'pro')
  for row in rows[1:]:
   self.assertFalse(row['fallback'])
   with self.assertRaisesRegex(mc_runner.BridgeError,'pro_zero_comments_means_unlimited' if row['max_comments']==0 else 'invalid_max_comments'):mc_runner.validate(copy.deepcopy(row['request']))
  self.assertEqual(pro_executor.explicit_unsupported(rows[1]['request']),'pro_zero_comments_means_unlimited')
  # Only authoritative participant-native options use the already-existing distinct validation path.
  for row in rows[1:]:
   native={k:row['request'][k]for k in ('comments','replies','max_comments')};v=mc_runner.validate(copy.deepcopy(row['request']),native_comments=native);self.assertEqual(v['max_comments'],row['max_comments'])
if __name__=='__main__':unittest.main()
