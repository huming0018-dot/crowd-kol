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


class RevisionSpeechStatusTests(RevisionPlaybackTests):
    def setUp(self):
        import hashlib
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'postprocess'))
        import speech_precheck as sp
        super().setUp()
        # One complete original window; child intentionally owns no audio/proof.
        self.fixture.state.update(speech_check=True,total_chunks=1,completed_chunks=1)
        evidence=self.fixture.result[0]['evidence']
        evidence.update(audio_windows_processed=1)
        evidence['segments'][1]['chunk_index']=0
        self.fixture.state['result_sha256']=fixtures.text_hash(fixtures.canonical(self.fixture.result))
        self.fixture.save()
        pcm=b'owned synthetic pcm';digest=hashlib.sha256(pcm).hexdigest()
        work=self.fixture.folder/'long-asr'
        (work/'chunk-0000.wav').write_bytes(pcm)
        manifest={'schema':1,'asset_sha256':self.fixture.asset,'duration_seconds':2.,'segment_seconds':55,'overlap_seconds':2,
                  'source_kind':'authorized_local_file','network':False,
                  'chunks':[{'index':0,'start':0,'end':2.,'file':'chunk-0000.wav','sha256':digest}]}
        report={'profile':sp.PROFILE,'state':'completed','asset_sha256':self.fixture.asset,'model_sha256':sp.MODEL_SHA,
                'vad_source_sha256':sp.VAD_SOURCE_SHA,'packages':sp.PACKAGES,'options':sp.OPTIONS,
                'semantic_status':'not_reviewed','audio_was_cut':False,
                'windows':[{'index':0,'pcm_sha256':digest,'samples':32000,'intervals':[{'start':0,'end':1}],'speech_samples':1}]}
        for name,value in [('chunks.json',manifest),('speech-check.json',report)]:
            (work/name).write_text(fixtures.canonical(value))
        self.summary=sp.validate_report(report,manifest)
        self.summary['diagnostic_sha256']=hashlib.sha256((work/'speech-check.json').read_bytes()).hexdigest()
        (work/'state.json').write_text(fixtures.canonical({'state':'completed','completed_chunks':1,'total_chunks':1,'speech_precheck':self.summary}))
        self.created=self.fixture.revise()

    def test_status_child_and_chain_reuse_validated_original_vad(self):
        before=self.fixture.fingerprint()
        self.assertEqual(self.manager.status(self.created['job_id'])['speech_precheck'],self.summary)
        second=self.fixture.manager.create_revision(self.created['job_id'],self.created['result_sha256'],
            [{'segment_index':1,'expected_text_sha256':fixtures.text_hash('候选二'),'text':'第二修订'}],'machine_suggestion',True)
        self.assertEqual(self.manager.status(second['job_id'])['speech_precheck'],self.summary)
        self.assertEqual(before,self.fixture.fingerprint())

    def test_status_rejects_escaped_pointer_cycle_and_changed_pcm(self):
        path=self.manager.root/self.created['job_id']/'state.json'
        original=json.loads(path.read_text())
        for source in ('../outside',self.created['job_id']):
            state=json.loads(json.dumps(original));state['text_revision']['source_job_id']=source
            path.write_text(fixtures.canonical(state))
            with self.assertRaises(ValueError):self.manager.status(self.created['job_id'])
        path.write_text(fixtures.canonical(original))
        (self.fixture.folder/'long-asr/chunk-0000.wav').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'speech_precheck_diagnostic_changed'):
            self.manager.status(self.created['job_id'])


if __name__ == '__main__':
    unittest.main()
