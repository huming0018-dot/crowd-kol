"""Read-only real publication input supplied explicitly; no build or queue action."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from material_bridge import MAX_SNAPSHOT, MaterialError, read_json

class ResultReadBound(unittest.TestCase):
    def test_existing_eight_mib_limit_accepts_exact_boundary(self):
        with tempfile.TemporaryDirectory() as name:
            p=Path(name).resolve()/'result.json'
            p.write_bytes(b'"'+b'a'*(MAX_SNAPSHOT-2)+b'"')
            self.assertEqual(len(read_json(p)),MAX_SNAPSHOT-2)

    def test_above_existing_eight_mib_limit_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            p=Path(name).resolve()/'result.json';p.write_bytes(b' '*(MAX_SNAPSHOT+1))
            with self.assertRaisesRegex(MaterialError,'material_file_invalid'):read_json(p)

    def test_duplicate_json_still_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            p=Path(name).resolve()/'result.json';p.write_text('{"items":1,"items":2}')
            with self.assertRaisesRegex(MaterialError,'material_duplicate_key'):read_json(p)

    def test_symlink_still_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            p=Path(name).resolve()/'real.json';p.write_text('{}');link=Path(name).resolve()/'result.json';link.symlink_to(p)
            with self.assertRaisesRegex(MaterialError,'material_path_symlink'):read_json(link)

    def test_malformed_json_still_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            p=Path(name).resolve()/'result.json';p.write_text('{broken')
            with self.assertRaisesRegex(MaterialError,'material_json_invalid'):read_json(p)

if __name__=='__main__':unittest.main()
