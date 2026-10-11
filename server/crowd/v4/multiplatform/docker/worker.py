#!/usr/bin/env python3
"""Persistent Linux worker; JSON actions are sent with docker exec, never HTTP."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

BRIDGE = Path(__file__).resolve().parent.parent / 'mc_runner.py'
sys.path.insert(0, str(BRIDGE.parent))
from mc_runner import FINAL
ACTIONS = ('capabilities', 'start', 'status', 'stop', 'import', 'list')


def preflight(mc, runtime):
    if sys.platform != 'linux':
        raise ValueError('linux_container_required')
    mc, runtime = Path(mc).resolve(), Path(runtime).resolve()
    if runtime == mc or mc in runtime.parents:
        raise ValueError('runtime_must_be_outside_upstream')
    for name in ('main.py', 'cmd_arg/arg.py', 'LICENSE', '.venv/bin/python'):
        if not (mc / name).is_file():
            raise ValueError('external_executor_or_linux_python_missing')
    # A Mac virtualenv can have a valid symlink while its packages remain ABI-incompatible.
    result = subprocess.run([str(mc / '.venv/bin/python'), '-c',
                             'import sys; print(sys.platform)'], capture_output=True, timeout=10)
    if result.returncode or result.stdout.strip() != b'linux':
        raise ValueError('external_linux_python_required')
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    return mc, runtime


def invoke(mc, runtime, action):
    return subprocess.run([sys.executable, str(BRIDGE), '--root', str(runtime),
                           '--mc-root', str(mc), action]).returncode


def serve(mc, runtime):
    stopping = False

    def stop_signal(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop_signal)
    signal.signal(signal.SIGINT, stop_signal)
    print(json.dumps({'ready': True, 'transport': 'docker_exec',
                      'runtime': str(runtime), 'linux_source_login_verified': False}), flush=True)
    while not stopping:
        # Reap detached bridge supervisors adopted by this PID 1 process.
        try:
            while os.waitpid(-1, os.WNOHANG)[0]:
                pass
        except ChildProcessError:
            pass
        time.sleep(0.2)
    # Preserve bridge stop semantics before Docker terminates the container.
    for folder in (runtime / 'runs').glob('*'):
        state_file = folder / 'status.json'
        if folder.is_symlink() or not state_file.is_file():
            continue
        try:
            state = json.loads(state_file.read_text())
            if state.get('state') not in FINAL:
                subprocess.run([sys.executable, str(BRIDGE), '--root', str(runtime),
                                '--mc-root', str(mc), 'stop'],
                               input=json.dumps({'run_id': folder.name}).encode(),
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    # Supervisors normally settle within their three-second termination grace.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
            if not pid:
                time.sleep(0.1)
        except ChildProcessError:
            break


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('serve',) + ACTIONS)
    parser.add_argument('--mc-root', default='/executor')
    parser.add_argument('--root', default='/runtime')
    args = parser.parse_args()
    os.umask(0o077)
    try:
        mc, runtime = preflight(args.mc_root, args.root)
        if args.action == 'serve':
            serve(mc, runtime)
            return 0
        return invoke(mc, runtime, args.action)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        code = str(error) if isinstance(error, ValueError) else 'worker_preflight_failed'
        print(json.dumps({'ok': False, 'error': code}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
