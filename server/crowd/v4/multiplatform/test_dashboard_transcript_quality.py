import importlib.util
from pathlib import Path
import threading
import unittest
from unittest.mock import Mock

from dashboard import Application
from media_jobs import MediaJobs


spec = importlib.util.spec_from_file_location('quality_fixture', Path(__file__).resolve().parent.parent / 'postprocess' / 'test_transcript_quality.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class CallerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.Tests()
        self.fixture.setUp()
        self.app = Application.__new__(Application)
        self.app.root = self.fixture.root
        self.app.lock = threading.Lock()
        self.app.media_jobs = MediaJobs(self.app.root)

    def tearDown(self):
        self.app.media_jobs.close()
        self.fixture.tearDown()

    def request(self):
        return {'job_id': self.fixture.identity, 'expected_result_sha256': self.fixture.state['result_sha256'],
                'edits': [self.fixture.edit()], 'reviewer_kind': 'machine_suggestion', 'acknowledge_new_version': True}

    def test_lookup_and_revision_use_original_proof_without_inference(self):
        before = self.fixture.fingerprint()
        lookup = self.app.process_media('quality_lookup', {'job_id': self.fixture.identity})
        self.assertEqual(lookup['model_calls'], 0)
        self.assertIsNone(lookup['quality']['cer'])
        created = self.app.process_media('transcript_revision', self.request())
        self.assertNotEqual(created['job_id'], self.fixture.identity)
        self.assertEqual(created['state'], 'completed')
        self.assertEqual(created['result'][0]['evidence']['segments'][0]['text'], '明确修正')
        self.assertEqual(created['source_requests'], 0)
        self.assertEqual(self.fixture.fingerprint(), before)

    def test_revision_playback_resolves_only_validated_original_audio(self):
        created = self.app.process_media('transcript_revision', self.request())
        self.app.media_jobs.playback = Mock(return_value={'data': b'fixture'})
        self.app.process_media('playback', {'job_id': created['job_id'], 'asset_sha256': created['asset_sha256']})
        self.app.media_jobs.playback.assert_called_once_with(self.fixture.identity, created['asset_sha256'])
        path = self.app.media_jobs.root / created['job_id'] / 'state.json'
        state = fixture.json.loads(path.read_text()); state['text_revision']['source_job_id'] = str(fixture.uuid.uuid4())
        path.write_text(fixture.canonical(state))
        with self.assertRaises(ValueError):
            self.app.process_media('playback', {'job_id': created['job_id'], 'asset_sha256': created['asset_sha256']})
        self.assertEqual(self.app.media_jobs.playback.call_count, 1)

    def test_strict_fields_stale_result_and_invalid_identity_do_not_save(self):
        for action, payload in [('quality_lookup', {'job_id': '../foreign'}), ('quality_lookup', {'job_id': self.fixture.identity, 'path': '/foreign'}),
                                ('transcript_revision', {**self.request(), 'expected_result_sha256': 'b' * 64}),
                                ('transcript_revision', {**self.request(), 'acknowledge_new_version': False}),
                                ('transcript_revision', {**self.request(), 'source_job_id': self.fixture.identity})]:
            with self.subTest(action=action), self.assertRaises(ValueError): self.app.process_media(action, payload)
        self.assertEqual(len(list(self.app.media_jobs.root.iterdir())), 1)


if __name__ == '__main__':
    unittest.main()
