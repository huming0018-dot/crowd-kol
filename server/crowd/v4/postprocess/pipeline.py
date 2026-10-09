#!/usr/bin/env python3
"""Process an explicitly authorized media job exported by the KOL controller."""
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

import evidence
import media


def validate(job):
    if not isinstance(job, dict) or set(job) != {'schema_version', 'platform', 'content_id', 'authorization_ref', 'assets'} or job['schema_version'] != 1:
        raise ValueError('invalid_media_job')
    platform = job['platform']
    pattern = r'[a-f0-9]{24}' if platform == 'xiaohongshu' else r'BV[A-Za-z0-9]{10}'
    if platform not in ('xiaohongshu', 'bilibili') or not isinstance(job['content_id'], str) or not re.fullmatch(pattern, job['content_id']):
        raise ValueError('invalid_content_identity')
    if not isinstance(job['authorization_ref'], str) or not 1 <= len(job['authorization_ref'].strip()) <= 200:
        raise ValueError('authorization_reference_required')
    assets = job['assets']
    if not isinstance(assets, list) or not 1 <= len(assets) <= 2:
        raise ValueError('one_or_two_assets_required')
    for asset in assets:
        if not isinstance(asset, dict) or set(asset) != {'url', 'kind'} or asset['kind'] not in ('image', 'audio', 'video') or not isinstance(asset['url'], str):
            raise ValueError('invalid_asset')
        # Resolve and validate every URL before creating a job or downloading bytes.
        media.validate_url(asset['url'])


def write_new(path, value):
    encoded = json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8')
    if len(encoded) > 200000:
        raise ValueError('result_over_200kb')
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as stream:
        stream.write(encoded)


def run(job, destination, ocr=False, asr=False, asr_model=None):
    validate(job)
    if asr and asr_model is None:
        raise ValueError('explicit_local_asr_model_required')
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    os.chmod(destination, 0o700)
    result = {'schema_version': 1, 'platform': job['platform'], 'content_id': job['content_id'],
              'authorization_ref': job['authorization_ref'], 'uploaded': False,
              'verification': 'user_declared_not_independently_verified', 'assets': []}
    for index, asset in enumerate(job['assets']):
        status = {'index': index, 'kind': asset['kind'], 'status': 'failed'}
        # Each asset has a distinct directory; identical bytes never overwrite another result.
        directory = destination / ('asset-' + str(index + 1))
        directory.mkdir(mode=0o700)
        try:
            downloaded = media.download(asset['url'], directory)
            status.update(downloaded, status='downloaded')
            actual_kind = downloaded['content_type'].split('/')[0]
            kind = 'ocr' if ocr and actual_kind == 'image' else 'asr' if asr and actual_kind in ('video', 'audio') else None
            if actual_kind != asset['kind']:
                status['declared_kind_mismatch'] = True
            if kind:
                row = evidence.prepare(kind, directory / downloaded['file'], job['platform'], job['content_id'],
                                       job['authorization_ref'], asr_model=asr_model)
                # Persist each successful result before beginning the next asset.
                write_new(directory / 'evidence.json', [row])
                status.update(status='processed', evidence_file='asset-' + str(index + 1) + '/evidence.json')
        except (ValueError, OSError, subprocess.SubprocessError, http.client.HTTPException) as error:
            status['reason'] = str(error) if isinstance(error, ValueError) and re.fullmatch('[a-z0-9_]+', str(error)) else type(error).__name__
            if 'file' in status:
                status['status'] = 'processing_failed_download_preserved'
        result['assets'].append(status)
        write_new(destination / ('receipt-' + str(index + 1) + '.json'), status)
    write_new(destination / 'manifest.json', result)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--ocr', action='store_true')
    p.add_argument('--asr', action='store_true')
    p.add_argument('--asr-model', type=Path)
    a = p.parse_args()
    try:
        with a.manifest.open('rb') as stream:
            data = stream.read(32001)
        if len(data) > 32000:
            raise ValueError('manifest_over_32kb')
        result = run(json.loads(data), a.output_dir, a.ocr, a.asr, a.asr_model)
        states = [x['status'] for x in result['assets']]
        print(json.dumps({'downloaded': sum(x in ('downloaded', 'processed', 'processing_failed_download_preserved') for x in states),
                          'processed': states.count('processed'), 'failed': sum(x not in ('downloaded', 'processed') for x in states),
                          'uploaded': False}))
        if any(x not in ('downloaded', 'processed') for x in states):
            raise SystemExit(1)
    except (ValueError, OSError) as error:
        p.exit(1, (str(error) if isinstance(error, ValueError) and re.fullmatch('[a-z0-9_]+', str(error)) else 'invalid_media_job') + '\n')


if __name__ == '__main__':
    main()
