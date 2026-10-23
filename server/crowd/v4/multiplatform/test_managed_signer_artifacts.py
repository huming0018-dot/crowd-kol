"""A published wrapper must satisfy its own production launch gate."""
import hashlib, unittest
import managed_pro_signer as signer
class InstalledArtifacts(unittest.TestCase):
 def test_production_wrapper_and_source_manifest_are_paired(self):
  self.assertEqual(hashlib.sha256(signer.SERVER.read_bytes()).hexdigest(), signer.SERVER_SHA)
  self.assertEqual(hashlib.sha256(signer.SERVER.with_name('SIGN-SOURCE-SHA.json').read_bytes()).hexdigest(), signer.SOURCE_MANIFEST_SHA)
if __name__=='__main__':unittest.main()
