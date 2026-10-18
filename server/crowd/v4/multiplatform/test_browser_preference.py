import json
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

from dashboard import Application
from account_sessions import AccountSessions
from test_browser_session import metadata, TARGET
from cloud_sync import CloudWorker
from test_cloud_sync import FakeCloud, uid
import time


class BrowserPreferenceTests(unittest.TestCase):
    def test_login_resume_keeps_original_child_session_when_preference_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            cloud = FakeCloud()
            original, newly_selected, local_id = uid(), uid(), uid()
            starts = []
            account = {'generation': 2, 'account_ref': 'f' * 64,
                       'identity_status': 'authenticated_self_id', 'state': 'logged_out',
                       'authorized_for_run': None, 'login_verified': True, 'verified_at': time.time()}
            def runner(action, payload):
                if action == 'start':
                    starts.append(payload['session_id']); return {'ok': True, 'run_id': local_id}
                if action == 'status': return {'ok': True, 'state': 'login_required', 'api_attempts': 1}
                if action == 'import': return {'ok': True, 'records': []}
                if action == 'account_status': return {'ok': True, **account}
                raise AssertionError(action)
            worker = CloudWorker(Path(folder), cloud, runner, session_selector=lambda _: original)
            worker.tick()
            # Upgrade an existing pre-binding journal, not only newly created waits.
            journal = json.loads(worker.path.read_text())
            journal.pop('session_bindings')
            worker.path.write_text(json.dumps(journal))
            worker = CloudWorker(Path(folder), cloud, runner, session_selector=lambda _: newly_selected)
            account.update(state='resumed', authorized_for_run=local_id)
            worker.tick()
            self.assertEqual(starts, [original, original])
            self.assertTrue(any(action == 'resume_login' for action, _ in cloud.calls))
            binding = json.loads(worker.path.read_text())['session_bindings'][cloud.lease['child_id']]
            self.assertEqual(binding['session_id'], original)

    def test_explicit_browser_selection_survives_restart_and_does_not_fall_back(self):
        with tempfile.TemporaryDirectory() as folder:
            app = Application(Path(folder))
            app.owner_tasks.close(); app.watchlists.close()
            store = AccountSessions(app.runner_root)
            old_id = str(uuid.uuid4())
            session = app.runner_root / 'sessions' / old_id
            session.mkdir(parents=True)
            (session / 'identity.json').write_text(json.dumps({'platform': 'bili'}))
            store.observe(old_id, 'bili', 'authenticated', run_id=str(uuid.uuid4()), account_id='123')
            original = (store.root / old_id / 'state.json').read_bytes()
            with patch('browser_session.metadata', side_effect=metadata):
                candidates = app.accounts('browser_candidates', {'session_id': old_id})
                created = app.accounts('create_browser_session', {
                    'platform': 'bili', 'port': 9222, 'target_id': TARGET,
                    'browser_fingerprint': candidates['browser_fingerprint']})
            new_id = created['session_id']
            self.assertNotEqual(new_id, old_id)
            with self.assertRaisesRegex(ValueError, 'login_session_required'):
                app._cloud_session({'platform': 'bili'})
            store.observe(new_id, 'bili', 'authenticated', account_id='123')
            self.assertEqual(app._cloud_session({'platform': 'bili'}), new_id)
            self.assertEqual((store.root / old_id / 'state.json').read_bytes(), original)
            app.configure({'mc_root': str(self.fake_mc(Path(folder)))})
            restored = Application(Path(folder))
            restored.owner_tasks.close(); restored.watchlists.close()
            self.assertEqual(restored._cloud_session({'platform': 'bili'}), new_id)
            store.observe(new_id, 'bili', 'logged_out')
            with self.assertRaisesRegex(ValueError, 'login_session_required'):
                restored._cloud_session({'platform': 'bili'})
            self.assertEqual((store.root / old_id / 'state.json').read_bytes(), original)

    @staticmethod
    def fake_mc(root):
        path = root / 'mc'; path.mkdir()
        for name in ('main.py', 'LICENSE'):
            (path / name).write_text('fixture')
        return path


if __name__ == '__main__':
    unittest.main()
