#!/usr/bin/env python3
"""One explicit download of a pinned MIT model. No audio or credentials are sent."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import urllib.request
from urllib.parse import urlsplit

REVISION = 'd90ca5fe260221311c53c58e660288d3deb8d356'
REPO = 'Systran/faster-whisper-tiny'
FILES = ('model.bin', 'config.json', 'tokenizer.json', 'vocabulary.txt', 'README.md')
MODELS = {
    'tiny': {'repository': REPO, 'revision': REVISION, 'limit': 100_000_000,
             'model_sha256': 'dcb76c6586fc06cbdac6dd21f14cfd129cc4cdd9dce19bf4ffa62e59cbe6e6d1'},
    'small': {'repository': 'Systran/faster-whisper-small',
              'revision': '536b0662742c02347bc0e980a01041f333bce120', 'limit': 500_000_000,
              'model_sha256': '3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671'},
    # SYSTRAN's mobiuslabsgmbh mapping redirects to this public canonical repository.
    'turbo': {'repository': 'dropbox-dash/faster-whisper-large-v3-turbo',
              'revision': '0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf', 'limit': 2_000_000_000,
              'model_sha256': 'e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da',
              'files': ('model.bin', 'config.json', 'tokenizer.json', 'vocabulary.json',
                        'preprocessor_config.json', 'README.md')},
}


def model_profile(manifest):
    if (not isinstance(manifest, dict) or manifest.get('license') != 'MIT'
            or not isinstance(manifest.get('sha256'), dict)):
        raise ValueError('model_manifest_invalid')
    for name, profile in MODELS.items():
        if (manifest.get('repository'), manifest.get('revision')) == (profile['repository'], profile['revision']):
            if manifest.get('sha256', {}).get('model.bin') != profile['model_sha256']:
                raise ValueError('model_weight_hash_not_pinned')
            return name, profile
    raise ValueError('model_revision_not_supported')


def trusted_url(url):
    parsed = urlsplit(url)
    host = parsed.hostname or ''
    if (parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443)
            or not (host == 'huggingface.co' or host.endswith('.huggingface.co') or host.endswith('.hf.co'))):
        raise ValueError('model_download_host_not_allowed')


class OfficialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        trusted_url(newurl)
        return super().redirect_request(request, fp, code, message, headers, newurl)


def fetch(destination, model='tiny'):
    if model not in MODELS:
        raise ValueError('model_not_supported')
    profile = MODELS[model]
    destination = Path(destination)
    if destination.exists():
        raise ValueError('model_directory_already_exists')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.crowd-model-', dir=destination.parent) as temporary:
        directory = Path(temporary)
        hashes = {}
        file_hashes = {}
        total = 0
        deadline = time.monotonic() + (900 if model in ('small', 'turbo') else 300)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), OfficialRedirect())
        for name in profile.get('files', FILES):
            url = 'https://huggingface.co/' + profile['repository'] + '/resolve/' + profile['revision'] + '/' + name
            digest = hashlib.sha256()
            with opener.open(url, timeout=30) as response, (directory / name).open('xb') as output:
                while True:
                    if time.monotonic() >= deadline:
                        raise ValueError('model_download_deadline')
                    chunk = response.read1(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > profile['limit']:
                        raise ValueError('model_over_download_limit')
                    digest.update(chunk)
                    output.write(chunk)
            if name == 'model.bin' and digest.hexdigest() != profile['model_sha256']:
                raise ValueError('model_weight_hash_mismatch')
            file_hashes[name] = digest.hexdigest()
            if name != 'README.md':
                hashes[name] = digest.hexdigest()
        (directory / 'crowd-model.json').write_text(json.dumps({
            'repository': profile['repository'], 'revision': profile['revision'], 'license': 'MIT', 'sha256': hashes,
            'bytes': total, 'files_sha256': file_hashes}, indent=2) + '\n')
        # A new directory only: never overwrite a user's existing model.
        destination.mkdir()
        for path in directory.iterdir():
            os.replace(path, destination / path.name)
    return {'repository': profile['repository'], 'revision': profile['revision'], 'bytes': total, 'downloaded': True}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--model', choices=tuple(MODELS), default='tiny')
    a = p.parse_args()
    try:
        print(json.dumps(fetch(a.output_dir, a.model)))
    except Exception as e:
        p.exit(1, (str(e) if isinstance(e, ValueError) else 'model_download_failed') + '\n')
