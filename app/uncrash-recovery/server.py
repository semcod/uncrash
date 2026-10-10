"""Loopback APX adapter. Own no engines, projects, credentials or remote policy."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import stat
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlsplit
import uuid

from logger import record

ROOT = Path(__file__).resolve().parent
MAX_BUNDLE = 128 * 1024 * 1024
OPERATIONS = [
    {'method': 'GET', 'path': '/health', 'kind': 'query'},
    {'method': 'GET', 'path': '/api/registry', 'kind': 'query'},
    {'method': 'GET', 'path': '/api/sessions', 'kind': 'query'},
    {'method': 'GET', 'path': '/api/backend', 'kind': 'query'},
    {'method': 'POST', 'path': '/api/transfer/plan', 'kind': 'command'},
    {'method': 'POST', 'path': '/api/transfer/apply', 'kind': 'command'},
]


class Rejected(ValueError):
    pass


def loopback_url(value):
    u = urlsplit(value)
    if (u.scheme != 'http' or u.hostname != '127.0.0.1' or u.username or
            u.password or not u.port or u.fragment):
        raise Rejected('Only a configured loopback HTTP endpoint is supported')
    return value


def confined_path(value):
    p = Path(value).expanduser().absolute()
    if any(part.is_symlink() for part in (p, *p.parents)):
        raise Rejected('Symlinks are not supported')
    return p


def private_file(path):
    path = confined_path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        s = os.fstat(fd)
        if (not stat.S_ISREG(s.st_mode) or s.st_uid != os.getuid() or
                s.st_mode & 0o077 or s.st_size > MAX_BUNDLE):
            raise Rejected('Select a private owned regular bundle below 128 MiB')
        return os.fdopen(fd, 'rb')
    except BaseException:
        os.close(fd)
        raise


def signature(s):
    return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns


def file_digest(stream, destination=None):
    before = signature(os.fstat(stream.fileno()))
    h = hashlib.sha256()
    total = 0
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        total += len(chunk)
        if total > MAX_BUNDLE:
            raise Rejected('Bundle grew beyond the transfer limit')
        h.update(chunk)
        if destination is not None:
            destination.write(chunk)
    if before != signature(os.fstat(stream.fileno())):
        raise Rejected('Bundle changed during verification')
    return h.hexdigest(), total, before


def transfer_cli(command, bundle, host):
    result = subprocess.run(
        [*command, 'bundle-transfer', str(bundle), '--host', host, '--timeout', '15'],
        capture_output=True, timeout=30, check=False, text=True,
    )
    if result.returncode:
        raise Rejected('Backend transfer failed; obtain a fresh plan before retrying')
    try:
        receipt = json.loads(result.stdout)
    except ValueError:
        raise Rejected('Backend did not return a transfer receipt') from None
    return receipt


@dataclass(frozen=True)
class Config:
    state: Path
    sessions: Path | None = None
    bundle: Path | None = None
    host: str = 'tom@minis'
    backend: str = 'http://127.0.0.1:18891/'
    command: tuple = ('uncrash',)


class RecoveryInterface:
    def __init__(self, config, *, runner=transfer_cli, clock=time.monotonic, audit=record):
        self.config, self.runner, self.clock, self.audit = config, runner, clock, audit
        self.lock = threading.Lock()
        self.plans = {}
        loopback_url(config.backend)
        import re
        if not re.fullmatch(r'[a-zA-Z0-9_.-]+@[a-zA-Z0-9][a-zA-Z0-9_.-]*', config.host):
            raise Rejected('Configure one explicit SSH host')
        state = confined_path(config.state)
        state.mkdir(mode=0o700, parents=True, exist_ok=True)
        s = state.stat()
        if s.st_uid != os.getuid() or s.st_mode & 0o077:
            raise Rejected('Runtime directory must be private and owned')

    def sessions(self):
        if self.config.sessions is None:
            return {'sessions': []}
        with private_file(self.config.sessions) as stream:
            data = stream.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise Rejected('Session inventory is too large')
        rows = json.loads(data)
        if not isinstance(rows, list) or len(rows) > 32:
            raise Rejected('Invalid session inventory')
        sessions = []
        for row in rows:
            sid = str(uuid.UUID(row['conversation_id']))
            url = loopback_url(row['novnc_url'])
            u = urlsplit(url)
            try:
                with socket.create_connection((u.hostname, u.port), timeout=0.2):
                    alive = True
            except OSError:
                alive = False
            sessions.append({'id': sid, 'name': Path(row.get('cwd', '')).name or 'Sesja',
                             'url': url, 'status': 'active' if alive else 'stopped',
                             'fidelity': row.get('fidelity', 'persisted conversation'),
                             'mode': row.get('mode', 'unknown')})
        return {'sessions': sessions}

    def plan(self):
        if self.config.bundle is None:
            raise Rejected('No recovery bundle is configured')
        with private_file(self.config.bundle) as source:
            sha, size, identity = file_digest(source)
        now = self.clock()
        token = secrets.token_urlsafe(32)
        p = {'token': token, 'name': Path(self.config.bundle).name, 'sha256': sha,
             'bytes': size, 'host': self.config.host,
             'expiresAt': (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat(),
             'requiresConfirmation': True, 'dataTransferred': False}
        with self.lock:
            self.plans = {k: v for k, v in self.plans.items() if v['deadline'] > now}
            if len(self.plans) >= 32:
                raise Rejected('Too many pending plans')
            self.plans[token] = {'deadline': now + 120, 'identity': identity, 'plan': p}
        return p

    def apply(self, token):
        if not isinstance(token, str) or not 1 <= len(token) <= 100:
            raise Rejected('Invalid confirmation token')
        with self.lock:
            pending = self.plans.pop(token, None)
        if not pending or pending['deadline'] <= self.clock():
            raise Rejected('Confirmation expired or already used; prepare a new plan')
        plan = pending['plan']
        staged = None
        try:
            with private_file(self.config.bundle) as source:
                if signature(os.fstat(source.fileno())) != pending['identity']:
                    raise Rejected('Bundle changed after planning')
                fd, name = tempfile.mkstemp(prefix='transfer-', suffix='.tar', dir=self.config.state)
                staged = Path(name)
                with os.fdopen(fd, 'wb') as target:
                    sha, size, _ = file_digest(source, target)
                    target.flush()
                    os.fsync(target.fileno())
                if sha != plan['sha256'] or size != plan['bytes']:
                    raise Rejected('Bundle changed after planning')
            self.audit(self.config.state, 'ACCEPTED', sha)
            receipt = self.runner(self.config.command, staged, self.config.host)
            # The backend receipt is bound to the exact uploaded bytes and host.
            if (not isinstance(receipt, dict) or receipt.get('sha256') != sha or receipt.get('host') != self.config.host or
                    receipt.get('bytes') != size or receipt.get('apps_launched') is not False):
                raise Rejected('Backend receipt does not match the confirmed transfer')
            rid = uuid.uuid4().hex
            raw = json.dumps(receipt, ensure_ascii=False, sort_keys=True).encode()
            fd = os.open(self.config.state / (rid + '.receipt.json'), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as f:
                f.write(raw)
                f.flush()
                os.fsync(f.fileno())
            self.audit(self.config.state, 'SUCCEEDED', sha, 'receipt:uncrash-transfer/' + rid)
            return {'transferred': True, 'sha256': sha, 'host': self.config.host,
                    'receipt': receipt, 'applicationsLaunched': False}
        finally:
            if staged is not None:
                staged.unlink(missing_ok=True)


def handler_for(interface):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, *_):
            pass

        def valid_host(self):
            return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'

        def send(self, status, value, content_type='application/json'):
            data = json.dumps(value, ensure_ascii=False).encode() if content_type == 'application/json' else value
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self.valid_host():
                return self.send(403, {'error': 'Unrecognized host'})
            path = urlsplit(self.path).path
            try:
                if path == '/health':
                    return self.send(200, {'status': 'ok', 'app': 'uncrash-recovery'})
                if path == '/api/registry':
                    return self.send(200, {'operations': OPERATIONS})
                if path == '/api/sessions':
                    return self.send(200, interface.sessions())
                if path == '/api/backend':
                    return self.send(200, {'url': interface.config.backend})
                if path == '/':
                    return self.send(200, (ROOT / 'web/index.html').read_bytes(), 'text/html; charset=utf-8')
                return self.send(404, {'error': 'Unknown route'})
            except (OSError, ValueError, KeyError, TypeError):
                return self.send(409, {'error': 'Recovery data is unavailable or invalid'})

        def do_POST(self):
            expected = f'http://127.0.0.1:{self.server.server_port}'
            if (not self.valid_host() or self.headers.get('Origin') != expected or
                    self.headers.get('Content-Type') != 'application/json'):
                return self.send(403, {'error': 'Use the local recovery interface'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 4096 or self.headers.get('Transfer-Encoding'):
                    raise Rejected('Invalid request size')
                body = json.loads(self.rfile.read(length))
                path = urlsplit(self.path).path
                if path == '/api/transfer/plan' and body == {}:
                    return self.send(200, interface.plan())
                if path == '/api/transfer/apply' and isinstance(body, dict) and set(body) == {'token'}:
                    return self.send(200, interface.apply(body['token']))
                return self.send(404, {'error': 'Unknown action or parameters'})
            except Rejected as exc:
                return self.send(409, {'error': str(exc)})
            except (OSError, ValueError, subprocess.TimeoutExpired):
                return self.send(409, {'error': 'Transfer failed; inspect the receipt before retrying'})
    return Handler


def main():
    # ssot.yaml is JSON (a YAML subset); the native server needs no YAML runtime.
    ssot = json.loads((ROOT / 'ssot.yaml').read_text())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=ssot['network']['default_port'])
    parser.add_argument('--state', type=Path, default=Path.home() / '.local/state/uncrash-apx')
    parser.add_argument('--sessions-file', type=Path)
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--host', default='tom@minis', help='Configured SSH destination, not the HTTP bind')
    parser.add_argument('--backend', default=ssot['backend'])
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Select a non-privileged port')
    command = shutil.which('uncrash')
    if not command:
        parser.error('Install Uncrash before starting this adapter')
    cfg = Config(args.state, args.sessions_file, args.bundle, args.host, args.backend, (command,))
    interface = RecoveryInterface(cfg)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler_for(interface))
    server.daemon_threads = True
    pid_dir = confined_path(args.state / '.apx/pids')
    pid_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    pid = pid_dir / 'uncrash-recovery.pid'
    fd = os.open(pid, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(str(os.getpid()))
    print(f'Uncrash APX: http://127.0.0.1:{args.port}/', flush=True)
    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        pid.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
