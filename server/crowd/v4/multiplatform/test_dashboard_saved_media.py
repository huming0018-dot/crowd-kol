import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import Mock, patch
import dashboard


class SavedMediaDashboardTests(unittest.TestCase):
    def test_attachment_read_uses_registered_run_and_never_reimports_source(self):
        with tempfile.TemporaryDirectory() as folder:
            app=object.__new__(dashboard.Application)
            app.root=Path(folder);app.results_store=object()
            collector=app.root/'registered-collector';rid=str(uuid.uuid4())
            app._registered_run_root=Mock(return_value=collector)
            app.run=Mock(side_effect=AssertionError('source normalization must not be rewritten'))
            asset=app.root/'verified.webp';service=Mock();service.resolve.return_value=asset
            constructed=[]
            def create(root,registered,results):
                constructed.append((root,registered(rid),results));return service
            module=SimpleNamespace(SavedMediaAttachments=create)
            virtual='attachments/'+'a'*64+'/'+'b'*64+'.webp'
            with patch.dict('sys.modules',{'saved_media_attachments':module}):
                self.assertEqual(app.media_file({'run_id':rid,'path':virtual}),asset)
            self.assertEqual(constructed,[(app.root,collector/'runs'/rid,app.results_store)])
            service.resolve.assert_called_once_with(rid,virtual);app.run.assert_not_called()

    def test_artifacts_never_use_image_attachment_namespace(self):
        app=object.__new__(dashboard.Application);app.run=Mock(return_value={'ok':True,'result':{'artifacts':[]}})
        with self.assertRaisesRegex(ValueError,'media_not_in_task'):
            app.media_file({'run_id':str(uuid.uuid4()),'path':'attachments/anything'},artifact=True)
        app.run.assert_called_once()

    def test_rejects_malformed_identity_before_any_attachment_lookup(self):
        app=object.__new__(dashboard.Application)
        app.run=Mock(side_effect=AssertionError('must not run'))
        for body in ({'run_id':'not-uuid','path':'attachments/a'},
                     {'run_id':str(uuid.uuid4()),'path':[]},
                     {'run_id':str(uuid.uuid4()),'path':'attachments/a','asset_path':'private'}):
            with self.subTest(body=body),self.assertRaises((ValueError,TypeError)):
                app.media_file(body)
        app.run.assert_not_called()


if __name__=='__main__':unittest.main()
