import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from dashboard import Application


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.app=Application.__new__(Application);self.app.root=Path(self.temp.name).resolve();self.app.lock=threading.Lock()
        self.app.media_jobs=SimpleNamespace(status=Mock(return_value={'job_id':'new','state':'completed'}))
        self.quality=SimpleNamespace(validate=Mock(return_value={'state':{}}),optimization_preview=Mock(return_value={'plan_sha256':'p'}),create_optimized_revision=Mock(return_value={'job_id':'new'}))
        spec=SimpleNamespace(loader=SimpleNamespace(exec_module=lambda _:None))
        for target,value in [('dashboard.importlib.util.spec_from_file_location',spec),('dashboard.importlib.util.module_from_spec',SimpleNamespace(TranscriptQuality=lambda _:self.quality))]:
            patcher=patch(target,return_value=value);patcher.start();self.addCleanup(patcher.stop)
        self.context=patch('transcript_context.context',return_value=({'server_source':True},{'server_refs':True})).start();self.addCleanup(patch.stopall)
    def test_only_server_context_used_in_preview_and_apply(self):
        self.app.process_media('optimization_preview',{'job_id':'original'})
        self.assertEqual(self.quality.optimization_preview.call_args.args,('original',{'server_source':True},{'server_refs':True}))
        value=self.app.process_media('optimization_apply',{'job_id':'original','expected_result_sha256':'r','expected_plan_sha256':'p'})
        self.assertEqual(self.quality.create_optimized_revision.call_args.args,('original','r','p',{'server_source':True},{'server_refs':True}));self.assertEqual(value['job_id'],'new')
    def test_client_context_and_refs_rejected_before_file_read(self):
        for extra in ('source_context','references'):
            with self.assertRaisesRegex(ValueError,'invalid_transcript_optimization_request'):
                self.app.process_media('optimization_preview',{'job_id':'original',extra:{}})
        self.quality.validate.assert_not_called();self.context.assert_not_called()


if __name__=='__main__':unittest.main()
