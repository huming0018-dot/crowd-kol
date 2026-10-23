import hashlib
from pathlib import Path
import plistlib
import tempfile
import unittest

from mac_service import ENVIRONMENT, LABEL, service_plist


class MacServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.revision = 'a' * 40
        self.source = self.root / '.crowd-launch/runtime-revisions' / self.revision / 'server/crowd/v4/multiplatform/dashboard.py'
        self.source.parent.mkdir(parents=True)
        self.source.write_text('reviewed source')
        self.sha = hashlib.sha256(self.source.read_bytes()).hexdigest()
        runtime = self.root / '.crowd-launch/unified-workbench'
        runtime.mkdir()
        (runtime / 'dashboard-config.json').write_text('{}')
        self.python = self.root / 'python'
        self.python.write_text('synthetic executable')
        self.env = {key: str(self.root) for key in ENVIRONMENT}

    def build(self, **kwargs):
        args = {'workspace': self.root, 'revision': self.revision, 'dashboard_sha256': self.sha, 'python': self.python, 'environment': self.env}
        args.update(kwargs)
        return service_plist(**args)

    def test_exact_revision_original_data_and_no_shell_or_periodic_scheduler(self):
        value = plistlib.loads(self.build())
        self.assertEqual(value['Label'], LABEL)
        self.assertEqual(value['ProgramArguments'][1], str(self.source))
        self.assertEqual(value['ProgramArguments'][-1], '45937')
        self.assertEqual(value['KeepAlive'], {'SuccessfulExit': False})
        self.assertNotIn('StartInterval', value)
        self.assertNotIn('StartCalendarInterval', value)
        self.assertEqual(list(self.root.glob('*.plist')), [])

    def test_changed_source_bad_revision_or_hash_refused(self):
        for args in ({'revision': '../other'}, {'dashboard_sha256': 'b' * 64}, {'dashboard_sha256': True}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.build(**args)

    def test_credentials_or_external_dependencies_not_accepted(self):
        for env in ({**self.env, 'SERVICE_ROLE_KEY': 'synthetic'}, {**self.env, 'PYTHONPATH': '/usr'}, {**self.env, 'PYTHONPATH': None}):
            with self.subTest(env=env), self.assertRaises(ValueError):
                self.build(environment=env)

    def test_symlink_source_or_data_root_not_accepted(self):
        target = self.root / 'other-source'
        target.write_bytes(self.source.read_bytes())
        self.source.unlink()
        self.source.symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'runtime_revision_mismatch'):
            self.build()

    def test_config_or_existing_log_aliases_refused(self):
        config = self.root / '.crowd-launch/unified-workbench/dashboard-config.json'
        external = self.root / 'external-config'
        external.write_text('{}')
        config.unlink()
        config.symlink_to(external)
        with self.assertRaisesRegex(ValueError, 'regular_owned_service_file_required'):
            self.build()
        config.unlink()
        config.write_text('{}')
        logs = self.root / '.crowd-launch/workbench-service'
        logs.mkdir()
        (logs / 'stdout.log').symlink_to(external)
        with self.assertRaisesRegex(ValueError, 'regular_owned_service_file_required'):
            self.build()

    def test_only_exact_existing_asr_interpreter_alias_allowed(self):
        from mac_service import ASR_INTERPRETER
        if not ASR_INTERPRETER.exists():
            self.skipTest('Apple interpreter absent; no installation')
        alias = self.root / 'asr-python'
        alias.symlink_to(ASR_INTERPRETER)
        self.build(environment={**self.env, 'CROWD_LOCAL_ASR_PYTHON': str(alias)})
        with self.assertRaises(ValueError):
            self.build(environment={**self.env, 'PYTHONPATH': str(alias)})


if __name__ == '__main__':
    unittest.main()
