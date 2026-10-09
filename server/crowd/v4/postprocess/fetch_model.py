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

REVISION = 'd90ca5fe260221311c53c58e660288d3deb8d356'
REPO = 'Systran/faster-whisper-tiny'
FILES = ('model.bin', 'config.json', 'tokenizer.json', 'vocabulary.txt', 'README.md')


def fetch(destination):
    if destination.exists():
        raise ValueError('model_directory_already_exists')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.crowd-model-', dir=destination.parent) as temporary:
        directory = Path(temporary)
        hashes = {}
        total = 0
        deadline = time.monotonic() + 300
        for name in FILES:
            url = 'https://huggingface.co/' + REPO + '/resolve/' + REVISION + '/' + name
            digest = hashlib.sha256()
            with urllib.request.urlopen(url, timeout=30) as response, (directory / name).open('xb') as output:
                while True:
                    if time.monotonic() >= deadline:
                        raise ValueError('model_download_deadline')
                    chunk = response.read1(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > 100_000_000:
                        raise ValueError('model_over_100mb')
                    digest.update(chunk)
                    output.write(chunk)
            if name != 'README.md':
                hashes[name] = digest.hexdigest()
        (directory / 'crowd-model.json').write_text(json.dumps({
            'repository': REPO, 'revision': REVISION, 'license': 'MIT', 'sha256': hashes,
            'bytes': total}, indent=2) + '\n')
        # A new directory only: never overwrite a user's existing model.
        destination.mkdir()
        for path in directory.iterdir():
            os.replace(path, destination / path.name)
    return {'repository': REPO, 'revision': REVISION, 'bytes': total, 'downloaded': True}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir', type=Path, required=True)
    a = p.parse_args()
    try:
        print(json.dumps(fetch(a.output_dir)))
    except Exception as e:
        p.exit(1, (str(e) if isinstance(e, ValueError) else 'model_download_failed') + '\n')
