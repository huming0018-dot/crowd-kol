"""Caller deadlines only: simulated elapsed time, no real sleep/SDK/build/network."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

import dashboard as D
import material_auto_worker as W
from automatic_materials import write,private_json

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

class MaterialReadDeadlines(unittest.TestCase):
    def dashboard_read(self,seconds,size=None):
        with tempfile.TemporaryDirectory()as name:
            root=Path(name).resolve();data=root/'data-products';data.mkdir()
            script=root/'bridge.py';script.write_text('# own test bridge\n')
            request=root/'request.json';request.write_text('{}')
            write(data/'material-runtime.json',{'python':sys.executable,'script':str(script),
                'script_sha256':sha(script),'request':str(request),'request_sha256':sha(request)})
            body=json.dumps({'items':list(range(96))}).encode()if size is None else b'x'*size
            def run(command,**kw):
                self.assertEqual(command[-4:],['--action','read','--format','json'])
                if kw['timeout']<seconds:raise subprocess.TimeoutExpired(command,kw['timeout'])
                kw['stdout'].write(body);return SimpleNamespace(returncode=0)
            with patch.object(D.subprocess,'run',side_effect=run):
                return D.Application.material_delivery(SimpleNamespace(root=root),'json')

    def test_real_observed_18_85_seconds_fits_dashboard_read_deadline(self):
        self.assertEqual(len(json.loads(self.dashboard_read(18.85))['items']),96)

    def test_dashboard_deadline_still_finite(self):
        with self.assertRaisesRegex(ValueError,'material_delivery_unavailable'):self.dashboard_read(60.01)

    def test_dashboard_original_output_bound_still_applies(self):
        with self.assertRaisesRegex(ValueError,'material_delivery_unavailable'):
            self.dashboard_read(18.85,16*1024*1024+1)

    def worker_read(self,seconds):
        with tempfile.TemporaryDirectory()as name:
            root=Path(name).resolve();base=root/'data-products/material-auto';base.mkdir(parents=True)
            runtime=root/'runtime';runtime.mkdir();cloud=runtime/'cloud_sync.py';cloud.write_text('# own fixture\n')
            bridge=root/'bridge.py';bridge.write_text('from pathlib import Path\ndef read_bytes(path,limit):return Path(path).read_bytes()\n')
            pins=root/'pins.json';pins.write_text('{}')
            local,task,child,run=[str(uuid.uuid4())for _ in range(4)]
            context={'schema':'crowd-material-postprocessing-v1','local_run_id':local,'task_id':task,
                'child_id':child,'cloud_run_id':run,'lease_epoch':1,'platform':'xhs','outcome':'completed',
                'api_attempts':46,'finish_hash':'a'*64,'finish_verified':True}
            state=base/(local+'.json');write(state,{'state':'waiting','context':context})
            snapshot={'captures':[{'capture_id':str(i),'envelope_hash':'a'*64,
                'receipt':{'received_at':'2026-10-22T00:00:00Z'},'receipt_canonical':'{}'}for i in range(96)],
                'delivery_selection':{'historical_material_rows':0},'coverage':'unverified'}
            cfg={'python':sys.executable,'worker_script':W.__file__,'worker_sha256':sha(Path(W.__file__)),
                'toolbox_root':str(root),'toolbox_pins':str(pins),'pack_path':str(root),'pack_sha256':{},
                'bridge_path':str(bridge),'bridge_sha256':sha(bridge),'runtime_root':str(runtime),'runtime_cloud_sha256':sha(cloud)}
            calls=[]
            def run(command,**kw):
                action=command[command.index('--action')+1];calls.append((action,kw['timeout']))
                if action=='read'and kw['timeout']<seconds:raise subprocess.TimeoutExpired(command,kw['timeout'])
                return SimpleNamespace(returncode=0,stdout=json.dumps({'items':[{}]*96}).encode())
            with patch.object(W,'read_scope_rows',return_value=[]),patch.object(W,'extract_rows',return_value=snapshot),\
                 patch.object(W.subprocess,'run',side_effect=run):
                try:W.process(root,state,cfg)
                except subprocess.TimeoutExpired:
                    self.assertEqual(private_json(state)['state'],'processing')
                    self.assertFalse((root/'data-products/material-runtime.json').exists())
                    raise
            return private_json(state),calls

    def test_real_observed_18_85_seconds_fits_worker_read_not_build_change(self):
        state,calls=self.worker_read(18.85)
        self.assertEqual(state['state'],'ready');self.assertEqual(state['items'],96)
        self.assertEqual(calls,[('build-jobs',150),('read',60)])

    def test_worker_deadline_still_finite_without_ready(self):
        with self.assertRaises(subprocess.TimeoutExpired):self.worker_read(60.01)

if __name__=='__main__':unittest.main()
