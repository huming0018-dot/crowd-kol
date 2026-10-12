import copy
import json
import unittest

import transcript_optimize as optimize
import test_transcript_quality as fixtures
from transcript_quality import canonical, text_hash, write_json


class OptimizationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.Tests('test_new_version_original_protected_native_scores_not_reassigned')
        self.fixture.setUp()
        self.manager = self.fixture.manager
        self.evidence = self.fixture.result[0]['evidence']
        self.evidence.update(duration_seconds=70., segments=[
            {'start':53.,'end':54.,'text':'松永当天','chunk_index':0},
            {'start':53.,'end':56.,'text':'松永当天有考试熬夜复习','chunk_index':1},
            {'start':60.,'end':62.,'text':'广古亚记','chunk_index':1},
            {'start':63.,'end':65.,'text':'松永当天','chunk_index':1}])
        self.chunks = [{'index':0,'start':0.,'end':55.},{'index':1,'start':53.,'end':70.}]
        self.fixture.state['result_sha256'] = text_hash(canonical(self.fixture.result))
        self.fixture.save()
        path = self.fixture.folder/'long-asr/chunks.json'; path.unlink()
        write_json(path, {'schema':1,'asset_sha256':self.fixture.asset,'duration_seconds':70.,'chunks':self.chunks})
        self.references = {'source_asset_sha256':self.fixture.asset,'samples':[
            {'absolute_seconds':61.,'visible_hard_subtitle':'广谷亚纪','frame_sha256':'a'*64,
             'reference_basis':'human_visual_read_of_saved_source_frame','spoken_audio_reference':False}]}

    def tearDown(self):
        self.fixture.tearDown()

    def preview(self):
        return self.manager.optimization_preview(self.fixture.identity,references=self.references)

    def test_plan_local_name_and_overlap_preserves_legitimate_repeat(self):
        before=copy.deepcopy(self.evidence)
        plan=self.preview()
        self.assertEqual([edit['segment_index'] for edit in plan['edits']],[0,2])
        self.assertEqual(plan['edits'][0]['remove_overlap_with'],1)
        self.assertEqual(plan['edits'][1]['text'],'广谷亚纪')
        self.assertEqual(self.evidence,before)
        self.assertEqual(plan['model_calls'],0)
        self.assertIsNone(plan['cer'])
        self.assertFalse(plan['human_groundtruth'])

    def test_immutable_mixed_revision_parent_indices_and_chain(self):
        before=self.fixture.fingerprint(); plan=self.preview()
        created=self.manager.create_optimized_revision(self.fixture.identity,plan['result_sha256'],plan['plan_sha256'],references=self.references)
        checked=self.manager.validate(created['job_id'])
        self.assertEqual([row['text'] for row in checked['evidence']['segments']],
                         ['松永当天有考试熬夜复习','广谷亚纪','松永当天'])
        self.assertEqual(checked['evidence']['segments'][1]['start'],60.)
        self.assertEqual(checked['evidence']['quality_diagnostics'],self.evidence['quality_diagnostics'])
        self.assertEqual(before,self.fixture.fingerprint())
        revision=created['text_revision']
        self.assertEqual(revision['optimization']['plan_sha256'],plan['plan_sha256'])
        self.assertFalse(revision['human_groundtruth'])
        self.assertEqual(revision['edits'][0]['overlap_proof']['overlap_start'],53.)
        next_edit={'segment_index':2,'expected_text_sha256':text_hash('松永当天'),'text':'后来松永当天'}
        second=self.manager.create_revision(created['job_id'],created['result_sha256'],[next_edit],'machine_suggestion',True)
        self.assertEqual(self.manager.validate(second['job_id'])['revision_depth'],2)

    def test_revision_overlap_proof_tamper_rejected(self):
        plan=self.preview(); created=self.manager.create_optimized_revision(self.fixture.identity,plan['result_sha256'],plan['plan_sha256'],references=self.references)
        folder=self.manager.root/created['job_id']
        result=json.loads((folder/'result.json').read_text()); state=json.loads((folder/'state.json').read_text())
        for value in (state['text_revision'],result[0]['evidence']['text_revision']):
            value['edits'][0]['overlap_proof']['retained_text_sha256']='0'*64
        state['result_sha256']=text_hash(canonical(result))
        for name,value in (('state.json',state),('result.json',result)):
            (folder/name).unlink();write_json(folder/name,value)
        with self.assertRaisesRegex(ValueError,'parent_changed'):
            self.manager.validate(created['job_id'])

    def test_stale_plan_and_non_overlap_delete_rejected(self):
        plan=self.preview()
        with self.assertRaisesRegex(ValueError,'stale_plan'):
            self.manager.create_optimized_revision(self.fixture.identity,plan['result_sha256'],'0'*64,references=self.references)
        invalid={'segment_index':3,'expected_text_sha256':text_hash('松永当天'),'remove_overlap_with':1}
        with self.assertRaisesRegex(ValueError,'invalid_transcript_overlap_removal'):
            self.manager.create_revision(self.fixture.identity,plan['result_sha256'],[invalid],'machine_suggestion',True)
        self.assertEqual(len(list(self.manager.root.iterdir())),1)

    def test_overlap_rules_reject_same_window_separated_and_arbitrary_substring(self):
        self.assertIsNotNone(optimize.overlap_removal(self.evidence['segments'],self.chunks,0,1))
        for changes in ({'start':50.,'end':51.},{'chunk_index':1},{'text':'当天有考试'}, {'text':'松永当'}):
            rows=copy.deepcopy(self.evidence['segments']);rows[0].update(changes)
            with self.subTest(changes=changes):
                self.assertIsNone(optimize.overlap_removal(rows,self.chunks,0,1))

    def test_reference_identity_basis_and_bool_timestamp_rejected(self):
        for changes in ({'reference_basis':'automatic_platform_caption'}, {'absolute_seconds':True}, {'spoken_audio_reference':True}):
            references=copy.deepcopy(self.references);references['samples'][0].update(changes)
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                optimize.plan(self.evidence,self.chunks,references=references)
        references=copy.deepcopy(self.references);references['source_asset_sha256']='b'*64
        with self.assertRaisesRegex(ValueError,'identity_mismatch'):
            optimize.plan(self.evidence,self.chunks,references=references)

    def test_source_candidate_is_not_global_homophone_replacement(self):
        evidence=copy.deepcopy(self.evidence);evidence['segments'].append(
            {'start':66.,'end':68.,'text':'广古亚记去了别处','chunk_index':1})
        context={'asset_sha256':self.fixture.asset,'source_sha256':'c'*64,
                 'body':'案件收录：《法月纶太郎的功绩》法月纶太郎'}
        plan=optimize.plan(evidence,self.chunks,context,self.references)
        self.assertIn('法月纶太郎',[row['term'] for row in plan['lexical_candidates']])
        self.assertNotIn(4,[row['segment_index'] for row in plan['edits']])

    def test_caption_credit_and_native_score_are_flags_never_deleted(self):
        evidence=copy.deepcopy(self.evidence);evidence['segments'][3]['text']='字幕志愿者 杨茜茜'
        plan=optimize.plan(evidence,self.chunks,references=self.references)
        self.assertNotIn(3,[row['segment_index'] for row in plan['edits']])
        rules=[row['rule'] for row in plan['review_concerns']]
        self.assertIn('possible_subtitle_credit_hallucination',rules)
        self.assertIn('native_metric_review_hint',rules)

    def test_source_author_variants_need_repeat_and_role_anchor(self):
        context={'asset_sha256':self.fixture.asset,'source_sha256':'c'*64,
                 'body':'案件收录：《法月纶太郎的功绩》法月纶太郎'}
        evidence=copy.deepcopy(self.evidence)
        evidence['segments'][2]['text']='作家法越伦太郎'
        evidence['segments'][3]['text']='法越伦太郎笔下的侦探'
        plan=optimize.plan(evidence,self.chunks,context)
        changes={edit['segment_index']:edit for edit in plan['edits']}
        self.assertEqual(changes[2]['text'],'作家法月纶太郎')
        self.assertEqual(changes[3]['text'],'法月纶太郎笔下的侦探')
        self.assertEqual(changes[2]['basis']['role_anchor_segment_indices'],[2])
        evidence['segments'][2]['text']='法越伦太郎在路上'
        plan=optimize.plan(evidence,self.chunks,context)
        self.assertNotIn(2,[edit['segment_index'] for edit in plan['edits']])
        self.assertIn('source_name_variant_without_local_role_anchor',[row['rule'] for row in plan['review_concerns']])

    def test_ocr_is_a_machine_frame_reference_never_spoken_groundtruth(self):
        reference=copy.deepcopy(self.references)
        reference['samples'][0].update(reference_basis='apple_vision_ocr_saved_source_frame',ocr_result_sha256='d'*64)
        plan=optimize.plan(self.evidence,self.chunks,references=reference)
        edit=next(edit for edit in plan['edits'] if 'text' in edit)
        self.assertEqual(edit['basis']['reference_basis'],'apple_vision_ocr_saved_source_frame')
        self.assertFalse(edit['basis']['spoken_audio_reference'])
        del reference['samples'][0]['ocr_result_sha256']
        with self.assertRaisesRegex(ValueError,'invalid_transcript_optimization_reference'):
            optimize.plan(self.evidence,self.chunks,references=reference)

    def test_derived_bridge_is_explicit_and_both_assets_retained(self):
        reference=copy.deepcopy(self.references);reference['source_asset_sha256']='b'*64
        context={'asset_sha256':self.fixture.asset,'reference_source_asset_sha256':'b'*64,'source_sha256':'c'*64}
        plan=optimize.plan(self.evidence,self.chunks,context,reference)
        self.assertEqual(plan['reference_binding']['audio_asset_sha256'],self.fixture.asset)
        self.assertEqual(plan['reference_binding']['reference_source_asset_sha256'],'b'*64)
        context['reference_source_asset_sha256']='d'*64
        with self.assertRaisesRegex(ValueError,'identity_mismatch'):
            optimize.plan(self.evidence,self.chunks,context,reference)


if __name__=='__main__':unittest.main()
