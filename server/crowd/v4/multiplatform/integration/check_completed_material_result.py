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
    @classmethod
    def setUpClass(cls):
        path=os.environ.get('CROWD_MATERIAL_COMPLETED_REQUEST')
        if not path:raise RuntimeError('CROWD_MATERIAL_COMPLETED_REQUEST_required')
        cls.request_path=Path(path)
        cls.request=json.loads(cls.request_path.read_text())
        cls.bridge=Path(os.environ['CROWD_MATERIAL_BRIDGE'])

    def invoke(self,request):
        # Existing read CLI only; stdout may contain source data and stays in memory.
        with tempfile.TemporaryDirectory() as name:
            path=Path(name).resolve()/'request.json';path.write_text(json.dumps(request));path.chmod(0o600)
            return subprocess.run([sys.executable,'-B',str(self.bridge),'--request',str(path),
                '--action','read','--format','json'],capture_output=True,timeout=30)

    def test_completed_96_publication_above_64k_reopens_without_writes(self):
        output=Path(self.request['output'])
        paths=[output/'result.json',output/'data/store.sqlite',output/'materials.jsonl',output/'materials.csv']
        before={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in paths}
        self.assertGreater((output/'result.json').stat().st_size,65536)
        self.assertLessEqual((output/'result.json').stat().st_size,MAX_SNAPSHOT)
        result=self.invoke(self.request)
        self.assertEqual(result.returncode,0,result.stderr.decode())
        data=json.loads(result.stdout)
        self.assertEqual(len(data['items']),96)
        self.assertEqual(data['items'],[json.loads(line)for line in (output/'materials.jsonl').read_text().splitlines()])
        self.assertEqual({str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in paths},before)

    def test_changed_snapshot_hash_still_rejected(self):
        result=self.invoke({**self.request,'snapshot_sha256':'0'*64})
        self.assertEqual(result.returncode,2)
        self.assertEqual(result.stdout,b'')
        self.assertEqual(result.stderr,b'material_rejected\n')


if __name__=='__main__':unittest.main()
