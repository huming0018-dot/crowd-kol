import copy,json,unittest
from local_asr import validate_native_alignment
from long_media import merge_chunks

class NativeAlignmentTests(unittest.TestCase):
    def receipt(self):
        rows=[{'start':54.66,'end':54.98,'text':'original'}]
        value={'method':'faster_whisper_word_timestamps','source':'same_native_decode_before_word_alignment',
            'pcm_duration_seconds':55.,'token_candidates':[{'start':54.66,'end':56.66,'text':'original','seek_frames':5466,'padding_end':84.66}],
            'aligned_estimates':rows,'text_sequence_equal':True,'semantic_status':'not_reviewed'}
        return rows,value
    def test_raw_padding_candidate_is_not_valid_timeline_but_retained(self):
        rows,value=self.receipt();before=copy.deepcopy(value)
        self.assertEqual(validate_native_alignment(value,rows,55.),value)
        merged=merge_chunks({'duration_seconds':55.,'chunks':[{'index':0,'start':0.,'end':55.}]},[{'segments':rows,'native_alignment':value}])
        self.assertEqual(merged['segments'][0]['end'],54.98)
        self.assertEqual(merged['native_alignment_windows'][0]['receipt']['token_candidates'][0]['end'],56.66)
        self.assertEqual(value,before)
        self.assertEqual(merged['native_alignment_windows'][0]['time_basis'],'chunk_local_seconds')
    def test_unknown_old_cache_and_changed_text_do_not_fake_identity(self):
        rows,value=self.receipt()
        self.assertIsNone(validate_native_alignment(None,rows,55.))
        changed=copy.deepcopy(value);changed['token_candidates'][0]['text']='different';changed['text_sequence_equal']=False
        self.assertEqual(validate_native_alignment(changed,rows,55.)['text_sequence_equal'],False)
        self.assertEqual(changed['aligned_estimates'][0]['text'],'original')
        changed['text_sequence_equal']=True
        with self.assertRaises(ValueError):validate_native_alignment(changed,rows,55.)
    def test_empty_aligned_window_keeps_raw_candidates_without_faking_valid_text(self):
        rows,value=self.receipt();value['aligned_estimates']=[];value['text_sequence_equal']=False
        self.assertEqual(validate_native_alignment(value,[],55.)['token_candidates'][0]['text'],'original')
        result=merge_chunks({'duration_seconds':55.,'chunks':[{'index':0,'start':0.,'end':55.}]},[{'segments':[],'native_alignment':value}])
        self.assertEqual(result['segments'],[])
        self.assertEqual(result['native_alignment_windows'][0]['receipt']['text_sequence_equal'],False)
    def test_bad_fields_and_invalid_alignment_fail_closed(self):
        rows,value=self.receipt()
        for path,change in [('method','guessed'),('source','external'),('semantic_status','accurate'),('pcm_duration_seconds',55.1),('text_sequence_equal',1),('extra','private')]:
            bad=copy.deepcopy(value);bad[path]=change
            with self.assertRaises(ValueError):validate_native_alignment(bad,rows,55.)
        for target,key,change in [('token_candidates','end',100.),('token_candidates','seek_frames',True),('token_candidates','padding_end',100.),('aligned_estimates','start',55.),('aligned_estimates','end',55.6),('aligned_estimates','text','changed'),('aligned_estimates','end',float('nan')),('token_candidates','end',10**1000)]:
            bad=copy.deepcopy(value);bad[target][0][key]=change
            with self.assertRaises(ValueError):validate_native_alignment(bad,rows,55.)
    def test_absolute_window_origin_is_kept_separate_from_native_local_times(self):
        rows,value=self.receipt()
        result=merge_chunks({'duration_seconds':108.,'chunks':[{'index':0,'start':0.,'end':55.},{'index':1,'start':53.,'end':108.}]},[{'segments':[]},{'segments':rows,'native_alignment':value}])
        self.assertEqual(result['segments'][0]['start'],107.66)
        entry=result['native_alignment_windows'][1]
        self.assertEqual(entry['chunk_start_seconds'],53.)
        self.assertEqual(entry['receipt']['aligned_estimates'][0]['start'],54.66)
        self.assertEqual(result['native_alignment_windows'][0]['status'],'unknown')
if __name__=='__main__':unittest.main()
