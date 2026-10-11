"""Publishing accepts only a local job ID and never restarts analysis."""
import tempfile
import unittest
from unittest.mock import patch
from dashboard import Application

class PublishRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Application(self.temp.name)
        self.app.analysis_jobs = object()
        self.app.cloud_client = object()

    def tearDown(self):
        self.app.watchlists.close()
        if self.app.owner_tasks is not None:
            self.app.owner_tasks.close()
        self.temp.cleanup()

    def test_only_job_id_forwarded_to_server_bound_objects(self):
        with patch('analysis_artifact.publish_analysis_artifact', return_value={'ok': True}) as publish:
            self.assertEqual(self.app.analysis('publish', {'job_id': 'local-job'}), {'ok': True})
            publish.assert_called_once_with(self.app.analysis_jobs, self.app.cloud_client, 'local-job')

    def test_rejects_caller_supplied_report_or_endpoint(self):
        with patch('analysis_artifact.publish_analysis_artifact') as publish:
            for body in ({}, {'job_id': 'x', 'report_json': '{}'}, {'job_id': 'x', 'endpoint': 'https://example.com'}):
                with self.assertRaisesRegex(ValueError, 'invalid_analysis_request'):
                    self.app.analysis('publish', body)
            publish.assert_not_called()
