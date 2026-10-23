"""Real Application.cloud routing only; no Application init, network, DB or source."""
import importlib.util
import unittest
from pathlib import Path
D=Path(__file__).parent
s=importlib.util.spec_from_file_location('g08_dashboard',D/'dashboard.py')
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class Cloud:
    def __init__(self):self.calls=[]
    def call(self,a,p):
        self.calls.append((a,p));return {'schema':'crowd-unified-dispatch-v1','ready':True,'routes':[]}
class TestCancel(unittest.TestCase):
    def app(self):
        app=m.Application.__new__(m.Application);app.cloud_client=Cloud();return app
    def test_exact(self):
        a=self.app();p={'dispatch_id':'00000000-0000-4000-8000-000000000001'}
        self.assertTrue(a.cloud('unified_cancel',p)['available']);self.assertEqual(a.cloud_client.calls,[('unified_cancel',p)])
    def test_bad(self):
        for p in ({},{'dispatch_id':'bad'},{'dispatch_id':1},{'dispatch_id':'00000000-0000-4000-8000-000000000001','task':1}):
            a=self.app()
            with self.assertRaises(ValueError):a.cloud('unified_cancel',p)
            self.assertEqual(a.cloud_client.calls,[])
    def test_offline(self):
        a=self.app();a.cloud_client=None
        self.assertFalse(a.cloud('unified_cancel',{'dispatch_id':'00000000-0000-4000-8000-000000000001'})['available'])
if __name__=='__main__':unittest.main()
