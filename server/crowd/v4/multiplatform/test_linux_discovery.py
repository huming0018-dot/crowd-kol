import importlib.util,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
import first_bind as F
spec=importlib.util.spec_from_file_location('linux_install',Path(__file__).with_name('install-linux.py'));L=importlib.util.module_from_spec(spec);spec.loader.exec_module(L)
class Tests(unittest.TestCase):
 def test_unique_licensed_checkout_discovered_without_clone(self):
  with tempfile.TemporaryDirectory()as d:
   home=Path(d).resolve();project=home/'MediaCrawlerPro-Python';project.mkdir();(project/'pyproject.toml').write_text('synthetic')
   self.assertEqual(L.local_project(None,project.name,[home]),project)
 def test_ambiguous_local_checkouts_require_explicit_path(self):
  with tempfile.TemporaryDirectory()as d:
   homes=[Path(d).resolve()/x for x in('a','b')]
   for h in homes:(h/'MediaCrawlerPro-Python').mkdir(parents=True);(h/'MediaCrawlerPro-Python/pyproject.toml').write_text('synthetic')
   with self.assertRaisesRegex(ValueError,'ambiguous'):L.local_project(None,'MediaCrawlerPro-Python',homes)
   self.assertEqual(L.local_project(homes[0]/'MediaCrawlerPro-Python','MediaCrawlerPro-Python',homes),homes[0]/'MediaCrawlerPro-Python')
 def test_original_bridge_server_layout_discovered_without_pyproject(self):
  with tempfile.TemporaryDirectory()as d:
   home=Path(d).resolve();project=home/'MediaCrawlerPro-CookieBridge';(project/'server').mkdir(parents=True);(project/'server/app.py').write_text('synthetic original layout only')
   self.assertFalse((project/'pyproject.toml').exists());self.assertEqual(L.local_project(None,project.name,[home]),project);self.assertFalse((project/'pyproject.toml').exists())
 def test_bridge_pyproject_alone_is_not_original_server(self):
  with tempfile.TemporaryDirectory()as d:
   home=Path(d).resolve();project=home/'MediaCrawlerPro-CookieBridge';project.mkdir();(project/'pyproject.toml').write_text('not the original Bridge marker')
   with self.assertRaisesRegex(ValueError,'missing_or_ambiguous'):L.local_project(None,project.name,[home])
 def test_ambiguous_bridge_server_layout_requires_explicit_path(self):
  with tempfile.TemporaryDirectory()as d:
   homes=[Path(d).resolve()/n for n in ('a','b')]
   for home in homes:
    project=home/'MediaCrawlerPro-CookieBridge';(project/'server').mkdir(parents=True);(project/'server/app.py').write_text('synthetic original layout only')
   with self.assertRaisesRegex(ValueError,'ambiguous'):L.local_project(None,'MediaCrawlerPro-CookieBridge',homes)
   chosen=homes[0]/'MediaCrawlerPro-CookieBridge';self.assertEqual(L.local_project(chosen,chosen.name,homes),chosen)
 def test_server_app_does_not_replace_python_signer_marker(self):
  with tempfile.TemporaryDirectory()as d:
   home=Path(d).resolve()
   for name in ('MediaCrawlerPro-Python','MediaCrawlerPro-SignSrv'):
    project=home/name;(project/'server').mkdir(parents=True);(project/'server/app.py').write_text('synthetic')
    with self.assertRaisesRegex(ValueError,'missing_or_ambiguous'):L.local_project(None,name,[home])
 def accounts(self,rows):
  response=MagicMock();response.status=200;response.read.return_value=json.dumps({'biz_code':0,'isok':True,'data':{'accounts':rows}}).encode();response.__enter__.return_value=response
  opener=MagicMock();opener.open.return_value=response;return patch.object(F.urllib.request,'build_opener',return_value=opener)
 def row(self,client,connected=True,cookies=True):return{'client_id':client,'connected':connected,'platforms':{'xhs':{'has_cookies':cookies}}}
 def test_unique_connected_xhs_client_only(self):
  with self.accounts([self.row('one'),self.row('offline',False),self.row('no_login',cookies=False)]):self.assertEqual(F.choose_client(),'one')
 def test_multiple_clients_never_pick_first(self):
  with self.accounts([self.row('one'),self.row('two')]):
   with self.assertRaisesRegex(ValueError,'ambiguous'):F.choose_client()
 def test_duplicate_clients_and_wrong_typed_metadata_refused(self):
  for rows in([self.row('one'),self.row('one')],[{'client_id':'one','platforms':[]}],[self.row('one',cookies='true')]):
   with self.accounts(rows):
    with self.assertRaises(ValueError):F.choose_client()
 def test_metadata_does_not_expose_cookie_values(self):
  with self.accounts([self.row('one')]):self.assertEqual(F.choose_client(),'one')
if __name__=='__main__':unittest.main()
