import unittest
from local_asr import normalize_timestamps
from long_media import validate_adjustments, merge_chunks


class TimestampTests(unittest.TestCase):
    def test_tail_estimate_is_retained_with_text(self):
        rows, adjusted = normalize_timestamps([{'start':21., 'end':24., 'text':'original'}],23.858)
        self.assertEqual(rows[0], {'start':21., 'end':23.858, 'text':'original'})
        self.assertEqual(adjusted[0]['provider_end'],24.)
        self.assertEqual(adjusted[0]['text'],'original')

    def test_large_or_invalid_overrun_fails(self):
        for start,end in [(21.,25.),(24.,24.1),(22.,21.),(float('nan'),22.)]:
            with self.assertRaisesRegex(ValueError,'timestamp_out_of_bounds'):
                normalize_timestamps([{'start':start,'end':end,'text':'original'}],23.858)

    def test_valid_timestamps_remain_unchanged(self):
        original=[{'start':0.,'end':2.,'text':'original'}]
        self.assertEqual(normalize_timestamps(original,3.),(original,[]))

    def test_exact_bound_and_cache_adjustment_validation(self):
        rows, adjusted = normalize_timestamps([{'start':2.,'end':3.5,'text':'original'}],3.)
        self.assertEqual(validate_adjustments(adjusted,rows,3.),adjusted)
        for field,value in [('provider_end',4.),('segment_index',False),('text','changed')]:
            bad=[{**adjusted[0],field:value}]
            with self.assertRaisesRegex(ValueError,'invalid_asr_timing_adjustments'):
                validate_adjustments(bad,rows,3.)

    def test_pcm_fractional_duration_epsilon_only(self):
        pcm = 16.8206875
        rows, adjusted = normalize_timestamps([{'start':0., 'end':17., 'text':'original'}], pcm)
        self.assertEqual(validate_adjustments(adjusted, rows, 69.8206875 - 53), adjusted)
        self.assertEqual(validate_adjustments(adjusted, rows, pcm - 1e-14), adjusted)
        for change in ({'adjusted_end': pcm - 1e-5}, {'provider_end': pcm + .50001}):
            with self.assertRaisesRegex(ValueError, 'invalid_asr_timing_adjustments'):
                validate_adjustments([{**adjusted[0], **change}], rows, pcm)

    def test_merged_fractional_tail_rounding_never_exceeds_asset_duration(self):
        duration = 69.8206875
        rows, adjusted = normalize_timestamps([{'start':0., 'end':17., 'text':'original'}], 16.8206875)
        manifest = {'duration_seconds': duration, 'chunks': [
            {'index':0, 'start':0., 'end':55.}, {'index':1, 'start':53., 'end':duration}]}
        merged = merge_chunks(manifest, [{'segments':[]}, {'segments':rows, 'timing_adjustments':adjusted}])
        self.assertEqual(merged['segments'][0]['end'], duration)
        self.assertTrue(all(0 <= row['start'] <= row['end'] <= duration for row in merged['segments']))
        self.assertEqual(merged['timing_adjustments'][0]['provider_absolute_end'], 70.)

    def test_native_padded_tail_is_explicit_and_bounded(self):
        raw = [{'start':54.72,'end':55.72,'text':'retained'}]
        with self.assertRaisesRegex(ValueError,'timestamp_out_of_bounds'):
            normalize_timestamps(raw,55.)
        rows, adjustments = normalize_timestamps(raw,55.,[60.])
        self.assertEqual(rows,[{'start':54.72,'end':55.,'text':'retained'}])
        self.assertEqual(adjustments[0]['provider_end'],55.72)
        self.assertEqual(adjustments[0]['provider_padding_end'],60.)
        self.assertEqual(validate_adjustments(adjustments,rows,55.),adjustments)
        for start,end,padding in [(55.,55.72,60.),(54.,56.,60.),(54.,55.72,55.5),(54.,55.72,86.),(54.,55.72,float('nan'))]:
            with self.assertRaises(ValueError):
                normalize_timestamps([{'start':start,'end':end,'text':'retained'}],55.,[padding])
        for field,value in [('provider_end',56.),('provider_padding_end',55.5),('provider_padding_end',True),('reason','unknown')]:
            with self.assertRaises(ValueError):
                validate_adjustments([{**adjustments[0],field:value}],rows,55.)
