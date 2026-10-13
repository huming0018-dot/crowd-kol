#!/usr/bin/env python3
"""CLI client for the existing loopback workbench; never a second scheduler."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit

ROUTES = {
    'tasks': {'parse_batch', 'preview', 'create', 'list', 'status', 'stop', 'resume', 'retry_supplemental', 'reconcile'},
    'watchlists': {'preview', 'create', 'list', 'status', 'stop', 'resume'},
    'results': {'ingest', 'list', 'detail', 'evaluate', 'export'},
    'collector': {'capabilities', 'list', 'status', 'start', 'stop', 'import'},
    'media-processing': {'speech_check_bypass', 'video_ocr_start', 'capabilities', 'list', 'status', 'start', 'cancel', 'resume', 'video_cloud_status', 'video_cloud_save', 'quality_lookup', 'transcript_revision', 'optimization_preview', 'optimization_apply', 'native_video_cloud_status', 'native_video_cloud_save'},
    'cloud': {'status', 'results'},
    'accounts': {'list', 'status', 'open_login', 'cancel_login', 'resume_verification', 'confirm_same_account', 'accept_account_switch', 'browser_candidates', 'bind_browser', 'create_browser_session', 'use_persistent_browser'},
    # Starting an external model job remains an explicit UI authorization step.
    'analysis': {'lookup', 'status', 'cancel'},
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise ValueError('redirect_rejected')


def call(url, resource, action, payload):
    parsed = urlsplit(url)
    if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost')
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ('', '/') or not parsed.port):
        raise ValueError('explicit_loopback_url_required')
    if action not in ROUTES.get(resource, set()) or not isinstance(payload, dict):
        raise ValueError('invalid_cli_request')
    origin = url.rstrip('/')
    data = json.dumps({'action': action, 'payload': payload}, ensure_ascii=False).encode()
    if len(data) > 32768:
        raise ValueError('request_too_large')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(origin + '/', timeout=20) as response:
        document = response.read(512 * 1024).decode()
    match = re.search(r'<script nonce="([A-Za-z0-9_-]{32,})"', document)
    if not match:
        raise ValueError('workbench_nonce_missing')
    route = '/api/action' if resource == 'collector' else '/api/' + resource
    request = urllib.request.Request(origin + route, data=data, headers={
        'Content-Type': 'application/json', 'Origin': origin, 'X-Crowd-CSRF': match[1],
    })
    with opener.open(request, timeout=20) as response:
        body = response.read(100 * 1024 * 1024 + 1)
        if len(body) > 100 * 1024 * 1024:
            raise ValueError('response_too_large')
        if resource == 'results' and action == 'export':
            digest = hashlib.sha256(body).hexdigest()
            if digest != response.headers.get('X-Content-SHA256'):
                raise ValueError('export_hash_mismatch')
            manifest = json.loads(base64.urlsafe_b64decode(response.headers['X-Crowd-Export-Manifest']))
            return body, {**manifest, 'sha256': digest}
        value = json.loads(body)
        if value.get('ok') is False or value.get('error'):
            raise ValueError(value.get('error', 'workbench_request_failed'))
        return value, None



def save_export(path, data, manifest):
    """Reserve both paths before writing; clean only files this call created."""
    created = []
    descriptors = []
    try:
        for target in (Path(path), Path(str(path) + '.manifest.json')):
            fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            descriptors.append(fd)
            info = os.fstat(fd)
            created.append((target, info.st_dev, info.st_ino))
        for fd, content in zip(descriptors, (data, json.dumps(manifest, ensure_ascii=False, indent=2).encode())):
            with os.fdopen(os.dup(fd), 'wb') as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
    except BaseException:
        for target, device, inode in created:
            try:
                info = target.lstat()
                if (info.st_dev, info.st_ino) == (device, inode):
                    target.unlink()
            except OSError:
                pass
        raise
    finally:
        for fd in descriptors:
            os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:45937')
    parser.add_argument('resource', choices=ROUTES)
    parser.add_argument('action')
    parser.add_argument('--output', type=Path, help='New private export file; existing files are never replaced')
    args = parser.parse_args(argv)
    try:
        exporting = args.resource == 'results' and args.action == 'export'
        if exporting != bool(args.output):
            raise ValueError('export_output_required' if exporting else 'output_only_for_export')
        raw = sys.stdin.buffer.read(32769)
        if len(raw) > 32768:
            raise ValueError('request_too_large')
        payload = json.loads(raw or b'{}')
        if exporting and (args.output.exists() or Path(str(args.output) + '.manifest.json').exists()):
            raise ValueError('output_already_exists')
        result, manifest = call(args.url, args.resource, args.action, payload)
        if exporting:
            save_export(args.output, result, manifest)
            result = {'ok': True, 'output': str(args.output), 'manifest': manifest}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except urllib.error.HTTPError as error:
        try:
            value = json.loads(error.read(32768)); reason = value.get('error', 'workbench_http_error')
        except (ValueError, OSError):
            reason = 'workbench_http_error'
        print(json.dumps({'ok': False, 'error': reason, 'http_status': error.code}), file=sys.stderr)
    except (ValueError, TypeError, OSError, KeyError) as error:
        reason = str(error)
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,100}', reason):
            reason = 'workbench_unavailable_check_original_state_before_retry'
        print(json.dumps({'ok': False, 'error': reason}), file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
