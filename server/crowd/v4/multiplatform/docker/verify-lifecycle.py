#!/usr/bin/env python3
"""Host driver: synthetic daemon/exec lifecycle with Docker network disabled."""
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

SCRIPT = Path(__file__).resolve().parent / 'worker.sh'


def main():
    evidence = Path(sys.argv[1]).resolve()
    name = 'crowd-verify-' + uuid.uuid4().hex[:12]
    commands = []

    def script(*args, payload=None):
        result = subprocess.run(['bash', str(SCRIPT), *map(str, args)],
                                input=json.dumps(payload) if payload is not None else '',
                                capture_output=True, text=True, timeout=30)
        commands.append({'action': str(args[0]), 'returncode': result.returncode})
        if result.returncode:
            raise RuntimeError('docker_lifecycle_command_failed:' + str(args[0]))
        return result.stdout

    def call(action, payload=None):
        result = json.loads(script('exec', name, action, payload=payload or {}))
        if not result.get('ok'):
            raise RuntimeError('bridge_action_failed:' + str(result.get('error')))
        return result['result']

    def settle(run, wanted):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            state = call('status', {'run_id': run['run_id']})
            if state['state'] in ('completed', 'failed', 'stopped', 'interrupted_unknown', 'login_required'):
                if state['state'] != wanted:
                    raise RuntimeError('unexpected_terminal:' + state['state'])
                return state
            time.sleep(0.1)
        raise RuntimeError('lifecycle_timeout')

    def ready():
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            logs = subprocess.run(['docker', 'logs', name], capture_output=True, text=True).stdout
            if '"ready": true' in logs:
                return
            time.sleep(0.1)
        raise RuntimeError('daemon_not_ready')

    started = False
    try:
        script('init-env', evidence / 'linux-env')
        script('start', evidence / 'synthetic-executor', evidence / 'linux-env',
               evidence / 'runtime', name)
        started = True
        # No readiness assumption from docker run's container ID.
        ready()
        payload = {'platform': 'xhs', 'mode': 'search', 'targets': ['fixture'],
                   'purpose': 'noncommercial_research'}
        completed = call('start', payload)
        settle(completed, 'completed')
        imported = call('import', {'run_id': completed['run_id']})
        assert len(imported['records']) == 2
        contents = [row for row in imported['records'] if row['kind'] == 'content']
        comments = [row for row in imported['records'] if row['kind'] == 'comment']
        assert len(contents) == len(comments) == 1
        assert contents[0]['body'] == 'body'
        assert comments[0]['content_id'] == contents[0]['content_id'] == 'id123'
        slow = call('start', {**payload, 'targets': ['slow']})
        assert call('stop', {'run_id': slow['run_id']})['stop_requested']
        settle(slow, 'stopped')
        # Separate docker exec commands must still see the persisted first result.
        assert call('import', {'run_id': completed['run_id']})['run_id'] == completed['run_id']
        before_stop = subprocess.run(['docker', 'inspect', name], capture_output=True, text=True, check=True)
        info = json.loads(before_stop.stdout)[0]
        assert info['HostConfig']['NetworkMode'] == 'none'
        assert info['HostConfig']['ReadonlyRootfs'] is True
        assert not info['HostConfig']['PortBindings']
        mounts = {m['Destination']: m for m in info['Mounts']}
        assert mounts['/executor']['RW'] is False
        assert mounts['/executor/.venv']['RW'] is False
        assert mounts['/runtime']['RW'] is True
        script('stop', name)
        started = False
        subprocess.run(['docker', 'rm', name], capture_output=True, check=True)
        script('start', evidence / 'synthetic-executor', evidence / 'linux-env',
               evidence / 'runtime', name)
        started = True
        ready()
        assert call('status', {'run_id': completed['run_id']})['state'] == 'completed'
        assert call('import', {'run_id': completed['run_id']})['run_id'] == completed['run_id']
        assert call('status', {'run_id': slow['run_id']})['state'] == 'stopped'
        script('stop', name)
        started = False
        result = {'ok': True, 'transport': 'persistent_container_docker_exec',
                  'start_terminal': 'completed', 'stop_terminal': 'stopped',
                  'import_records': len(imported['records']), 'runtime_persisted': True,
                  'verified_after_container_recreation': True,
                  'network': 'none', 'published_ports': 0, 'uid': info['Config']['User'],
                  'image_id': info['Image'], 'new_source_requests': 0, 'model_calls': 0,
                  'executor': 'owned_synthetic_fixture', 'third_party_code_in_image': False,
                  'linux_real_platform_login_verified': False, 'commands': commands}
        (evidence / 'daemon-lifecycle.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2))
    finally:
        if started:
            script('stop', name)
        subprocess.run(['docker', 'rm', name], capture_output=True)


if __name__ == '__main__':
    main()
