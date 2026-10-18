#!/usr/bin/env python3
"""Run only owned bridge tests with synthetic executors and no network."""
import hashlib
import io
import json
import platform
import shutil
from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import test_mc_runner
import test_worker


def main():
    evidence = Path(sys.argv[1])
    evidence.mkdir(parents=True, exist_ok=True)
    test_mc_runner.MC = Path('/synthetic-only-not-installed')
    test_mc_runner.PYTHON = test_mc_runner.MC / '.venv/bin/python'
    stream = io.StringIO()
    began = time.monotonic()
    suite = unittest.TestSuite([
        unittest.defaultTestLoader.loadTestsFromTestCase(test_mc_runner.RunnerTest),
        unittest.defaultTestLoader.loadTestsFromTestCase(test_worker.ShutdownTests)])
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    log = stream.getvalue()
    (evidence / 'linux-runner-tests.log').write_text(log)
    print(log, flush=True)
    summary = {'schema': 'crowd_linux_worker_evidence_v1', 'platform': platform.platform(),
               'python': sys.version, 'tests_run': result.testsRun,
               'success': result.wasSuccessful(), 'seconds': time.monotonic() - began,
               'new_source_requests': 0, 'model_calls': 0, 'installed_cli_included': False,
               'linux_real_platform_login_verified': False, 'production_deployed': False,
               'source_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                 for name in ('mc_runner.py', 'test_mc_runner.py',
                                              'docker/worker.py', 'docker/verify.py',
                                              'docker/test_worker.py')}}
    (evidence / 'linux-evidence.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    # Preserve only our generated synthetic executor for the separate daemon test.
    # This never copies an installed MC checkout or a credential profile.
    fixture = test_mc_runner.RunnerTest()
    fixture.setUp()
    try:
        target = evidence / 'synthetic-executor'
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(fixture.mc, target, symlinks=True)
    finally:
        fixture.tearDown()
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main())
