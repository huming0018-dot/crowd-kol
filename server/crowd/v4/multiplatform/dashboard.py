#!/usr/bin/env python3
"""Local-only task UI for a separately installed MediaCrawler executor."""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, quote
import uuid
import webbrowser

HERE = Path(__file__).resolve().parent
ACTIONS = {'capabilities', 'start', 'status', 'stop', 'import', 'list'}


class Application:
    def __init__(self, root, mc_root=None):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.config_path = self.root / 'dashboard-config.json'
        self.runner_root = self.root / 'collector'
        self.lock = threading.Lock()
        self.token = secrets.token_urlsafe(32)
        try:
            config = json.loads(self.config_path.read_text())
            self.mc_root = config.get('mc_root', '')
        except (OSError, ValueError):
            self.mc_root = ''
        if mc_root:
            self.mc_root = str(Path(mc_root).expanduser().resolve())
        if not self.mc_root:
            candidates = [p for p in (Path.home() / 'WorkBuddy').glob('*/MediaCrawler')
                          if (p / 'main.py').is_file() and (p / 'LICENSE').is_file()]
            if len(candidates) == 1:
                self.mc_root = str(candidates[0].resolve())

    def configure(self, body):
        if set(body) != {'mc_root'} or not isinstance(body['mc_root'], str):
            raise ValueError('invalid_configuration')
        path = Path(body['mc_root']).expanduser().resolve()
        if not all((path / name).is_file() for name in ['main.py', 'LICENSE']):
            raise ValueError('mediacrawler_directory_required')
        with self.lock:
            data = json.dumps({'mc_root': str(path)}).encode()
            temporary = self.root / ('config-' + secrets.token_hex(8))
            with os.fdopen(os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as f:
                f.write(data)
            temporary.replace(self.config_path)
            self.mc_root = str(path)
        return {'ok': True, 'mc_root': self.mc_root}

    def run(self, action, payload):
        if action not in ACTIONS or not isinstance(payload, dict):
            raise ValueError('invalid_action')
        if not self.mc_root:
            raise ValueError('configure_executor_first')
        command = [sys.executable, str(HERE / 'mc_runner.py'), '--root', str(self.runner_root),
                   '--mc-root', self.mc_root, action]
        # The runner consumes JSON, never a shell command or browser credentials.
        try:
            result = subprocess.run(command, input=json.dumps(payload), text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    timeout=15, check=False)
        except subprocess.TimeoutExpired:
            return {'ok': False, 'error': 'runner_response_timeout_check_runs_before_retry'}
        if len(result.stdout.encode()) > 10 * 1024 * 1024:
            return {'ok': False, 'error': 'runner_result_too_large'}
        try:
            value = json.loads(result.stdout)
        except ValueError:
            return {'ok': False, 'error': 'runner_unavailable'}
        if not isinstance(value, dict):
            return {'ok': False, 'error': 'invalid_runner_result'}
        return value

    def media_file(self, body):
        if set(body) != {'run_id', 'path'} or not isinstance(body['path'], str):
            raise ValueError('invalid_media_request')
        run_id = str(uuid.UUID(body['run_id']))
        if run_id != body['run_id']:
            raise ValueError('invalid_run_id')
        response = self.run('import', {'run_id': run_id})
        if response.get('ok') is False:
            raise ValueError('results_not_ready')
        media = response.get('result', response).get('media', [])
        if body['path'] not in {item['path'] for item in media}:
            raise ValueError('media_not_in_task')
        run = self.runner_root / 'runs' / run_id
        path = run / body['path']
        if path.is_symlink() or not path.resolve().is_relative_to((run / 'output').resolve()) or not path.is_file():
            raise ValueError('unsafe_media_path')
        if path.stat().st_size > 500 * 1024 * 1024:
            raise ValueError('media_over_download_limit')
        return path


def make_server(app, port=45937):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass  # No task targets, local paths or source records in HTTP logs.

        def allowed_host(self):
            expected = str(self.server.server_port)
            return self.headers.get('Host') in ('127.0.0.1:' + expected, 'localhost:' + expected)

        def send(self, value, code=200, html=False):
            data = value.encode() if html else json.dumps(value, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'text/html; charset=utf-8' if html else 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'nonce-" + app.token + "'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self.allowed_host():
                return self.send({'ok': False, 'error': 'host_rejected'}, 403)
            path = urlsplit(self.path).path
            if path == '/':
                document = (HERE / 'dashboard.html').read_text()
                return self.send(document.replace('__NONCE__', app.token), html=True)
            if path == '/api/config':
                return self.send({'ok': True, 'mc_root': app.mc_root})
            return self.send({'ok': False, 'error': 'not_found'}, 404)

        def do_POST(self):
            expected = {'http://127.0.0.1:' + str(self.server.server_port), 'http://localhost:' + str(self.server.server_port)}
            if not self.allowed_host() or self.headers.get('Origin') not in expected or not secrets.compare_digest(self.headers.get('X-Crowd-CSRF', ''), app.token):
                return self.send({'ok': False, 'error': 'local_origin_required'}, 403)
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 32768 or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ValueError('invalid_request')
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError('invalid_request')
                if self.path == '/api/config':
                    return self.send(app.configure(body))
                if self.path == '/api/media':
                    path = app.media_file(body)
                    with path.open('rb') as stream:
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/octet-stream')
                        self.send_header('Content-Length', str(os.fstat(stream.fileno()).st_size))
                        self.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + quote(path.name))
                        self.send_header('Cache-Control', 'no-store')
                        self.send_header('X-Content-Type-Options', 'nosniff')
                        self.end_headers()
                        while True:
                            chunk = stream.read(1024 * 1024)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                    return
                if self.path != '/api/action' or set(body) != {'action', 'payload'}:
                    raise ValueError('invalid_request')
                return self.send(app.run(body['action'], body['payload']))
            except (ValueError, TypeError, OSError) as error:
                message = str(error)
                return self.send({'ok': False, 'error': message if message.replace('_', '').isalnum() else 'invalid_request'}, 400)

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.home() / 'Library/Application Support/CrowdCollector')
    parser.add_argument('--mc-root')
    parser.add_argument('--port', type=int, default=45937)
    parser.add_argument('--open', action='store_true')
    args = parser.parse_args()
    server = make_server(Application(args.root, args.mc_root), args.port)
    url = 'http://127.0.0.1:' + str(server.server_port)
    print('多平台采集工作台：' + url, flush=True)
    print('关闭此终端只关闭工作台；请先在页面停止仍在运行的采集任务。', flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
