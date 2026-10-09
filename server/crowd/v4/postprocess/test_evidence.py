import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('evidence',Path(__file__).with_name('evidence.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class EvidenceTests(unittest.TestCase):
    def test_authorized_transcript(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'source.vtt';f.write_text('WEBVTT\n\n00:00.000 --> 00:01.000\n原文 undefined\n')
            result=m.prepare('transcript',f,'bilibili','BV1xx411c7mD','creator-consent-1')
            self.assertEqual(result['evidence']['raw_text'],f.read_text())
            self.assertNotIn(str(f),json.dumps(result))
            self.assertEqual(len(result['evidence']['asset_sha256']),64)
            with self.assertRaises(ValueError):m.prepare('transcript',f,'bilibili','BV1xx411c7mD','')
    def test_aggregate_not_individuals(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'aggregate.json'
            row={'population':'creator-authorized export','dimension':'region','sample_size':100,'coverage_period':'2026-10','aggregate_values':{'上海':20,'其他':80}}
            f.write_text(json.dumps(row));self.assertEqual(m.prepare('demographics',f,'bilibili','BV1xx411c7mD','consent')['evidence']['sample_size'],100)
            row['user_ids']=['person'];f.write_text(json.dumps(row))
            with self.assertRaises(ValueError):m.prepare('demographics',f,'bilibili','BV1xx411c7mD','consent')
            del row['user_ids'];row['aggregate_values']={'bad':float('nan')};f.write_text(json.dumps(row))
            with self.assertRaises(ValueError):m.prepare('demographics',f,'bilibili','BV1xx411c7mD','consent')
    def test_limits_and_identity(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'source.txt';f.write_text('a'*24001)
            with self.assertRaises(ValueError):m.prepare('transcript',f,'bilibili','BV1xx411c7mD','consent')
            with self.assertRaises(ValueError):m.prepare('transcript',f,'xiaohongshu','BV1xx411c7mD','consent')

if __name__=='__main__':unittest.main()
