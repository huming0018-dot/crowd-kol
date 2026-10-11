"""Real subprocess pause/resume contracts using an owned offline processor."""
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import media_jobs


PROCESSOR = '''import argparse,json,hashlib,pathlib,time
p=argparse.ArgumentParser()
for name in ('input','asr-model','work-dir','output','platform','content-id','authorization-ref'): p.add_argument('--'+name,required=True)
a=p.parse_args(); work=pathlib.Path(a.work_dir);work.mkdir(exist_ok=True)
marker=work/'offline-provider-started';checkpoint=work/'result-0000.json'
if not marker.exists():
 marker.write_text('synthetic provider; no model')
 checkpoint.write_text('first completed synthetic chunk')
 (work/'state.json').write_text(json.dumps({'state':'transcribing','completed_chunks':1,'total_chunks':2}))
 time.sleep(30)
assert checkpoint.read_text()=='first completed synthetic chunk'
(work/'state.json').write_text(json.dumps({'state':'completed','completed_chunks':2,'total_chunks':2}))
evidence={'asset_sha256':hashlib.sha256(pathlib.Path(a.input).read_bytes()).hexdigest(),'raw_text':'Offline test only',
          'segments':[{'start':0,'end':1,'text':'first'},{'start':53,'end':54,'text':'second'}]}
pathlib.Path(a.output).write_text(json.dumps([{'platform':a.platform,'content_id':a.content_id,'evidence':evidence}]))
'''


class LongMediaJobsTests(unittest.TestCase):
    def test_real_cancel_retains_checkpoint_resume_same_job_and_completed_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model = root / 'synthetic-model'; model.mkdir()
            (model / 'crowd-model.json').write_text('{}')
            source = root / 'source.wav'; source.write_bytes(b'owned synthetic subprocess input')
            executable = root / 'offline_processor.py'; executable.write_text(PROCESSOR)
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            manager = media_jobs.MediaJobs(root, model)
            try:
                with patch.object(media_jobs, 'LONG_PROCESSOR', executable):
                    job = manager.start(source, 'weibo', '123', 'asr', 'run')
                    deadline = time.monotonic() + 5
                    while manager.status(job['job_id']).get('completed_chunks') != 1 and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertEqual(manager.status(job['job_id'])['completed_chunks'], 1)
                    folder = manager.root / job['job_id']
                    checkpoint = folder / 'long-asr/result-0000.json'
                    checkpoint_hash = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
                    manager.cancel(job['job_id'])
                    manager.threads[job['job_id']].join(timeout=5)
                    state = manager.status(job['job_id'])
                    self.assertEqual(state['state'], 'cancelled')
                    self.assertTrue(state['checkpoint_available'])
                    resumed = manager.resume(job['job_id'])
                    self.assertEqual(resumed['job_id'], job['job_id'])
                    manager.threads[job['job_id']].join(timeout=5)
                    completed = manager.status(job['job_id'])
                    self.assertEqual(completed['state'], 'completed', completed)
                    self.assertEqual(completed['completed_chunks'], 2)
                    self.assertEqual(completed['result'][0]['evidence']['segments'][1]['start'], 53)
                    self.assertEqual(hashlib.sha256(checkpoint.read_bytes()).hexdigest(), checkpoint_hash)
                    self.assertFalse(list(folder.glob('input*')))
                    self.assertTrue(manager.start(source, 'weibo', '123', 'asr', 'run')['cached'])
                    self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
            finally:
                manager.close()

    def test_missing_model_is_explicit_capability_and_no_job_created(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = media_jobs.MediaJobs(temp)
            source = Path(temp) / 'audio.wav'; source.write_bytes(b'audio')
            try:
                self.assertEqual(manager.capabilities()['asr_model_state'], 'local_model_unavailable')
                self.assertEqual(manager.capabilities()['limits']['max_audio_seconds'], 3600)
                with self.assertRaisesRegex(ValueError, 'local_asr_model_not_configured'):
                    manager.start(source, 'weibo', '123', 'asr', 'run')
                self.assertFalse(any(p.is_dir() for p in manager.root.iterdir()))
            finally:
                manager.close()


if __name__ == '__main__':
    unittest.main()
