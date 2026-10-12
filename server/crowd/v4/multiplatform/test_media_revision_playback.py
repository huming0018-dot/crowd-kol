"""A revision reuses verified parent bytes, never a client-provided media pointer."""
import importlib.util
import json
from pathlib import Path
import unittest
import uuid

from media_jobs import MediaJobs

spec = importlib.util.spec_from_file_location('playback_quality_fixture',
    Path(__file__).resolve().parent.parent / 'postprocess/test_transcript_quality.py')
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


class RevisionPlaybackTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.Tests()
        self.fixture.setUp()
        self.manager = MediaJobs(self.fixture.root)
        self.created = self.fixture.revise()

    def tearDown(self):
        self.manager.close()
        self.fixture.tearDown()

    def test_child_and_chain_play_parent_without_media_copy(self):
        before = self.fixture.fingerprint()
        played = self.manager.playback(self.created['job_id'], self.created['asset_sha256'])
        self.assertEqual(played['data'], self.fixture.audio)
        self.assertEqual(played['sha256'], self.fixture.asset)
        self.assertEqual(played['mime'], 'audio/mp4')
        self.assertEqual(list((self.manager.root / self.created['job_id']).glob('input*')), [])
        edit = {'segment_index':1,'expected_text_sha256':fixtures.text_hash('候选二'),'text':'第二个修订'}
        second = self.fixture.manager.create_revision(self.created['job_id'],self.created['result_sha256'],
                                                     [edit],'machine_suggestion',True)
        self.assertEqual(self.manager.playback(second['job_id'],self.fixture.asset), played)
        self.assertEqual(before, self.fixture.fingerprint())

    def test_child_source_pointer_and_asset_tampering_rejected(self):
        path = self.manager.root / self.created['job_id'] / 'state.json'
        original = json.loads(path.read_text())
        mutations = [lambda state:state.update(source_job_id=str(uuid.uuid4())),
                     lambda state:state['text_revision'].update(source_job_id=str(uuid.uuid4())),
                     lambda state:state['text_revision'].update(audio_source_job_id=str(uuid.uuid4())),
                     lambda state:state.update(asset_sha256='a'*64)]
        for mutation in mutations:
            state = json.loads(json.dumps(original)); mutation(state)
            path.write_text(fixtures.canonical(state))
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.manager.playback(self.created['job_id'],self.fixture.asset)
        path.write_text(fixtures.canonical(original))

    def test_parent_bytes_and_wrong_client_hash_rejected(self):
        with self.assertRaisesRegex(ValueError,'identity_mismatch'):
            self.manager.playback(self.created['job_id'],'a'*64)
        (self.fixture.folder/'input.m4a').write_bytes(b'changed after revision')
        with self.assertRaises(ValueError):
            self.manager.playback(self.created['job_id'],self.fixture.asset)


if __name__ == '__main__':
    unittest.main()
