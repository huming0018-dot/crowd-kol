#!/usr/bin/env python3
"""Download at most two explicitly authorized public CDN assets, with no cookies.
This optional local step never runs as part of a collection task.
"""
import argparse
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import socket
import ssl
import tempfile
import time
from urllib.parse import urlsplit, urljoin

DOMAINS = ('xhscdn.com', 'xhsimg.com', 'hdslb.com')
MAX_BYTES = 25 * 1024 * 1024


def validate_url(url, resolver=socket.getaddrinfo):
    value = urlsplit(url)
    host = value.hostname or ''
    if (value.scheme != 'https' or value.username or value.password or value.port not in (None, 443)
            or not any(host == domain or host.endswith('.' + domain) for domain in DOMAINS)
            or len(url) > 4096 or any(ord(c) < 32 for c in url)):
        raise ValueError('unsupported_asset_url')
    addresses = list(dict.fromkeys(row[4][0] for row in resolver(host, 443, type=socket.SOCK_STREAM)))
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError('non_public_asset_address')
    return value, addresses


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout=20):
        super().__init__(host, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        sock = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise


def download(url, directory):
    deadline = time.monotonic() + 60
    def remaining():
        left = deadline - time.monotonic()
        if left <= 0:
            raise ValueError('asset_deadline')
        return min(20, left)
    for redirect in range(4):
        remaining()
        value, addresses = validate_url(url)
        connection = PinnedHTTPS(value.hostname, addresses[0], remaining())
        temporary = None
        try:
            target = value.path or '/'
            if value.query:
                target += '?' + value.query
            connection.request('GET', target, headers={'Accept': 'image/*, audio/*, video/*', 'User-Agent': 'CrowdAuthorizedMedia/1.0'})
            if getattr(connection, 'sock', None):
                connection.sock.settimeout(remaining())
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader('Location')
                if not location:
                    raise ValueError('redirect_missing_location')
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise ValueError('asset_http_' + str(response.status))
            mime = response.getheader('Content-Type', '').split(';')[0].lower()
            if mime.split('/')[0] not in ('image', 'audio', 'video'):
                raise ValueError('unsupported_asset_type')
            length = response.getheader('Content-Length')
            if length is not None and (not length.isdigit() or int(length) > MAX_BYTES):
                raise ValueError('asset_over_25mb')
            digest = hashlib.sha256()
            count = 0
            fd, name = tempfile.mkstemp(prefix='.crowd-download-', dir=directory)
            temporary = Path(name)
            with os.fdopen(fd, 'wb') as output:
                while True:
                    left = remaining()
                    if getattr(connection, 'sock', None):
                        connection.sock.settimeout(left)
                    chunk = response.read1(65536)
                    if not chunk:
                        break
                    count += len(chunk)
                    if count > MAX_BYTES:
                        raise ValueError('asset_over_25mb')
                    output.write(chunk)
                    digest.update(chunk)
            if not count or (length is not None and count != int(length)):
                raise ValueError('asset_incomplete')
            suffix = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp', 'audio/mpeg': '.mp3', 'audio/mp4': '.m4a', 'video/mp4': '.mp4'}.get(mime, '.bin')
            destination = directory / (digest.hexdigest() + suffix)
            os.link(temporary, destination)  # Exclusive final name: never overwrite an existing file.
            temporary.unlink()
            temporary = None
            return {'file': destination.name, 'asset_sha256': digest.hexdigest(), 'bytes': count,
                    'content_type': mime, 'source_origin': 'https://' + value.hostname}
        finally:
            connection.close()
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    raise ValueError('too_many_redirects')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url', required=True, nargs='+')
    p.add_argument('--authorization-ref', required=True)
    p.add_argument('--output-dir', required=True, type=Path)
    a = p.parse_args()
    if not 1 <= len(a.url) <= 2 or not 1 <= len(a.authorization_ref.strip()) <= 200:
        p.error('最多2个资源，必须有授权引用')
    a.output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for url in a.url:
        try:
            results.append({'status': 'downloaded', **download(url, a.output_dir)})
        except (ValueError, OSError, http.client.HTTPException) as error:
            # Neither access locators nor local paths are logged.
            results.append({'status': 'failed', 'reason': str(error) if isinstance(error, ValueError) else type(error).__name__})
    manifest = {'authorization_ref': a.authorization_ref, 'verification': 'user_declared_not_independently_verified', 'assets': results}
    name = a.output_dir / ('manifest-' + str(time.time_ns()) + '.json')
    with os.fdopen(os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(json.dumps({'downloaded': sum(x['status'] == 'downloaded' for x in results), 'failed': sum(x['status'] == 'failed' for x in results)}))
    if any(x['status'] != 'downloaded' for x in results):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
