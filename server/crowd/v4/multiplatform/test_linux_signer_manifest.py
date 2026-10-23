import hashlib,io,unittest,zipfile
import linux_signer_manifest as G
class Tests(unittest.TestCase):
 def fixture(self):
  data={'Crypto/Cipher/_raw_aes.abi3.so':b'ELF-linux','Crypto/__init__.py':b'pure same'};bio=io.BytesIO()
  with zipfile.ZipFile(bio,'w')as z:
   for name,value in data.items():z.writestr(name,value)
  original=[{'distribution':'pycryptodome','file':name,'sha256':G.sha(b'MachO-mac')if name.endswith('.so')else G.sha(value)}for name,value in data.items()]+[{'distribution':'xhshow','file':'xhshow/__init__.py','sha256':'a'*64}]
  return original,bio.getvalue()
 def test_only_locked_wheel_compiled_members_change(self):
  original,raw=self.fixture();result,proof=G.generate(original,raw,G.sha(raw));self.assertEqual(result[1:],original[1:]);self.assertNotEqual(result[0]['sha256'],original[0]['sha256']);self.assertEqual(proof['compiled_members'][0]['file'],'Crypto/Cipher/_raw_aes.abi3.so')
 def test_installed_bytes_not_input_and_wrong_archive_rejected(self):
  original,raw=self.fixture()
  with self.assertRaisesRegex(ValueError,'wheel_hash_changed'):G.generate(original,raw,'0'*64)
 def test_noncompiled_drift_is_rejected_not_resigned(self):
  original,raw=self.fixture();original[1]['sha256']='0'*64
  with self.assertRaisesRegex(ValueError,'noncompiled_dependency_changed'):G.generate(original,raw,G.sha(raw))
if __name__=='__main__':unittest.main()
