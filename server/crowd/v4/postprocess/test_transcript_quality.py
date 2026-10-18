import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import uuid

from transcript_quality import TranscriptQuality,canonical,text_hash,write_json


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.manager=TranscriptQuality(self.root)
        self.identity=str(uuid.uuid4());self.folder=self.manager.root/self.identity;self.folder.mkdir(parents=True)
        self.audio=b'owned fixture audio';self.asset=hashlib.sha256(self.audio).hexdigest();(self.folder/'input.m4a').write_bytes(self.audio)
        self.result=[{'kind':'transcript','platform':'bilibili','content_id':'123','authorization_ref':'saved-local-asset',
          'evidence':{'source_kind':'authorized_local_file','asset_sha256':self.asset,'processor':'faster_whisper_local_segmented',
             'segments':[{'start':0.,'end':1.,'text':'候选一','chunk_index':0},{'start':1.,'end':2.,'text':'候选二','chunk_index':1}],
             'duration_seconds':2.,'timeline':'absolute_seconds','coverage':'local_file_all_audio_windows_processed','audio_windows_processed':2,
             'raw_text':'[0–1] 候选一\n[1–2] 候选二','truncated':False,'no_text_windows':0,'overlap_decisions':[],
             'quality_diagnostics':{'segments':[{'start':0.,'end':1.,'text':'候选一','segment_index':0,'chunk_index':0,'avg_logprob':-2.,'compression_ratio':1.,'no_speech_prob':.1,'flags':['low_logprob']}]}}}]
        self.state={'job_id':self.identity,'state':'completed','kind':'asr','run_id':str(uuid.uuid4()),'platform':'bilibili','content_id':'123',
                    'asset_sha256':self.asset,'total_chunks':2,'completed_chunks':2,'result_sha256':text_hash(canonical(self.result)),
                    'model_manifest_sha256':'a'*64,'processor_files':{},'created_at':1,'finished_at':2,'review_status':'not_reviewed'}
        self.save();(self.folder/'long-asr').mkdir();write_json(self.folder/'long-asr/state.json',{'state':'completed','completed_chunks':2,'total_chunks':2})
        write_json(self.folder/'long-asr/chunks.json',{'schema':1,'asset_sha256':self.asset,'duration_seconds':2.,'chunks':[{'index':0},{'index':1}]})
    def tearDown(self):self.temp.cleanup()
    def save(self):
        for name,value in [('state.json',self.state),('result.json',self.result)]:
            path=self.folder/name
            if path.exists():path.unlink()
            write_json(path,value)
    def edit(self,**change):return {'segment_index':0,'expected_text_sha256':text_hash('候选一'),'text':'明确修正',**change}
    def revise(self,**extra):
        arguments={'identity':self.identity,'expected_result_sha256':self.state['result_sha256'],'edits':[self.edit()],
                   'reviewer_kind':'machine_suggestion','acknowledge_new_version':True};arguments.update(extra)
        return self.manager.create_revision(**arguments)
    def fingerprint(self):return {str(p.relative_to(self.folder)):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.folder.rglob('*') if p.is_file()}
    def test_new_version_original_protected_native_scores_not_reassigned(self):
        before=self.fingerprint();quality=self.manager.lookup(self.identity)
        self.assertIsNone(quality['quality']['cer']);self.assertEqual(quality['quality']['flag_counts']['low_logprob'],1)
        created=self.revise();self.assertNotEqual(created['job_id'],self.identity)
        self.assertEqual(created['text_revision']['reviewer_kind'],'machine_suggestion');self.assertFalse(created['text_revision']['human_groundtruth'])
        checked=self.manager.lookup(created['job_id']);self.assertEqual(checked['segments'][0]['text'],'明确修正')
        self.assertEqual(checked['quality']['candidates'][0]['text'],'候选一');self.assertEqual(checked['quality']['review_status'],'not_reviewed')
        self.assertEqual(created['result'][0]['evidence']['segments'][0]['start'],0.)
        self.assertEqual(before,self.fingerprint());self.assertEqual(list((self.manager.root/created['job_id']).glob('input*')),[])
        self.assertEqual(checked['source_job_id'],self.identity);self.assertEqual(created['model_calls'],0)
    def test_request_bounds_and_stale_inputs(self):
        bads=[{'edits':[self.edit(segment_index=True)]},{'edits':[self.edit(segment_index=-1)]},{'edits':[self.edit(start=4)]},
              {'edits':[self.edit(text=' ')]},{'edits':[self.edit(text='x'*2001)]},{'edits':[self.edit(text='cookie=private')]},
              {'edits':[self.edit(),self.edit()]},{'edits':[self.edit(expected_text_sha256='a'*64)]},
              {'expected_result_sha256':'b'*64},{'reviewer_kind':'human'},{'acknowledge_new_version':1},{'edits':[]}]
        for change in bads:
            with self.subTest(change=list(change)),self.assertRaises(ValueError):self.revise(**change)
        self.assertEqual(len(list(self.manager.root.iterdir())),1)
    def test_parent_change_entity_cycle_unrecorded_edit_refused(self):
        created=self.revise();folder=self.manager.root/created['job_id'];state=json.loads((folder/'state.json').read_text());result=json.loads((folder/'result.json').read_text())
        for mutate in (lambda s,r:s.update(content_id='456'),lambda s,r:s.update(entity_ref='bilibili:dynamic:123'),
                       lambda s,r:(s['text_revision'].update(source_job_id=s['job_id']),r[0]['evidence']['text_revision'].update(source_job_id=s['job_id'])),
                       lambda s,r:r[0]['evidence']['segments'][1].update(text='UNRECORDED')):
            s,r=copy.deepcopy(state),copy.deepcopy(result);mutate(s,r);s['result_sha256']=text_hash(canonical(r))
            for name,value in [('state.json',s),('result.json',r)]:
                path=folder/name;path.unlink();write_json(path,value)
            with self.assertRaises(ValueError):self.manager.lookup(created['job_id'])
        for name,value in [('state.json',state),('result.json',result)]:
            path=folder/name;path.unlink();write_json(path,value)
        self.result[0]['evidence']['segments'][1]['text']='parent changed';self.state['result_sha256']=text_hash(canonical(self.result));self.save()
        with self.assertRaisesRegex(ValueError,'parent_changed'):self.manager.lookup(created['job_id'])
    def test_mlx_full_window_gate_matches_cpu(self):
        self.result[0]['evidence']['processor']='mlx_whisper_local_segmented'
        self.state['result_sha256']=text_hash(canonical(self.result))
        self.save()
        self.assertEqual(self.manager.validate(self.identity)['evidence']['processor'],'mlx_whisper_local_segmented')
        self.assertEqual(self.manager.lookup(self.identity)['source_job_id'],self.identity)
        path=self.folder/'long-asr/state.json';path.unlink()
        write_json(path,{'state':'completed','completed_chunks':1,'total_chunks':2})
        with self.assertRaisesRegex(ValueError,'checkpoint_incomplete'):
            self.manager.validate(self.identity)

    def test_incomplete_audio_mismatch_and_links(self):
        (self.folder/'input.m4a').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'audio_unverified'):self.manager.lookup(self.identity)
        (self.folder/'input.m4a').write_bytes(self.audio);path=self.folder/'long-asr/state.json';path.unlink();write_json(path,{'state':'completed','completed_chunks':1,'total_chunks':2})
        with self.assertRaisesRegex(ValueError,'checkpoint_incomplete'):self.revise()
        path.unlink();write_json(path,{'state':'completed','completed_chunks':2,'total_chunks':2})
        original=self.folder/'result.json';other=self.root/'other';os.link(original,other)
        with self.assertRaisesRegex(ValueError,'unsafe_transcript_quality_file'):self.manager.lookup(self.identity)
        other.unlink();root=self.manager.root;backup=self.root/'old';root.rename(backup);root.symlink_to(backup,target_is_directory=True)
        try:
            with self.assertRaisesRegex(ValueError,'unsafe_transcript_quality_path'):self.manager.lookup(self.identity)
        finally:root.unlink();backup.rename(root)
    def test_fresh_parent_without_counters_uses_child_manifest_result_readonly(self):
        self.state.pop('total_chunks');self.state.pop('completed_chunks');self.save();before=self.fingerprint()
        self.assertEqual(self.manager.validate(self.identity)['evidence']['segments'],self.result[0]['evidence']['segments'])
        created=self.revise();self.assertEqual(self.manager.lookup(created['job_id'])['source_job_id'],self.identity)
        self.assertFalse((self.manager.root/created['job_id']/'long-asr/chunks.json').exists())
        self.assertEqual(before,self.fingerprint())
    def test_present_parent_counts_strict_and_fresh_window_proof_mismatch_reject(self):
        for key in ('total_chunks',):
            for value in (None,True,2.,1,3):
                self.state[key]=value;self.save()
                with self.assertRaisesRegex(ValueError,'checkpoint_incomplete'):self.manager.validate(self.identity)
            self.state[key]=2
        self.state['completed_chunks']=1;self.save()
        self.assertEqual(self.manager.validate(self.identity)['evidence']['audio_windows_processed'],2)
        self.state.pop('total_chunks');self.state.pop('completed_chunks');self.save()
        checkpoint=self.folder/'long-asr/state.json';manifest=self.folder/'long-asr/chunks.json'
        original_checkpoint=checkpoint.read_bytes();original_manifest=manifest.read_bytes()
        for change in ({'state':'cancelled'},{'total_chunks':True},{'completed_chunks':1}):
            checkpoint.unlink();write_json(checkpoint,{'state':'completed','completed_chunks':2,'total_chunks':2,**change})
            with self.assertRaisesRegex(ValueError,'checkpoint_incomplete'):self.manager.validate(self.identity)
        checkpoint.write_bytes(original_checkpoint)
        for change in ({'schema':True},{'asset_sha256':'b'*64},{'duration_seconds':3},{'chunks':[{'index':0}]},{'chunks':[{'index':False},{'index':1}]}):
            manifest.unlink();write_json(manifest,{'schema':1,'asset_sha256':self.asset,'duration_seconds':2.,'chunks':[{'index':0},{'index':1}],**change})
            with self.assertRaisesRegex(ValueError,'checkpoint_incomplete'):self.manager.validate(self.identity)
        manifest.write_bytes(original_manifest)
        for value in (None,True,1,2.):
            self.result[0]['evidence']['audio_windows_processed']=value;self.state['result_sha256']=text_hash(canonical(self.result));self.save()
            with self.assertRaisesRegex(ValueError,'checkpoint_incomplete'):self.manager.validate(self.identity)
    def test_old_metrics_unknown_and_invalid_values_not_confidence(self):
        self.result[0]['evidence'].pop('quality_diagnostics');self.state['result_sha256']=text_hash(canonical(self.result));self.save()
        self.assertEqual(self.manager.lookup(self.identity)['quality']['native_metric_status'],'unknown')
        self.result[0]['evidence']['quality_diagnostics']={'segments':[{'no_speech_prob':2.,'compression_ratio':-1.,'avg_logprob':None,'flags':[]}]}
        self.state['result_sha256']=text_hash(canonical(self.result));self.save()
        self.assertEqual(self.manager.lookup(self.identity)['quality']['native_metric_status'],'unknown')
    def test_media_status_and_analysis_admit_same_entity_revision_without_input_copy(self):
        sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'multiplatform'))
        from media_jobs import MediaJobs
        from analysis_jobs import AnalysisJobs
        from analysis_contract import build_snapshot
        created=self.revise();jobs=MediaJobs(self.root);jobs.root=self.manager.root
        status=jobs.status(created['job_id']);self.assertEqual(status['state'],'completed');self.assertEqual(status['result'],created['result']);self.assertEqual(status['source_job_id'],self.identity);jobs.close()
        analysis=AnalysisJobs(self.root,executable='/not-installed-offline');imported={'run_id':self.state['run_id'],'records':[{'kind':'content','platform':'bilibili','content_id':'123','title':'原素材','body':'原正文'}]}
        snapshot=build_snapshot(imported,'bili','123');option=analysis.media_inputs(imported,snapshot,self.state['run_id'])
        self.assertIn(created['job_id'],{item['job_id'] for item in option['options']})
        chosen=next(item for item in option['options'] if item['job_id']==created['job_id']);self.assertEqual(chosen['segments'][0]['text'],'明确修正')
        ref={key:chosen[key] for key in ('job_id','result_sha256','asset_sha256')};self.assertEqual(analysis.media_inputs(imported,snapshot,self.state['run_id'],[ref])['selected'][0]['job_id'],created['job_id'])
        other={'run_id':self.state['run_id'],'records':[{'kind':'content','platform':'bilibili','content_id':'456','title':'另一个','body':'另正文'}]}
        with self.assertRaisesRegex(ValueError,'selection_invalid'):analysis.media_inputs(other,build_snapshot(other,'bili','456'),self.state['run_id'],[ref])
        analysis.close()

    def test_full_revision_selection_uses_completed_parent_without_input_copy(self):
        sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'multiplatform'))
        from analysis_jobs import AnalysisJobs
        from analysis_contract import build_snapshot
        rows=[{'start':i/1000,'end':(i+1)/1000,'text':'旧候选'+str(i),'chunk_index':i//600} for i in range(1110)]
        self.result[0]['evidence'].update(segments=rows,truncated=True,raw_text='preview')
        self.state['result_sha256']=text_hash(canonical(self.result));self.save()
        created=self.revise(edits=[{'segment_index':0,'expected_text_sha256':text_hash('旧候选0'),'text':'修订候选'}])
        jobs=AnalysisJobs(self.root,executable='/not-installed-offline');imported={'run_id':self.state['run_id'],'records':[{'kind':'content','platform':'bilibili','content_id':'123','title':'素材','body':'正文'}]};snapshot=build_snapshot(imported,'bili','123')
        v=next(row for row in jobs.media_inputs(imported,snapshot,self.state['run_id'])['options'] if row['job_id']==created['job_id'])
        self.assertEqual(len(v['segments']),1110);self.assertEqual(v['segments'][0]['text'],'修订候选')
        path=self.manager.root/created['job_id']/'state.json';state=json.loads(path.read_text());state['text_revision']['source_job_id']=str(uuid.uuid4());path.unlink();write_json(path,state)
        ref={key:v[key] for key in ('job_id','result_sha256','asset_sha256')}
        with self.assertRaisesRegex(ValueError,'selection_invalid'):jobs.media_inputs(imported,snapshot,self.state['run_id'],[ref])
        jobs.close()

    def test_eight_node_chain_valid_ninth_refused_before_write(self):
        identity=self.identity;digest=self.state['result_sha256'];text='候选一'
        for index in range(7):
            new=self.manager.create_revision(identity,digest,[{'segment_index':0,'expected_text_sha256':text_hash(text),'text':'修订'+str(index)}],'machine_suggestion',True)
            identity=new['job_id'];digest=new['result_sha256'];text='修订'+str(index)
            self.assertEqual(self.manager.validate(identity)['revision_depth'],index+1)
        self.assertEqual(len(list(self.manager.root.iterdir())),8)
        with self.assertRaisesRegex(ValueError,'chain_limit'):self.manager.create_revision(identity,digest,[{'segment_index':0,'expected_text_sha256':text_hash(text),'text':'第九'}],'machine_suggestion',True)
        self.assertEqual(len(list(self.manager.root.iterdir())),8)
    def test_constructor_does_not_resolve_away_untrusted_root_symlink(self):
        link=self.root/'alias';link.symlink_to(self.root,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'unsafe_transcript_quality_path'):TranscriptQuality(link)

    def test_unlicensed_evidence_and_processor_state_changes_rejected(self):
        created=self.revise();folder=self.manager.root/created['job_id'];state=json.loads((folder/'state.json').read_text());result=json.loads((folder/'result.json').read_text())
        mutations=[lambda s,r:r[0]['evidence'].update(duration_seconds=700),lambda s,r:r[0]['evidence'].update(processor='faster_whisper_local'),
                   lambda s,r:r[0]['evidence']['overlap_decisions'].append({'action':'fake'}),lambda s,r:r[0].update(authorization_ref='other'),
                   lambda s,r:s.update(model_manifest_sha256='b'*64),lambda s,r:s.update(total_chunks=1),
                   lambda s,r:r[0]['evidence'].update(raw_text='wrong preview')]
        for change in mutations:
            s,r=copy.deepcopy(state),copy.deepcopy(result);change(s,r);s['result_sha256']=text_hash(canonical(r))
            for name,value in [('state.json',s),('result.json',r)]:
                path=folder/name;path.unlink();write_json(path,value)
            with self.assertRaisesRegex(ValueError,'parent_changed'):self.manager.lookup(created['job_id'])

if __name__=='__main__':unittest.main()
