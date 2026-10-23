"""Offline shutdown regression; no source, provider, Docker or credential access."""
import json
from pathlib import Path
import signal
import tempfile
import unittest
from unittest.mock import patch
import uuid

import worker


class ShutdownTests(unittest.TestCase):
    def shutdown(self, root):
        handlers = {}

        def capture(sig, handler):
            handlers[sig] = handler

        def stop_on_sleep(_):
            handlers[signal.SIGTERM](signal.SIGTERM, None)

        with patch.object(worker.signal, 'signal', side_effect=capture), \
                patch.object(worker.time, 'sleep', side_effect=stop_on_sleep), \
                patch.object(worker.os, 'waitpid', side_effect=ChildProcessError), \
                patch.object(worker.subprocess, 'run') as runner:
            worker.serve(Path('/synthetic-executor'), root)
        return [json.loads(call.kwargs['input'])['run_id'] for call in runner.call_args_list]

    def test_shutdown_stops_every_nonterminal_collection_phase(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            expected = []
            for state in ('starting', 'running', 'collecting', 'comments', 'media', 'waiting_login'):
                run_id = str(uuid.uuid4())
                folder = root / 'runs' / run_id
                folder.mkdir(parents=True)
                (folder / 'status.json').write_text(json.dumps({'state': state}))
                expected.append(run_id)
            self.assertCountEqual(self.shutdown(root), expected)

    def test_shutdown_preserves_terminal_and_skips_invalid_status(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for state in worker.FINAL:
                folder = root / 'runs' / str(uuid.uuid4())
                folder.mkdir(parents=True)
                (folder / 'status.json').write_text(json.dumps({'state': state}))
            invalid = root / 'runs' / str(uuid.uuid4())
            invalid.mkdir()
            (invalid / 'status.json').write_text('{bad json')
            self.assertEqual(self.shutdown(root), [])


if __name__ == '__main__':
    unittest.main()
