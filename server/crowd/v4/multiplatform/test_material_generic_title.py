"""Synthetic receipt fixtures; no cloud ACK, network or live database access."""
import copy
import hashlib
from pathlib import Path
import unittest
import uuid

from cloud_sync import SCHEMA, canonical, _hash
from material_bridge import MaterialError, snapshot_bundle


def fixture(record):
    task, child, run = (str(uuid.uuid4()) for _ in range(3))
    cid = str(uuid.uuid5(uuid.UUID(run), canonical(record)))
    envelope = dict(schema=SCHEMA, task_id=task, child_id=child, run_id=run,
                    lease_epoch=1, capture_id=cid, record=record)
    digest = _hash(SCHEMA, envelope)
    receipt = {k: envelope[k] for k in ('task_id', 'child_id', 'run_id', 'lease_epoch', 'capture_id')}
    receipt.update(status='received', reward_eligible=False, envelope_hash=digest,
                   received_at='2026-10-21T00:00:00Z')
    item = dict(capture_id=cid, envelope_hash=digest, envelope_canonical=canonical(envelope),
                receipt_canonical=canonical(receipt), envelope=envelope, receipt=receipt)
    return dict(schema='ctfs-confirmed-capture-snapshot-v1', task_id=task, child_id=child, captures=[item])


class GenericTitle(unittest.TestCase):
    def check_bundle(self, record, title):
        snapshot = fixture(record)
        before = copy.deepcopy(snapshot)
        bundle = snapshot_bundle(snapshot, Path(__file__).parent)
        self.assertEqual(snapshot, before)
        candidate = bundle['candidates'][0]
        self.assertEqual(candidate['draft']['title'], title)
        body = record['text'] if record['kind'] == 'comment' else record['body']
        self.assertEqual(candidate['draft']['text'], body)
        source = bundle['source_versions'][0]['canonical_body']
        self.assertEqual(bundle['source_versions'][0]['canonical_body_sha256'], hashlib.sha256(source.encode()).hexdigest())
        for evidence in candidate['evidence']:
            self.assertEqual(source[evidence['start']:evidence['end']], evidence['quote'])
        self.assertEqual(''.join(e['quote'] for e in candidate['evidence'] if e['field'] == 'text'), body)
        self.assertEqual(candidate['capture'], snapshot['captures'][0])

    def test_separate_original_title_and_full_body(self):
        self.check_bundle(dict(kind='content', platform='tieba', reward_eligible=False,
                               title='Original title — not a body prefix', body='Body\n' + 'x' * 11000),
                          'Original title — not a body prefix')

    def test_prefix_title_has_correct_evidence(self):
        self.check_bundle(dict(kind='content', platform='tieba', reward_eligible=False,
                               title='Title', body='Title\nFull body'), 'Title')

    def test_missing_and_blank_titles_keep_legacy_fallback(self):
        for title in (None, '', '   ', 42, []):
            record = dict(kind='content', platform='tieba', reward_eligible=False, body='b' * 120)
            if title is not None:
                record['title'] = title
            self.check_bundle(record, 'b' * 80)

    def test_comment_preserves_parent_and_media_in_capture(self):
        self.check_bundle(dict(kind='comment', platform='tieba', reward_eligible=False,
                               title='Do not change legacy comment title', text='Full reply', comment_id='reply-2', parent_comment_id='root-1',
                               media=[dict(url='https://example.invalid/image.png')]), 'Full reply')

    def test_long_special_title_is_exact(self):
        title = '  <script>&" original ' + 'T' * 120 + '  '
        self.check_bundle(dict(kind='content', platform='tieba', reward_eligible=False,
                               title=title, body='Full body'), title)

    def test_changed_title_without_matching_receipt_is_rejected(self):
        snapshot = fixture(dict(kind='content', platform='tieba', reward_eligible=False, title='Original', body='Body'))
        snapshot['captures'][0]['envelope']['record']['title'] = 'Changed'
        with self.assertRaises(MaterialError):
            snapshot_bundle(snapshot, Path(__file__).parent)


if __name__ == '__main__':
    unittest.main()
