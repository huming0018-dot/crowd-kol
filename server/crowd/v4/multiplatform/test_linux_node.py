import io,json,tarfile,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import portable_node as P

def archive():
 b=io.BytesIO()
 with tarfile.open(fileobj=b,mode='w:gz')as t:
  for name,data in [('bin/node',b'fixture-node'),('LICENSE',b'fixture-license')]:
   entry=tarfile.TarInfo('node-'+P.VERSION+'-linux-arm64/'+name);entry.size=len(data);t.addfile(entry,io.BytesIO(data))
 return b.getvalue()
class Tests(unittest.TestCase):
 def test_linux_architecture_real_os_names(self):
  for machine,arch in [('aarch64','arm64'),('x86_64','x64')]:
   with patch.object(P.platform,'system',return_value='Linux'),patch.object(P.platform,'machine',return_value=machine):self.assertEqual(P.architecture(),arch)
 def test_linux_prepare_check_and_tamper(self):
  with tempfile.TemporaryDirectory()as temp:
   helper=Path(temp).resolve();helper.chmod(0o700);raw=archive()
   with patch.dict(P.LINUX_ARCHIVES,{'arm64':P.sha(raw)}):
    node=P.prepare(helper,arch='arm64',system='linux',fetch=lambda url:raw);self.assertIn('linux-arm64',str(node));self.assertEqual(P.check(helper,arch='arm64',system='linux'),node);node.write_bytes(b'changed')
    with self.assertRaises(ValueError):P.check(helper,arch='arm64',system='linux')
 def test_linux_unknown_attempt_not_retried(self):
  with tempfile.TemporaryDirectory()as temp:
   helper=Path(temp).resolve();helper.chmod(0o700)
   with self.assertRaises(OSError):P.prepare(helper,arch='arm64',system='linux',fetch=lambda _:(_ for _ in ()).throw(OSError('offline')))
   with self.assertRaisesRegex(ValueError,'node_attempt_unknown'):P.prepare(helper,arch='arm64',system='linux',fetch=lambda _:self.fail('repeat fetch'))
 def test_darwin_contract_byte_fields_unchanged(self):
  self.assertEqual(P.contract('arm64',system='darwin'),{'schema':'crowd-node-resource-v1','version':P.VERSION,'arch':'arm64','archive_sha256':'61130f394c1630d211dd50aecc4353d379480f36d3ac913cd85dbba1aed585c6'})
 def test_machine_node_revision_uses_linux_home_resource(self):
  with patch.object(P.platform,'system',return_value='Linux'),patch.object(P,'check',return_value=Path('/expected/node'))as check:
   self.assertEqual(P.from_runtime(Path('/node/node-revisions')/('a'*64)),Path('/expected/node'));self.assertEqual(check.call_args.args[0],Path.home()/'.local/share/CrowdV4Updater')
 def test_windows_not_silently_linux(self):
  with patch.object(P.platform,'system',return_value='Windows'):
   with self.assertRaisesRegex(ValueError,'node_architecture_unsupported'):P.architecture()
 def test_linux_resource_requires_exact_archive_and_prefix(self):
  with self.assertRaisesRegex(ValueError,'node_archive_changed'):P.resource(b'not pinned','arm64',system='linux')
if __name__=='__main__':unittest.main()
