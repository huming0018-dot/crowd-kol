"""Cold attachment reads must not initialize or migrate the result database."""
from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid
from unittest.mock import patch
from dashboard import Application
from results_store import ResultsStore


class ExistingReader(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        store = ResultsStore(self.root)
        self.run_id = str(uuid.uuid4())
        self.virtual = 'attachments/' + 'a' * 64 + '/' + 'b' * 64 + '.jpg'
        store.ingest({'run_id': self.run_id, 'records': [
            {'platform': 'weibo', 'kind': 'media', 'media_id': 'c' * 64,
             'content_id': 'original', 'path': self.virtual, 'bytes': 12}]})
        self.original = store.list_results(filters={'kind': 'media'})['items'][0]
        self.path = store.path

    def snapshot(self):
        return {str(p.relative_to(self.root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.root.rglob('*') if p.is_file()}

    def test_cold_and_warm_attachment_reads_use_original_version_without_constructor(self):
        expected = self.original
        test = self
        class Attachment:
            def __init__(self, root, registered, results):
                self.results = results
            def resolve(self, run, path):
                test.assertEqual(self.results.saved_version('weibo', 'original', 'media',
                    expected['version_hash'], revision=expected['first_version_revision']), expected)
                with closing(self.results._connect()) as db:
                    with test.assertRaises(sqlite3.OperationalError):
                        db.execute('DELETE FROM versions')
                return test.root / 'known.jpg'
        before = self.snapshot()
        for warm in (False, True):
            app = Application.__new__(Application)
            app.root = self.root
            app.results_store = ResultsStore(self.root) if warm else None
            original_store = app.results_store
            app._registered_run_root = lambda rid: self.root
            with patch('saved_media_attachments.SavedMediaAttachments', Attachment), \
                    patch.object(ResultsStore, '__init__', side_effect=AssertionError('read cannot initialize')):
                self.assertEqual(app.media_file({'run_id': self.run_id, 'path': self.virtual}),
                                 self.root / 'known.jpg')
            self.assertIs(app.results_store, original_store)
        self.assertEqual(self.snapshot(), before)

    def test_existing_reader_matches_revision_and_rejects_writes(self):
        before = self.snapshot()
        with patch.object(ResultsStore, '__init__', side_effect=AssertionError('no initialization')):
            reader = ResultsStore.existing(self.root)
        self.assertEqual(reader.saved_version('weibo', 'original', 'media',
            self.original['version_hash']), self.original)
        with closing(reader._connect()) as db:
            self.assertEqual(db.execute('PRAGMA query_only').fetchone()[0], 1)
            with self.assertRaises(sqlite3.OperationalError):
                db.execute('CREATE TABLE unwanted(id)')
        self.assertEqual(self.snapshot(), before)

    def test_missing_database_never_creates_directories_or_files(self):
        before = self.snapshot()
        with self.assertRaises(ValueError):
            ResultsStore.existing(self.root / 'absent')
        self.assertFalse((self.root / 'absent').exists())
        self.assertEqual(self.snapshot(), before)

    def test_symlink_database_is_refused(self):
        other = self.root / 'copy.sqlite3'
        other.write_bytes(self.path.read_bytes())
        self.path.unlink()
        self.path.symlink_to(other)
        with self.assertRaises(ValueError):
            ResultsStore.existing(self.root)

    def test_corrupt_existing_database_has_fixed_attachment_error(self):
        self.path.write_bytes(b'not sqlite')
        app = Application.__new__(Application)
        app.root = self.root
        app.results_store = None
        app._registered_run_root = lambda rid: self.root
        class Attachment:
            def __init__(self, root, registered, results): self.results = results
            def resolve(self, run, path):
                return self.results.saved_version('weibo', 'original', 'media', 'a' * 64)
        with patch('saved_media_attachments.SavedMediaAttachments', Attachment), \
                self.assertRaisesRegex(ValueError, '^attachment_results_unavailable$'):
            app.media_file({'run_id': self.run_id, 'path': self.virtual})


if __name__ == '__main__':
    unittest.main()
