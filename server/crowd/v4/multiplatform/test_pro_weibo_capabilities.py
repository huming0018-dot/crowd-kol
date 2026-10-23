"""Capability metadata must describe the WB gate without changing collection."""
import os
import unittest
from unittest.mock import patch
import mc_runner as m

class WeiboCapabilitiesTest(unittest.TestCase):
    def capability(self,env):
        with patch.dict(os.environ,env,clear=True),patch.object(m,'source_info',return_value={'commit':'synthetic'}):
            return m.capabilities('/synthetic')['optional_pro_executor']
    def test_default_mc_and_original_platforms_preserved(self):
        value=self.capability({})
        self.assertEqual(value['default_executor'],'mc')
        self.assertEqual(value['operation_platforms'],['xhs','dy','bili'])
        self.assertEqual(value['required_native_protocol_platforms'],['xhs','dy','bili'])
        gate=value['gated_platforms'][0]
        self.assertEqual(gate['id'],'wb');self.assertFalse(gate['enabled'])
        self.assertEqual(gate['enable_env'],'CROWD_PRO_WEIBO_ENABLED=1')
        self.assertIn('partial',gate['replies']);self.assertFalse(gate['live_verified'])
    def test_only_exact_explicit_flag_enables_wb_metadata(self):
        for value in ('','0','true','yes'):
            self.assertNotIn('wb',self.capability({'CROWD_PRO_WEIBO_ENABLED':value})['operation_platforms'])
        value=self.capability({'CROWD_PRO_WEIBO_ENABLED':'1'})
        self.assertEqual(value['operation_platforms'],['xhs','dy','bili','wb'])
        self.assertTrue(value['gated_platforms'][0]['enabled'])
        self.assertEqual(value['selection_env'],'CROWD_EXECUTOR=pro')
        self.assertEqual(value['gated_platforms'][0]['modes'],['search','detail','creator'])

if __name__=='__main__':unittest.main()
