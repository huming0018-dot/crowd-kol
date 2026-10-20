"""Local metadata only: no SDK import, browser, official self or state mutation."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import pro_executor as pro


class Connection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.session = dict(session_id='11111111-1111-4111-8111-111111111111', platform='tieba',
                            state='authenticated', generation=1, account_ref='a' * 64)
        self.path = self.root/'sessions'/self.session['session_id']
        self.path.mkdir(parents=True)
        self.sdk = self.root/'sdk'
        self.sdk.mkdir()

    def write(self, path, data):
        path.write_text(json.dumps(data))
        path.chmod(0o600)

    def install(self):
        self.write(self.root/'pro-executor.json', dict(root=str(self.sdk), python=sys.executable))

    def binding(self):
        self.write(self.path/'pro-binding.json', dict(platform='tieba', client_id='fixture-client',
                   cookiebridge_url='http://127.0.0.1:8274', sign_url='http://127.0.0.1:8990'))

    def check(self):
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with patch('subprocess.run', side_effect=AssertionError('metadata cannot start a process')):
            value = pro.account_connection_status(self.root, self.session)
        self.assertEqual({str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}, before)
        self.assertIs(value['authentication_checked'], False)
        self.assertIs(value['source_collection_started'], False)
        self.assertNotIn(str(self.root), json.dumps(value))
        self.assertNotIn('fixture-client', json.dumps(value))
        return value

    def test_saved_login_without_pro_connections_is_not_ready(self):
        self.session.pop('account_ref')
        value = self.check()
        self.assertEqual(value['status'], 'configuration_required')
        self.assertEqual(value['missing'], ['installation', 'binding', 'identity'])

    def test_configured_metadata_never_claims_official_login(self):
        self.install(); self.binding()
        self.assertEqual(self.check()['status'], 'connected_unverified')

    def test_identity_is_separate_from_platform_login_label(self):
        self.install(); self.binding()
        for change in ({'account_ref': None}, {'account_ref': 'foreign'}, {'generation': True}, {'generation': 0}):
            old = dict(self.session); self.session.update(change)
            value = self.check(); self.assertEqual(value['status'], 'identity_required')
            self.assertEqual(value['missing'], ['identity']); self.session = old

    def test_invalid_installation_and_binding_fail_closed_without_raw_errors(self):
        self.install(); self.binding()
        self.write(self.root/'pro-executor.json', {'root': 'SECRET-PATH', 'python': 'SECRET-CODE'})
        self.write(self.path/'pro-binding.json', {'platform': 'wb', 'cookiebridge_url': 'SECRET-COOKIE'})
        value = self.check()
        self.assertEqual(value['missing'], ['installation', 'binding'])
        self.assertNotIn('SECRET', json.dumps(value))

    def test_existing_native_bili_provider_remains_configured(self):
        self.install(); self.session['platform'] = 'bili'
        self.write(self.path/'pro-binding.json', {'platform': 'bili', 'provider': 'native_persistent'})
        self.assertEqual(self.check()['status'], 'connected_unverified')


if __name__ == '__main__':
    unittest.main()
