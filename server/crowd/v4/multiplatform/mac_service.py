"""Build the single Mac workbench service spec; never install or restart implicitly."""
import hashlib
import os
from pathlib import Path
import plistlib
import re
import stat

LABEL = 'com.crowd.unified-workbench'
ENVIRONMENT = {'PYTHONPATH', 'CROWD_FFMPEG', 'CROWD_LOCAL_ASR_MODEL', 'CROWD_LOCAL_ASR_PYTHON'}
# The existing project ASR venv links this Apple command line tools interpreter.
ASR_INTERPRETER = Path('/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/bin/python3.9')


def _regular_owned(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
        raise ValueError('regular_owned_service_file_required')


def service_plist(workspace, revision, dashboard_sha256, python, environment):
    workspace = Path(workspace)
    if not workspace.is_absolute() or workspace.is_symlink() or workspace.resolve() != workspace or not workspace.is_dir():
        raise ValueError('explicit_workspace_required')
    if not isinstance(revision, str) or not re.fullmatch('[a-f0-9]{40}', revision):
        raise ValueError('reviewed_revision_required')
    if not isinstance(dashboard_sha256, str) or not re.fullmatch('[a-f0-9]{64}', dashboard_sha256):
        raise ValueError('reviewed_dashboard_hash_required')
    dashboard = workspace / '.crowd-launch/runtime-revisions' / revision / 'server/crowd/v4/multiplatform/dashboard.py'
    if dashboard.resolve() != dashboard or not dashboard.is_file() or hashlib.sha256(dashboard.read_bytes()).hexdigest() != dashboard_sha256:
        raise ValueError('runtime_revision_mismatch')
    root = workspace / '.crowd-launch/unified-workbench'
    if root.resolve() != root or not root.is_dir() or not (root / 'dashboard-config.json').is_file():
        raise ValueError('original_workbench_root_required')
    _regular_owned(root / 'dashboard-config.json')
    executable = Path(python)
    if not executable.is_absolute() or not executable.is_file():
        raise ValueError('existing_python_required')
    if not isinstance(environment, dict) or set(environment) != ENVIRONMENT:
        raise ValueError('workbench_environment_required')
    for key, value in environment.items():
        if not isinstance(value, str) or not Path(value).is_absolute() or not Path(value).exists():
            raise ValueError('project_dependency_required')
        path = Path(value)
        if not path.resolve().is_relative_to(workspace) and not (key == 'CROWD_LOCAL_ASR_PYTHON' and path.is_relative_to(workspace) and path.resolve() == ASR_INTERPRETER):
            raise ValueError('project_dependency_required')
    logs = workspace / '.crowd-launch/workbench-service'
    if logs.resolve() != logs or (logs.exists() and not logs.is_dir()):
        raise ValueError('project_service_logs_required')
    for name in ('stdout.log', 'stderr.log'):
        path = logs / name
        if path.exists() or path.is_symlink():
            _regular_owned(path)
    return plistlib.dumps({
        'Label': LABEL,
        'ProgramArguments': [str(executable), str(dashboard), '--root', str(root), '--port', '45937'],
        'WorkingDirectory': str(workspace),
        'EnvironmentVariables': environment,
        'RunAtLoad': True,
        'KeepAlive': {'SuccessfulExit': False},
        'ThrottleInterval': 10,
        'ProcessType': 'Background',
        'StandardOutPath': str(logs / 'stdout.log'),
        'StandardErrorPath': str(logs / 'stderr.log'),
    }, sort_keys=True)
