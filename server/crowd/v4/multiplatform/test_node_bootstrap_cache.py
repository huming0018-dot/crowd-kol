import importlib.util,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('installer',Path(__file__).with_name('install-linux.py'));M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)
import portable_node as N
class Reached(Exception):pass
class Tests(unittest.TestCase):
 def test_normal_cli_cache_must_reach_original_node_resource_loader(self):
  import pro_executor,mc_runner,pro_signer_server
  with tempfile.TemporaryDirectory()as d:
   p=Path(d);argv=['install-linux.py','--runtime',str(p/'runtime'),'--runtime-sha256','a'*64,'--root',str(p/'new'),'--sdk-root',str(p/'sdk'),'--signer-root',str(p/'signer'),'--uv',str(p/'uv'),'--bootstrap-cache',str(p/'cache')]
   def original_prepare(helper,**kwargs):
    self.assertIn('fetch',kwargs,'explicit bootstrap cache was ignored; original network fetch would run')
    raise Reached()
   with patch.object(sys,'argv',argv),patch.object(M.sys,'platform','linux'),patch.object(M,'runtime'),patch.object(Path,'home',return_value=p),patch.object(mc_runner,'source_info',return_value={'commit':pro_executor.PINNED_COMMIT,'dirty':False}),patch.object(pro_signer_server,'verify_source'),patch.object(N,'prepare',side_effect=original_prepare):
    with self.assertRaises(Reached):M.main()
 def test_cached_archive_delegates_unchanged_original_resource_validation(self):
  with tempfile.TemporaryDirectory()as d:
   p=Path(d);cache=p/'cache';cache.mkdir();archive=cache/('node-'+N.VERSION+'-linux-arm64.tar.gz');archive.write_bytes(b'official-archive-fixture')
   seen=[]
   def original_prepare(helper,**kwargs):
    raw=kwargs['fetch']('https://nodejs.org/download/release/'+N.VERSION+'/'+archive.name)
    seen.append(raw);return p/'node'
   with patch.object(N,'architecture',return_value='arm64'),patch.object(N,'prepare',side_effect=original_prepare):self.assertEqual(M.prepare_node(p/'helper',cache),p/'node')
   self.assertEqual(seen,[b'official-archive-fixture'])
 def test_wrong_url_missing_symlink_or_oversize_refused_before_resource(self):
  with tempfile.TemporaryDirectory()as d:
   p=Path(d);archive=p/('node-'+N.VERSION+'-linux-arm64.tar.gz')
   def call(url):
    with patch.object(N,'architecture',return_value='arm64'),patch.object(N,'prepare',side_effect=lambda helper,**kw:kw['fetch'](url)):
     return M.prepare_node(p/'helper',p)
   url='https://nodejs.org/download/release/'+N.VERSION+'/'+archive.name
   with self.assertRaisesRegex(ValueError,'node_archive_cache_missing'):call(url)
   archive.write_bytes(b'ok')
   with self.assertRaisesRegex(ValueError,'node_archive_cache_url_changed'):call('https://elsewhere.invalid/'+archive.name)
   archive.unlink();other=p/'other';other.write_bytes(b'ok');archive.symlink_to(other)
   with self.assertRaisesRegex(ValueError,'node_archive_cache_unsafe'):call(url)
   archive.unlink();archive.write_bytes(b'12345')
   with patch.object(N,'MAX_ARCHIVE',4),self.assertRaisesRegex(ValueError,'node_archive_too_large'):call(url)
 def test_no_cache_preserves_original_prepare_network_behavior(self):
  with patch.object(N,'prepare',return_value='original')as original:
   self.assertEqual(M.prepare_node(Path('/synthetic/helper'),None),'original')
   original.assert_called_once_with(Path('/synthetic/helper'))
if __name__=='__main__':unittest.main()
