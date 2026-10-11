"""Full saved text: bounded calls, exhaustive immutable references, real fake CLI."""
import copy
import unittest
import uuid
from pathlib import Path
from mc_runner import write

from analysis_contract import build_snapshot, validate_result
from full_analysis import build_analysis_snapshot, combine_results
import test_analysis as fixtures
import test_analysis_media as media_fixtures


def item(count=1110):
    return {'job_id':str(uuid.uuid4()), 'kind':'asr', 'result_sha256':'a'*64,
        'asset_sha256':'b'*64, 'processor':'faster_whisper_local_segmented',
        'model_manifest_sha256':'c'*64, 'processor_files':{}, 'review_status':'not_reviewed',
        'segments':[{'start':float(i), 'end':float(i+1), 'text':'候选'+str(i)} for i in range(count)]}


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.imported = fixtures.imported_fixture(); self.item = item()
    def test_all_segments_bounded_and_citations_remapped(self):
        original=copy.deepcopy(self.item)
        full=build_analysis_snapshot(self.imported,'bili','video1',derived_inputs=[self.item])
        self.assertEqual(self.item,original); self.assertEqual(len(full['analysis_batches']),3)
        results=[]
        for batch in full['analysis_batches']:
            snapshot=batch['snapshot']; value=fixtures.model_fixture(snapshot)
            if batch['offsets']:
                last=snapshot['paragraphs'][-1]
                value['content_analysis']['segments']=[{'paragraph':last['paragraph'],'role':'候选','observation':'尾段'}]
            results.append(validate_result(snapshot,value))
        result=combine_results(full,results)
        self.assertEqual(result['full_analysis_coverage']['selected_segments'],1110)
        self.assertEqual(result['content_analysis']['segments'][-1]['source_ref'],'derived:'+self.item['job_id']+':1109')
        self.assertEqual(result['comment_statistics']['labeled'],2)
        self.assertEqual(len(result['comment_labels']),2)
        with self.assertRaisesRegex(ValueError,'coverage_incomplete'):combine_results(full,results[:-1])
    def test_old_single_call_hash_and_rejection_boundaries(self):
        small=item(1)
        self.assertEqual(build_snapshot(self.imported,'bili','video1',derived_inputs=[small]),
                         build_analysis_snapshot(self.imported,'bili','video1',derived_inputs=[small]))
        mutations=[lambda v:v.update(review_status='verified'),
                   lambda v:v['segments'][-1].update(start=float('nan')),
                   lambda v:v['segments'][-1].update(text='cookie=secret-value'),
                   lambda v:v.update(kind='unknown')]
        for change in mutations:
            candidate=copy.deepcopy(self.item);change(candidate)
            with self.assertRaises(ValueError):build_analysis_snapshot(self.imported,'bili','video1',derived_inputs=[candidate])
        with self.assertRaisesRegex(ValueError,'full_input_limit'):
            build_analysis_snapshot(self.imported,'bili','video1',derived_inputs=[item(8001)])
    def test_missing_or_duplicate_partition_not_called_complete(self):
        full=build_analysis_snapshot(self.imported,'bili','video1',derived_inputs=[self.item])
        results=[validate_result(batch['snapshot'],fixtures.model_fixture(batch['snapshot'])) for batch in full['analysis_batches']]
        full['analysis_batches'][-1]['offsets'][self.item['job_id']]=0
        with self.assertRaisesRegex(ValueError,'coverage_incomplete'):combine_results(full,results)


class JobsTests(fixtures.JobsTests):
    def test_real_child_process_full_run_cache_and_original_unchanged(self):
        imported=fixtures.imported_fixture(); original=copy.deepcopy(imported)
        result=self.wait(self.manager.start(imported,'bili','video1',derived_inputs=[item()]),'completed')
        self.assertEqual(result['completed_batches'],3)
        self.assertEqual(result['result']['full_analysis_coverage']['selected_segments'],1110)
        self.assertEqual(imported,original)
        self.assertEqual(len((self.manager.executable and self.base/'calls.jsonl').read_text().splitlines()),3)


class CompleteLoaderTests(media_fixtures.Tests):
    def test_truncated_preview_requires_completed_original_checkpoint(self):
        self.state['total_chunks']=93
        self.result[0]['evidence'].update(truncated=True,coverage='local_file_all_audio_windows_processed',
            audio_windows_processed=93,duration_seconds=1200.,segments=item()['segments'])
        checkpoint=self.folder/'long-asr'; checkpoint.mkdir()
        write(checkpoint/'state.json',{'state':'completed','total_chunks':93,'completed_chunks':93})
        self.save(); selected=self.choices()['options'][0]
        self.assertEqual(len(selected['segments']),1110)
        self.assertTrue(self.result[0]['evidence']['truncated'])
        write(checkpoint/'state.json',{'state':'completed','total_chunks':93,'completed_chunks':92})
        self.assertEqual(self.choices()['options'],[])
        write(checkpoint/'state.json',{'state':'running','total_chunks':93,'completed_chunks':93})
        self.assertEqual(self.choices()['options'],[])

if __name__=='__main__':unittest.main()
