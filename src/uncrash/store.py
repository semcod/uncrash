from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sqlite3
import stat
import subprocess
import pwd
import time
from urllib.parse import quote
import uuid
import zlib

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .inventory import process_inventory


class RecoveryError(ValueError):
    pass


def no_links(path):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        if item.is_symlink():
            raise RecoveryError('Symlinked state paths are not supported')
    return path


def private_dir(path):
    path = no_links(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    return path


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_file(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def excluded(name):
    lower = name.lower()
    return (lower in {'.ssh', '.gnupg', '.aws', '.azure', '.kube', 'keyrings',
        '.env', 'cookies', 'login data', 'web data', 'secrets.json', 'credentials',
        'credentials.json', '.credentials.json', 'auth.json', 'oauth.json', 'tokens.json',
        'antigravity-oauth-token', 'devtoolsactiveport'}
        or lower.startswith(('.env.', 'singleton')) or lower.endswith(('.pem', '.key', '.p12')))


def matches_path(relative, pattern):
    def match(parts, patterns):
        if not patterns: return not parts
        if patterns[0] == '**':
            return match(parts, patterns[1:]) or (bool(parts) and match(parts[1:], patterns))
        return bool(parts) and fnmatch.fnmatchcase(parts[0], patterns[0]) and match(parts[1:], patterns[1:])
    return match(Path(relative).parts, Path(pattern).parts)


def profiles(config):
    result = []
    seen = set()
    for item in config.get('profiles', []):
        name = item.get('id', '')
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', name) or name in seen:
            raise RecoveryError('Profile IDs must be unique lowercase identifiers')
        seen.add(name)
        path = no_links(item['state_dir'])
        if not Path(item['state_dir']).is_absolute() or path == Path('/') or path == Path.home():
            raise RecoveryError('Select a specific absolute app data directory, not HOME or /')
        argv = item.get('argv', [])
        if not isinstance(argv, list) or any(not isinstance(s, str) or '\x00' in s for s in argv):
            raise RecoveryError('App command must be an explicit argument list')
        databases = item.get('sqlite_backup_files', [])
        if (not isinstance(databases, list) or any(not isinstance(s, str) or not s or '\x00' in s
                or Path(s).is_absolute() or '..' in Path(s).parts or Path(s).as_posix() != s for s in databases)
                or len(set(databases)) != len(databases)):
            raise RecoveryError('SQLite backup files must be unique confined relative paths')
        for key in ['include_globs', 'sqlite_backup_globs']:
            patterns = item.get(key, [])
            if (not isinstance(patterns, list) or any(not isinstance(s, str) or not s or '\x00' in s
                    or Path(s).is_absolute() or '..' in Path(s).parts for s in patterns)):
                raise RecoveryError('Profile globs must be confined relative patterns')
        result.append({**item, 'state_dir': str(path), 'argv': argv})
    roots = [Path(p['state_dir']) for p in result]
    for index, left in enumerate(roots):
        for right in roots[index+1:]:
            if left == right or left in right.parents or right in left.parents:
                raise RecoveryError('Application state directories must not overlap')
    return result


def sqlite_snapshot(path, file_limit):
    """Online backup includes committed WAL data without writing plaintext temp files."""
    deadline = time.monotonic()+10
    source = destination = None
    try:
        source = sqlite3.connect('file:'+quote(str(no_links(path)), safe='/')+'?mode=ro', uri=True, timeout=1)
        page_size = source.execute('PRAGMA page_size').fetchone()[0]
        destination = sqlite3.connect(':memory:')
        def progress(status, remaining, total):
            if total*page_size > file_limit:
                raise RecoveryError('SQLite snapshot exceeds the file byte budget')
            if time.monotonic() >= deadline:
                raise RecoveryError('SQLite backup deadline exceeded; retry later')
        source.backup(destination, pages=128, progress=progress, sleep=.01)
        data = destination.serialize()
        if len(data) > file_limit:
            raise RecoveryError('SQLite snapshot exceeds the file byte budget')
        return data
    except sqlite3.Error as exc:
        raise RecoveryError('SQLite consistency backup failed; capture refused') from exc
    finally:
        if destination is not None: destination.close()
        if source is not None: source.close()


def build_native(root):
    source = Path(__file__).with_name('snapshot.rs')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    directory = private_dir(Path(root)/'native'/digest)
    binary = directory/'uncrash-snapshot'
    if binary.exists():
        info = binary.stat()
        if not binary.is_file() or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise RecoveryError('Rust worker must be a private owned executable')
        no_links(binary)
        return binary
    temporary = directory/('.build-'+uuid.uuid4().hex)
    try:
        compiler_env = {k: os.environ[k] for k in ['PATH', 'LANG', 'LC_ALL', 'RUSTUP_HOME', 'CARGO_HOME'] if k in os.environ}
        toolchain_home = Path(pwd.getpwuid(os.getuid()).pw_dir)/'.rustup'
        if 'RUSTUP_HOME' not in compiler_env and toolchain_home.is_dir(): compiler_env['RUSTUP_HOME'] = str(toolchain_home)
        try:
            result = subprocess.run(['rustc', '--edition=2021', '-O', str(source), '-o', str(temporary)],
                env=compiler_env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=120)
        except subprocess.TimeoutExpired as exc:
            raise RecoveryError('Rust worker build timed out') from exc
        if result.returncode:
            raise RecoveryError('Rust worker build failed; install rustc and OpenSSL/zlib development libraries')
        temporary.chmod(0o700)
        with temporary.open('rb') as stream: os.fsync(stream.fileno())
        os.replace(temporary, binary); sync_dir(directory)
    finally:
        if temporary.exists(): temporary.unlink()
    return binary


def rust_capture(root, jobs, config, key):
    if not jobs: return []
    binary = no_links(config['rust_binary']) if config.get('rust_binary') else build_native(root)
    workers = int(config.get('rust_threads', 4))
    if not 1 <= workers <= 16: raise RecoveryError('Rust threads must be between 1 and 16')
    header = str(workers)+'\t'+(key.hex() if key else '-')+'\t'+str(int(config.get('compress', False)))
    rows = [header]
    for job in jobs:
        old = job['old']
        rows.append('\t'.join([os.fsencode(job['source']).hex(), os.fsencode(job['destination']).hex(),
            str(job['limit']), job['aad'].hex(), os.fsencode(job['cache']).hex() if job['cache'] else '-',
            ','.join(map(str, old.get('source_signature', []))) or '-', old.get('sha256', '-'),
            str(old.get('blob_size', 0)), str(old.get('blob_mtime_ns', 0)), old.get('encoding', 'raw')]))
    try:
        result = subprocess.run([str(binary)], input=('\n'.join(rows)+'\n').encode(),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=600)
    except subprocess.TimeoutExpired as exc:
        raise RecoveryError('Rust snapshot worker timed out; previous complete snapshots retained') from exc
    if result.returncode:
        failed_index = len(result.stdout.splitlines())
        diagnostic = {'engine': 'rust', 'failed_index': failed_index, 'returncode': result.returncode,
            'source_sha256': hashlib.sha256(os.fsencode(jobs[failed_index]['source'])).hexdigest() if failed_index < len(jobs) else None}
        temporary = Path(root)/('.worker-error-'+uuid.uuid4().hex)
        write_file(temporary, json.dumps(diagnostic).encode())
        os.replace(temporary, Path(root)/'worker-error.json'); sync_dir(root)
        raise RecoveryError('Rust snapshot worker refused an unstable, unsafe or oversized file')
    records = [json.loads(line) for line in result.stdout.splitlines()]
    if len(records) != len(jobs) or [x['index'] for x in records] != list(range(len(jobs))):
        raise RecoveryError('Invalid Rust snapshot worker response')
    return records


def physical_bytes(paths):
    seen = set(); total = 0
    for path in paths:
        for file in path.iterdir():
            info = file.stat(follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode): raise RecoveryError('Snapshot contains an invalid storage entry')
            identity = (info.st_dev, info.st_ino)
            if identity not in seen: total += info.st_blocks*512; seen.add(identity)
    return total


class Store:
    def __init__(self, root, origin=None, *, encrypt=False):
        self.root = private_dir(root)
        self.snapshots = private_dir(self.root/'snapshots')
        self.origin = origin or socket.gethostname()
        self.encryption = encrypt

    @contextmanager
    def lock(self):
        fd = os.open(self.root/'lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def key(self):
        path = self.root/'key'
        if not path.exists():
            try:
                write_file(path, os.urandom(32))
                sync_dir(self.root)
            except FileExistsError:
                pass
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise RecoveryError('Snapshot key must be an owned regular file with mode 0600')
            key = stream.read(33)
        if len(key) != 32:
            raise RecoveryError('Invalid snapshot key')
        return key

    def aad(self, snapshot, label):
        return json.dumps(['uncrash.encrypted-snapshot/v1', self.origin, snapshot, label], separators=(',', ':')).encode()

    def encrypt(self, cipher, snapshot, label, data):
        nonce = os.urandom(12)
        return nonce+cipher.encrypt(nonce, data, self.aad(snapshot, label))

    def decrypt(self, cipher, snapshot, label, data):
        if cipher is None: return data
        try:
            return cipher.decrypt(data[:12], data[12:], self.aad(snapshot, label))
        except Exception as exc:
            raise RecoveryError('Snapshot authentication failed; restore refused') from exc

    def list(self):
        return sorted(p.name for p in self.snapshots.iterdir() if p.is_dir() and not p.name.startswith('.') and ((p/'manifest.enc').is_file() or ((p/'manifest.json').is_file() and (p/'manifest.sha256').is_file())))

    def capture(self, config):
        started = time.monotonic()
        selected = profiles(config)
        encryption = config.get('encrypt', False)
        engine = config.get('snapshot_engine', 'rust')
        if not isinstance(encryption, bool) or engine not in ['rust', 'python']:
            raise RecoveryError('Select boolean encryption and rust/python snapshot engine')
        self.encryption = encryption
        for item in selected:
            source = Path(item['state_dir'])
            if source == self.root or source in self.root.parents or self.root in source.parents:
                raise RecoveryError('Snapshot store and application data must not overlap')
        limit = int(config.get('max_bytes', 512*1024*1024))
        file_limit = int(config.get('max_file_bytes', 64*1024*1024))
        keep = int(config.get('retention', 288))
        disk_limit = int(config.get('max_total_bytes', 4*1024*1024*1024))
        compress = config.get('compress', False)
        if not isinstance(compress, bool):
            raise RecoveryError('Compression must be explicitly true or false')
        if limit <= 0 or file_limit <= 0 or disk_limit <= 0 or not 1 <= keep <= 10000:
            raise RecoveryError('Invalid snapshot bounds')
        with self.lock():
            key = self.key() if encryption else None
            cipher = AESGCM(key) if key else None
            old_files = {}; previous_path = None
            if not encryption and self.list():
                try:
                    _, previous_path, previous_cipher, previous = self.load('latest')
                    if previous_cipher is None and previous.get('compress', False) == compress:
                        old_files = {(a['id'], f['path']): f for a in previous['profiles'] for f in a['files']
                            if re.fullmatch(r'[a-f0-9]{64}\.blob', str(f.get('blob', '')))}
                except (RecoveryError, OSError, ValueError): pass
            jobs = []
            sid = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')+'-'+uuid.uuid4().hex[:12]
            stage = private_dir(self.snapshots/('.pending-'+sid))
            manifest = {'schema': 'uncrash.snapshot/v1', 'id': sid, 'origin': self.origin,
                'created_at': datetime.now(timezone.utc).isoformat(), 'profiles': [],
                'encryption': 'aes-256-gcm' if encryption else 'none', 'compress': compress, 'snapshot_engine': engine,
                'processes': process_inventory(), 'fidelity': 'durable-files-and-configured-relaunch; no RAM or live PTY'}
            if config.get('jetbrains_metadata', False):
                from .recovery import jetbrains_state
                manifest['jetbrains'] = jetbrains_state()
                from .diagnostics import session_hosts
                manifest['session_hosts'] = session_hosts()
            total = 0
            try:
                for app in selected:
                    source = Path(app['state_dir'])
                    if not source.is_dir():
                        raise RecoveryError('Application state directory is missing')
                    files, directories, skipped = [], [], 0
                    databases = set(app.get('sqlite_backup_files', []))
                    captured_databases = set()
                    for directory, dirs, names in os.walk(source, followlinks=False):
                        base = Path(directory)
                        for name in list(dirs):
                            includes = app.get('include_globs', [])
                            rel_dir = (base/name).relative_to(source)
                            def could_include(pattern):
                                if len(Path(pattern).parts) == 1 and pattern != '**': return False
                                prefix = []
                                for part in Path(pattern).parts:
                                    if any(c in part for c in '*?['): break
                                    prefix.append(part)
                                if not prefix: return True
                                target = Path(*prefix)
                                return rel_dir == target or rel_dir in target.parents or target in rel_dir.parents
                            if includes and not any(could_include(p) for p in includes):
                                dirs.remove(name); skipped += 1
                            elif excluded(name):
                                dirs.remove(name); skipped += 1
                            elif (base/name).is_symlink():
                                raise RecoveryError('Application data contains a symlink; capture refused')
                            else:
                                directories.append((base/name).relative_to(source).as_posix())
                        for name in sorted(names):
                            rel = (base/name).relative_to(source).as_posix()
                            includes = app.get('include_globs', [])
                            if includes and not any(matches_path(rel, pattern) for pattern in includes):
                                skipped += 1; continue
                            sqlite_globs = app.get('sqlite_backup_globs', [])
                            is_sqlite = rel in databases or any(matches_path(rel, pattern) for pattern in sqlite_globs)
                            sidecar_database = next((rel[:-len(s)] for s in ('-wal', '-shm', '-journal') if rel.endswith(s)), None)
                            if sidecar_database and (sidecar_database in databases or any(matches_path(sidecar_database, p) for p in sqlite_globs)):
                                skipped += 1; continue
                            if excluded(name):
                                skipped += 1; continue
                            path = base/name
                            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                            with os.fdopen(fd, 'rb') as stream:
                                before = os.fstat(stream.fileno())
                                if not stat.S_ISREG(before.st_mode) or before.st_size > file_limit:
                                    raise RecoveryError('Only bounded regular app data files can be captured')
                                if not is_sqlite and engine == 'rust':
                                    label = app['id']+'/'+rel
                                    blob = hashlib.sha256(label.encode()).hexdigest()+('.enc' if encryption else '.blob')
                                    record = {'path': rel, 'blob': blob, 'size': before.st_size, 'capture_method': 'stable-file-read'}
                                    files.append(record)
                                    old = old_files.get((app['id'], rel), {})
                                    cached = previous_path/old['blob'] if previous_path and old.get('blob') else None
                                    jobs.append({'source': path, 'destination': stage/blob, 'limit': file_limit,
                                        'aad': self.aad(sid, label), 'old': old, 'cache': cached, 'record': record})
                                    total += before.st_size
                                    if total > limit: raise RecoveryError('Snapshot byte budget exceeded')
                                    continue
                                if is_sqlite:
                                    if stream.read(16) != b'SQLite format 3\x00':
                                        raise RecoveryError('Configured SQLite file is not a SQLite database')
                                    data = sqlite_snapshot(path, file_limit)
                                    if rel in databases: captured_databases.add(rel)
                                else:
                                    data = stream.read(file_limit+1)
                                after = os.fstat(stream.fileno())
                            current = path.stat(follow_symlinks=False)
                            signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
                            if is_sqlite:
                                if (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino):
                                    raise RecoveryError('SQLite file was replaced while captured; retry later')
                            elif signature(before) != signature(after) or signature(before) != signature(current) or len(data) != before.st_size:
                                raise RecoveryError('Application file changed while being captured; retry later')
                            total += len(data)
                            if total > limit:
                                raise RecoveryError('Snapshot byte budget exceeded')
                            label = app['id']+'/'+rel
                            blob = hashlib.sha256(label.encode()).hexdigest()+('.enc' if encryption else '.blob')
                            digest = hashlib.sha256(data).hexdigest()
                            old = old_files.get((app['id'], rel), {})
                            cached = no_links(previous_path/old['blob']) if previous_path and old.get('blob') else None
                            reused = False
                            if cached and old.get('sha256') == digest and cached.is_file():
                                info = cached.stat()
                                if info.st_size == old.get('blob_size') and info.st_mtime_ns == old.get('blob_mtime_ns'):
                                    os.link(cached, stage/blob, follow_symlinks=False)
                                    encoding = old.get('encoding', 'raw'); reused = True
                            if not reused:
                                encoded = zlib.compress(data, level=1) if compress else data
                                encoding = 'zlib' if compress and len(encoded) < len(data) else 'raw'
                                if encoding == 'raw': encoded = data
                                write_file(stage/blob, self.encrypt(cipher, sid, label, encoded) if cipher else encoded)
                            info = (stage/blob).stat()
                            files.append({'path': rel, 'blob': blob, 'size': len(data), 'sha256': digest,
                                'executable': bool(before.st_mode & stat.S_IXUSR),
                                'capture_method': 'sqlite-online-backup' if is_sqlite else 'stable-file-read', 'encoding': encoding,
                                'copy_method': 'cached-hardlink' if reused else 'python-write',
                                'blob_size': info.st_size, 'blob_mtime_ns': info.st_mtime_ns})
                    if captured_databases != databases:
                        raise RecoveryError('A configured SQLite backup file is missing or excluded')
                    manifest['profiles'].append({'id': app['id'], 'files': files, 'directories': directories, 'excluded_entries': skipped})
                for job, result in zip(jobs, rust_capture(self.root, jobs, config, key)):
                    result.pop('index'); job['record'].update(result)
                total = sum(f['size'] for app in manifest['profiles'] for f in app['files'])
                if total > limit:
                    raise RecoveryError('Snapshot byte budget exceeded after stable Rust reads')
                manifest_data = json.dumps(manifest).encode()
                if cipher:
                    write_file(stage/'manifest.enc', self.encrypt(cipher, sid, 'manifest', manifest_data))
                else:
                    write_file(stage/'manifest.json', manifest_data)
                    write_file(stage/'manifest.sha256', hashlib.sha256(manifest_data).hexdigest().encode())
                newest_size = physical_bytes([stage])
                if newest_size > disk_limit:
                    raise RecoveryError('Encrypted snapshot exceeds the total storage budget')
                sync_dir(stage)
                os.replace(stage, self.snapshots/sid); sync_dir(self.snapshots)
                retained = self.list()
                for old in retained[:-keep]:
                    shutil.rmtree(self.snapshots/old)
                retained = self.list()
                while len(retained) > 1 and physical_bytes([self.snapshots/name for name in retained]) > disk_limit:
                    shutil.rmtree(self.snapshots/retained.pop(0))
                sync_dir(self.snapshots)
                return {'snapshot': sid, 'bytes': total, 'profiles': len(selected), 'engine': engine,
                    'encryption': manifest['encryption'], 'duration_seconds': round(time.monotonic()-started, 3),
                    'reused_files': sum(f.get('copy_method') == 'cached-hardlink' for a in manifest['profiles'] for f in a['files']),
                    'physical_bytes': physical_bytes([self.snapshots/name for name in retained])}
            except BaseException:
                shutil.rmtree(stage, ignore_errors=True)
                raise

    def load(self, sid):
        if sid == 'latest':
            choices = self.list()
            if not choices:
                raise RecoveryError('No complete snapshot is available')
            sid = choices[-1]
        if not re.fullmatch(r'\d{8}T\d{12}-[a-f0-9]{12}', sid):
            raise RecoveryError('Invalid snapshot ID')
        path = no_links(self.snapshots/sid)
        if (path/'manifest.enc').is_file():
            cipher = AESGCM(self.key())
            manifest = json.loads(self.decrypt(cipher, sid, 'manifest', (path/'manifest.enc').read_bytes()))
        else:
            cipher = None
            data = no_links(path/'manifest.json').read_bytes()
            if hashlib.sha256(data).hexdigest().encode() != no_links(path/'manifest.sha256').read_bytes():
                raise RecoveryError('Plain snapshot manifest checksum mismatch')
            manifest = json.loads(data)
            if manifest.get('encryption') != 'none': raise RecoveryError('Invalid plain snapshot encryption marker')
        if manifest.get('id') != sid or manifest.get('origin') != self.origin or manifest.get('schema') != 'uncrash.snapshot/v1':
            raise RecoveryError('Snapshot identity mismatch')
        return sid, path, cipher, manifest

    def restore(self, sid, config, destination, *, replace=False):
        selected = {p['id']: p for p in profiles(config)}
        destination = no_links(destination)
        if destination == self.root or destination in self.root.parents or self.root in destination.parents:
            raise RecoveryError('Restore destination overlaps snapshot storage')
        with self.lock():
            sid, path, cipher, manifest = self.load(sid)
            # Authenticate every byte before changing even the first target.
            file_limit = int(config.get('max_file_bytes', 64*1024*1024))
            total_limit = int(config.get('max_bytes', 512*1024*1024))
            total = 0
            def decode(app, item):
                if not isinstance(item['size'], int) or not 0 <= item['size'] <= file_limit:
                    raise RecoveryError('Restore file byte budget exceeded')
                blob = no_links(path/item['blob'])
                if blob.stat().st_size > file_limit+28:
                    raise RecoveryError('Encrypted restore file byte budget exceeded')
                data = self.decrypt(cipher, sid, app['id']+'/'+item['path'], blob.read_bytes())
                encoding = item.get('encoding', 'raw')
                if encoding == 'zlib':
                    try:
                        inflater = zlib.decompressobj()
                        data = inflater.decompress(data, item['size']+1)
                        if not inflater.eof or inflater.unused_data or inflater.unconsumed_tail:
                            raise RecoveryError('Invalid or oversized compressed snapshot file')
                    except zlib.error as exc:
                        raise RecoveryError('Compressed snapshot authentication failed') from exc
                elif encoding != 'raw':
                    raise RecoveryError('Unknown snapshot file encoding')
                if len(data) != item['size'] or hashlib.sha256(data).hexdigest() != item['sha256']:
                    raise RecoveryError('Snapshot content digest mismatch')
                return data
            for app in manifest['profiles']:
                if app['id'] not in selected:
                    raise RecoveryError('Snapshot application is not registered in current configuration')
                for directory in app.get('directories', []):
                    if Path(directory).is_absolute() or '..' in Path(directory).parts:
                        raise RecoveryError('Invalid snapshot directory')
                for item in app['files']:
                    rel = Path(item['path'])
                    if rel.is_absolute() or '..' in rel.parts or not rel.parts or not re.fullmatch(r'[a-f0-9]{64}'+(r'\.enc' if cipher else r'\.blob'), item['blob']):
                        raise RecoveryError('Invalid snapshot file path')
                    total += item['size']
                    if total > total_limit:
                        raise RecoveryError('Restore snapshot byte budget exceeded')
                    # Two authenticated passes bound memory to individual files.
                    decode(app, item)
            private_dir(destination)
            for app in manifest['profiles']:
                target = no_links(destination/app['id'])
                if target.exists() and not replace:
                    raise RecoveryError('Restore target already exists; select a new destination or explicitly replace')
                if target.is_file():
                    raise RecoveryError('Restore target must be a directory')
            receipt = {'schema': 'uncrash.restore-receipt/v1', 'snapshot': sid, 'restored': [], 'pre_restore': [], 'fidelity': manifest['fidelity']}
            try:
                for app in manifest['profiles']:
                    target = destination/app['id']
                    stage = private_dir(destination/('.restore-'+uuid.uuid4().hex))
                    try:
                        for directory in app.get('directories', []):
                            private_dir(stage/directory)
                        for item in app['files']:
                            output = stage/item['path']; private_dir(output.parent)
                            write_file(output, decode(app, item))
                            if item.get('executable'):
                                os.chmod(output, 0o700)
                        for directory, _, _ in os.walk(stage, topdown=False):
                            sync_dir(directory)
                        if target.exists():
                            previous = destination/(app['id']+'.pre-uncrash-'+uuid.uuid4().hex[:12])
                            os.replace(target, previous); sync_dir(destination)
                            receipt['pre_restore'].append(str(previous))
                        os.replace(stage, target); sync_dir(destination)
                        receipt['restored'].append({'id': app['id'], 'state_dir': str(target), 'files': len(app['files'])})
                    finally:
                        if stage.exists():
                            shutil.rmtree(stage)
            finally:
                receipt['completed'] = len(receipt['restored']) == len(manifest['profiles'])
                self.receipt(receipt)
            return receipt

    def receipt(self, receipt):
        directory = private_dir(self.root/'receipts')
        path = directory/(uuid.uuid4().hex+('.enc' if self.encryption else '.json'))
        data = json.dumps(receipt).encode()
        write_file(path, self.encrypt(AESGCM(self.key()), path.stem, 'receipt', data) if self.encryption else data)
        for old in sorted(directory.iterdir(), key=lambda p: p.stat().st_mtime_ns)[:-1000]:
            old.unlink()
        sync_dir(directory)
