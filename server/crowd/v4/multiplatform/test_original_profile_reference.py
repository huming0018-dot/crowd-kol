"""A moved data ledger must keep the existing browser's installed CookieBridge."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from account_sessions import _preserve_bound_xhs_bridge


class OriginalProfileReference(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.sid = str(uuid.uuid4())
        self.original = self.base / 'old' / 'sessions' / self.sid
        self.session = self.base / 'new' / 'sessions' / self.sid
        (self.original / 'browser_data' / 'xhs_bridge_profile').mkdir(parents=True)
        self.session.mkdir(parents=True)
        identity = {'platform': 'xhs'}
        binding = {'platform': 'xhs', 'client_id': 'fixture-original',
                   'cookiebridge_url': 'http://127.0.0.1:8274',
                   'sign_url': 'http://127.0.0.1:8275'}
        for directory in (self.original, self.session):
            for name, value in [('identity.json', identity), ('pro-binding.json', binding)]:
                self.write(directory / name, value)
        (self.session / 'browser_data').symlink_to(self.original / 'browser_data')
        self.marker = self.session / 'browser-profile-reference.json'
        self.reference = {'schema': 'crowd-pro-original-browser-profile-v1',
                          'session_id': self.sid, 'platform': 'xhs',
                          'browser_data': str(self.original / 'browser_data'),
                          'identity_sha256': self.digest(self.original / 'identity.json'),
                          'binding_sha256': self.digest(self.original / 'pro-binding.json')}
        self.write(self.marker, self.reference)

    def write(self, path, value):
        path.write_text(json.dumps(value, sort_keys=True))
        path.chmod(0o600)

    def digest(self, path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def options(self):
        return _preserve_bound_xhs_bridge(self.session.parent.parent, self.sid, 'xhs',
                                         'chromium', self.session / 'browser_data/xhs_bridge_profile', {})

    def test_marked_original_keeps_extensions_without_copying_profile(self):
        self.assertEqual(self.options(), {'ignore_default_args': ['--disable-extensions']})
        self.assertTrue((self.session / 'browser_data').is_symlink())
        self.assertEqual((self.session / 'browser_data').resolve(), self.original / 'browser_data')

    def test_unmarked_link_is_not_trusted(self):
        self.marker.unlink()
        self.assertEqual(self.options(), {})

    def test_marker_permissions_and_foreign_session_are_rejected(self):
        self.marker.chmod(0o644)
        self.assertEqual(self.options(), {})
        self.write(self.marker, {**self.reference, 'session_id': str(uuid.uuid4())})
        self.assertEqual(self.options(), {})

    def test_original_identity_or_binding_drift_is_rejected(self):
        for name in ('identity.json', 'pro-binding.json'):
            path = self.original / name
            saved = path.read_bytes()
            path.write_text('{}')
            self.assertEqual(self.options(), {})
            path.write_bytes(saved)

    def test_new_identity_drift_and_marker_symlink_are_rejected(self):
        self.write(self.session / 'identity.json', {'platform': 'bili'})
        self.assertEqual(self.options(), {})
        self.write(self.session / 'identity.json', {'platform': 'xhs'})
        saved = self.marker.read_bytes()
        self.marker.unlink()
        other = self.base / 'foreign-marker.json'
        other.write_bytes(saved)
        self.marker.symlink_to(other)
        self.assertEqual(self.options(), {})


if __name__ == '__main__':
    unittest.main()
