import unittest
from local_asr import normalize_timestamps
from long_media import validate_adjustments


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
