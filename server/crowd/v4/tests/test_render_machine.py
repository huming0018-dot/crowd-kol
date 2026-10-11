import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('render_machine', Path(__file__).parents[1] / 'render_machine.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RenderTests(unittest.TestCase):
    def test_existing_principal_is_rendered_without_disclosing_any_key(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'private.json'
            config = {'owner_key': 'a'*64, 'worker_key': 'b'*64,
                      'project_key': 'sb_publishable_private_routing_value',
                      'endpoint': 'https://bdwrhshgdeghgyzwpxnl.supabase.co/functions/v1/crowd-machine'}
            path.write_text(json.dumps(config)); path.chmod(0o600)
            result = module.render(path)
            text = json.dumps(result)
            for key in ('owner_key', 'worker_key', 'project_key'):
                self.assertNotIn(config[key], text)
            self.assertNotIn('__CROWD_MACHINE_', text)
            self.assertIn(hashlib.sha256(config['owner_key'].encode()).hexdigest(), text)
            self.assertEqual(result['project_id'], 'bdwrhshgdeghgyzwpxnl')
            self.assertEqual(path.read_text(), json.dumps(config))
            path.chmod(0o644)
            with self.assertRaisesRegex(ValueError, 'private_cloud_config_required'):
                module.render(path)
            path.chmod(0o600)
            link = Path(temporary) / 'link.json'; link.symlink_to(path)
            with self.assertRaises(ValueError): module.render(link)

    def test_accidental_worker_or_routing_key_in_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); source=root/'source'; source.mkdir()
            config={'owner_key':'a'*64,'worker_key':'b'*64,'project_key':'sb_publishable_example_only',
                    'endpoint':'https://bdwrhshgdeghgyzwpxnl.supabase.co/functions/v1/crowd-machine'}
            path=root/'private.json'; path.write_text(json.dumps(config)); path.chmod(0o600)
            (source/'index.ts').write_text("const ownerHash = '__CROWD_MACHINE_OWNER_SHA256__';")
            (source/'contract.mjs').write_text('export const platform = 7;')
            for name in ('worker_key','project_key'):
                (source/'core.mjs').write_text('// accidental copied config: '+config[name])
                with self.assertRaisesRegex(ValueError,'unrendered_or_sensitive_deployment'):
                    module.render(path,source)


if __name__ == '__main__':
    unittest.main()
