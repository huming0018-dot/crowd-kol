import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from mc_runner import normalize,canonical
from transcript_context import context


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.run='12345678-1234-4234-8234-123456789012'
        self.folder=self.root/'runs'/self.run;(self.folder/'output').mkdir(parents=True)
        raw=(json.dumps({'video_id':'123','title':'题目','desc':'作者原文'},ensure_ascii=False)+'\n').encode();self.original=self.folder/'output/source.jsonl';self.original.write_bytes(raw)
        origin={'run_id':self.run,'file_sha256':hashlib.sha256(raw).hexdigest(),'line':1}
        self.row=normalize('bili','content',json.loads(raw),origin)
        self.source={'records':[self.row],'files':[{'path':'output/source.jsonl','sha256':origin['file_sha256']}],'media':[]}
        self.app=SimpleNamespace(root=self.root,_registered_run_root=lambda _:self.root)
        self.saved={'state':{'run_id':self.run,'content_id':'123','platform':'bilibili','asset_sha256':'a'*64}}
        self.store()
    def store(self):
        (self.folder/'normalized.json').write_text(canonical(self.source))
    def test_registered_source_replayed_and_no_refs_supported(self):
        value,refs=context(self.app,self.saved);self.assertIsNone(refs);self.assertEqual(value['body'],'作者原文');self.assertEqual(value['source_sha256'],self.row['record_hash'])
    def test_hash_or_original_jsonl_changes_fail(self):
        self.original.write_text('changed')
        with self.assertRaisesRegex(ValueError,'source_changed'):context(self.app,self.saved)
    def test_forged_normalized_text_with_valid_self_hash_fails_replay(self):
        self.row['body']='forged';self.row['record_hash']=hashlib.sha256(canonical({k:v for k,v in self.row.items() if k not in ('record_hash','discovery_kind')}).encode()).hexdigest();self.store()
        with self.assertRaisesRegex(ValueError,'source_changed'):context(self.app,self.saved)
    def test_foreign_content_or_path_denied(self):
        self.saved['state']['content_id']='other'
        with self.assertRaisesRegex(ValueError,'source_ambiguous'):context(self.app,self.saved)
        self.saved['state']['content_id']='123';self.source['files'][0]['path']='../source.jsonl';self.store()
        with self.assertRaisesRegex(ValueError,'source_changed'):context(self.app,self.saved)
    def reference_fixture(self):
        self.directory=self.root/'transcript-references'/('a'*64);self.directory.mkdir(parents=True)
        video=b'original video';self.video=self.folder/'output/video.mp4';self.video.write_bytes(video)
        frame=b'reference PNG';(self.directory/'one.png').write_bytes(frame)
        native={'platform':'bilibili','content_id':'123','content_identity_basis':'same_native_bilibili_view','source_media_id':'BV1234567890','bilibili_view_cid':'456'}
        self.audio={**native,'sha256':'a'*64};self.visual={**native,'sha256':hashlib.sha256(video).hexdigest(),'path':'output/video.mp4'}
        self.source['media']=[self.audio,self.visual];self.store()
        self.reference={'source_run_id':self.run,'source_asset_sha256':self.visual['sha256'],'samples':[{'frame_file':'one.png','frame_sha256':hashlib.sha256(frame).hexdigest()}]};self.save_reference()
        def identity(_folder,_cid,asset,_entity,**_mode):return None,None,None,self.audio if asset=='a'*64 else self.visual,None,None
        checker=patch('media_native._identity',side_effect=identity);self.native=checker.start();self.addCleanup(checker.stop)
    def save_reference(self):
        (self.directory/'reference.json').write_text(canonical(self.reference))
    def test_native_content_bridge_validates_both_original_assets(self):
        self.reference_fixture();value,refs=context(self.app,self.saved)
        self.assertEqual(self.native.call_count,2);self.assertEqual(value['reference_source_asset_sha256'],self.visual['sha256']);self.assertNotEqual(value['asset_sha256'],refs['source_asset_sha256']);self.assertNotIn('frame_file',refs['samples'][0])
    def test_native_cid_mismatch_rejected(self):
        self.reference_fixture();self.visual['bilibili_view_cid']='other';self.store()
        with self.assertRaisesRegex(ValueError,'binding_denied'):context(self.app,self.saved)
    def test_video_or_frame_mutation_rejected(self):
        self.reference_fixture();self.video.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'reference_changed'):context(self.app,self.saved)
        self.video.write_bytes(b'original video');(self.directory/'one.png').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'reference_changed'):context(self.app,self.saved)
    def test_reference_frame_path_rejected(self):
        self.reference_fixture();self.reference['samples'][0]['frame_file']='../one.png';self.save_reference()
        with self.assertRaisesRegex(ValueError,'reference_changed'):context(self.app,self.saved)


if __name__=='__main__':unittest.main()
