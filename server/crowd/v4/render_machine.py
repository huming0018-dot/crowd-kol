"""Render an existing machine deployment; never return role keys or contact a server."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit


def render(config_path, source=None):
    config_path = Path(config_path)
    if config_path.is_symlink() or not config_path.is_file() or config_path.stat().st_mode & 0o077:
        raise ValueError('private_cloud_config_required')
    if config_path.stat().st_size > 10000:
        raise ValueError('cloud_config_size_limit')
    config = json.loads(config_path.read_text())
    key = config.get('owner_key')
    if not isinstance(key, str) or not re.fullmatch('[a-f0-9]{64}', key):
        raise ValueError('existing_owner_key_required')
    private_values = [config[name] for name in ('owner_key', 'worker_key', 'project_key')
                      if isinstance(config.get(name), str) and config[name]]
    endpoint = urlsplit(config.get('endpoint', ''))
    host = endpoint.hostname or ''
    suffix = '.supabase.co'
    project = host[:-len(suffix)] if host.endswith(suffix) else ''
    if (endpoint.scheme != 'https' or not re.fullmatch('[a-z0-9]{20}', project)
            or endpoint.username or endpoint.password or endpoint.port or endpoint.query
            or endpoint.fragment or endpoint.path != '/functions/v1/crowd-machine'):
        raise ValueError('machine_endpoint_required')
    source = Path(source) if source else Path(__file__).parent / 'supabase/functions/crowd-machine'
    files = []
    for name in ('index.ts', 'core.mjs', 'contract.mjs'):
        path = source / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('machine_source_required')
        content = path.read_text()
        if name == 'index.ts':
            marker = '__CROWD_MACHINE_OWNER_SHA256__'
            if content.count(marker) != 1:
                raise ValueError('owner_hash_template_required')
            content = content.replace(marker, hashlib.sha256(key.encode()).hexdigest())
        if '__CROWD_MACHINE_' in content or any(value in content for value in private_values):
            raise ValueError('unrendered_or_sensitive_deployment')
        files.append({'name': name, 'content': content})
    return {'project_id': project, 'name': 'crowd-machine', 'entrypoint_path': 'index.ts',
            'verify_jwt': False, 'files': files}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(render(args.config)))
    except (ValueError, OSError, TypeError):
        parser.exit(1, 'machine_deployment_render_failed\n')
