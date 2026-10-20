"""Exact request activation tests; no SDK/network/account access."""
import copy,unittest
import pro_executor as p
BASE={'source_executor':'pro','platform':'tieba','mode':'detail','targets':['10451142633'],'max_items':1,'comments':True,'replies':True,'max_comments':0,'media':True,'wordcloud':False,'platform_options':{}}
class Scope(unittest.TestCase):
 def test_exact_scope(self):self.assertIsNone(p.explicit_unsupported(BASE))
 def test_original_native_root_limit_semantics(self):
  for maximum in [0,1,20,350]:
   r={**BASE,'max_comments':maximum};self.assertIsNone(p.explicit_unsupported(r))
 def test_implicit_retains_original_route(self):
  r=copy.deepcopy(BASE);r.pop('source_executor');self.assertEqual(p.selection(r,{'CROWD_EXECUTOR':'pro'})['fallback_reason'],'pro_operation_platform_not_adapted')
 def test_other_modes_rejected(self):
  for mode in ['search','creator','homefeed']:
   self.assertIsNotNone(p.explicit_unsupported({**BASE,'mode':mode}))
 def test_scope_not_broadened(self):
  for fields in [{'max_items':2},{'max_items':True},{'targets':[]},{'targets':['1','2']},{'platform_options':{'x':1}},{'wordcloud':True}]:
   self.assertIsNotNone(p.explicit_unsupported({**BASE,**fields}))
 def test_ks_remains_not_locally_adapted(self):self.assertEqual(p.explicit_unsupported({**BASE,'platform':'ks'}),'pro_operation_platform_not_adapted')
 def test_legacy_platforms_unchanged(self):
  for platform in ['xhs','dy','bili','wb']:
   self.assertIsNone(p.explicit_unsupported({**BASE,'platform':platform,'media':False,'max_comments':20}))
 def test_capability_exact_detail_only(self):
  row=next(x for x in p.owner_task_capabilities()['platforms']if x['id']=='tieba')
  self.assertEqual(row['adapter_state'],'adapted');self.assertEqual([x['id']for x in row['modes']if x['adapted']],['detail'])
 def test_owner_plan_preserves_requested_scope(self):
  from owner_tasks import plan
  value=plan({'idempotency_key':'g46-tieba-local-test','platforms':['tieba'],'mode':'detail','targets_by_platform':{'tieba':['10451142633']},'desired_items':1,'max_api_requests':30,'purpose':'noncommercial_research','source_executor':'pro','comments':True,'replies':True,'max_comments':0,'media':True})
  child=value['children'][0];self.assertEqual(child['state'],'queued');r=child['request'];self.assertEqual({k:r[k]for k in BASE},BASE);self.assertEqual(r['max_api_requests'],30)
 def test_explicit_selection_no_fallback(self):
  r=p.selection(BASE,{},installation={'root':'/tmp/licensed-sdk','python':'/tmp/pro-python'});self.assertEqual(r['backend'],'pro');self.assertNotIn('fallback_reason',r)
if __name__=='__main__':unittest.main()
