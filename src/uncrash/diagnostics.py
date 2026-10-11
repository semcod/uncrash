"""Read-only terminal provenance and backup health; never read a PTY or chat body."""
from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import time
from urllib.parse import quote

from .store import RecoveryError, find_native_worker, no_links, write_file


PROVIDERS = {'codex', 'claude', 'agy'}
HOSTS = {'gnome-terminal-server': 'GNOME Terminal', 'gnome-terminal-': 'GNOME Terminal',
         'konsole': 'Konsole', 'xterm': 'xterm', 'kitty': 'Kitty', 'alacritty': 'Alacritty',
         'wezterm-gui': 'WezTerm', 'code': 'VS Code', 'code-insiders': 'VS Code Insiders',
         'pycharm': 'PyCharm', 'idea': 'IntelliJ IDEA', 'webstorm': 'WebStorm',
         'goland': 'GoLand', 'clion': 'CLion', 'rider': 'Rider'}


def _stat(path):
    fields = (path / 'stat').read_text().rsplit(')', 1)[1].split()
    return {'pid': int(path.name), 'ppid': int(fields[1]), 'start_ticks': fields[19],
            'session_id': int(fields[3]), 'tty_nr': int(fields[4])}


def _read_regular_bytes(path, maximum):
    fd = os.open(no_links(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('metadata is not a regular file')
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError('metadata limit exceeded')
    return raw


def _read_json(path, maximum=32 * 1024**2):
    raw = _read_regular_bytes(path, maximum)
    return json.loads(raw), raw


def native_session_hosts(proc_root: Path = Path('/proc'), state_root: Path = None) -> dict | None:
    """Attempt fast native Rust scan of /proc session hosts; returns None if native worker is unavailable."""
    try:
        proc_root = no_links(proc_root)
    except (OSError, RecoveryError):
        return None
    binary = find_native_worker(state_root)
    if binary is None:
        return None
    try:
        proc = subprocess.run(
            [str(binary), '--session-hosts', str(proc_root)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0:
            data = json.loads(proc.stdout.strip() or '{}')
            if isinstance(data, dict) and data.get('schema') == 'uncrash.session-hosts/v1':
                data['observed_at'] = datetime.now(timezone.utc).isoformat()
                return data
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError):
        pass
    return None


def session_hosts(proc_root=Path('/proc'), state_root=None):
    """Observe PID/start identity twice; source labels never determine the host."""
    proc_root = Path(proc_root)
    native_data = native_session_hosts(proc_root, state_root=state_root)
    if native_data is not None:
        return native_data
    now = datetime.now(timezone.utc).isoformat()
    try:
        boot = (proc_root / 'sys/kernel/random/boot_id').read_text().strip()
    except OSError:
        boot = None
    nodes = {}; rejected = Counter()
    for path in proc_root.iterdir():
        if not path.name.isdecimal():
            continue
        try:
            if path.stat().st_uid != os.getuid():
                continue
            before = _stat(path)
            name = (path / 'comm').read_text().strip()
            exe = os.readlink(path / 'exe')
            basename = Path(exe).name
            provider = basename if basename in PROVIDERS else None
            role = 'unknown'
            # Only recognize bounded executable arguments; never retain prompt arguments.
            if provider or basename in {'node', 'nodejs', 'java'}:
                with (path / 'cmdline').open('rb') as stream:
                    args = stream.read(65536).split(b'\0')
                if basename in {'node', 'nodejs'} and len(args) > 1:
                    entry = args[1].decode(errors='replace')
                    if '/@anthropic-ai/claude-code/' in entry: provider = 'claude'
                    if '/@openai/codex/' in entry: provider = 'codex'
                if b'app-server' in args[1:3]: role = 'server'
                elif b'exec' in args[1:3]: role = 'automation'
                if basename == 'java':
                    selectors = [a for a in args if a.startswith(b'-Didea.paths.selector=')]
                    for token, label in HOSTS.items():
                        if any(token.encode() in a.lower() for a in selectors): basename = token; break
            node = {**before, 'name': name, 'executable': exe, 'provider': provider,
                    'host_app': HOSTS.get(basename) or HOSTS.get(name), 'role': role}
            if provider:
                node['cwd'] = os.readlink(path / 'cwd')
                stdin = os.readlink(path / 'fd/0')
                node['terminal'] = stdin if stdin.startswith('/dev/pts/') else None
                if node['terminal'] and node['role'] == 'unknown': node['role'] = 'client'
                node['pid_namespace'] = os.readlink(path / 'ns/pid')
                node['inherited_markers'] = {}
                with (path / 'environ').open('rb') as stream:
                    fields = stream.read(262144).split(b'\0')
                for field in fields:
                    k, sep, v = field.partition(b'=')
                    if sep and k in {b'TERMINAL_EMULATOR', b'TERM_SESSION_ID'}:
                        node['inherited_markers'][k.decode()] = v[:256].decode(errors='replace')
            if before != _stat(path):
                rejected['identity_changed'] += 1; continue
            nodes[before['pid']] = node
        except (OSError, ValueError, IndexError):
            rejected['unavailable'] += 1
    rows = []
    for pid in sorted(nodes):
        node = nodes[pid]
        if not node['provider']: continue
        chain = []; seen = {pid}; cursor = node['ppid']; host = None; stable = True
        while cursor in nodes and cursor not in seen:
            seen.add(cursor); parent = nodes[cursor]
            chain.append({k: parent[k] for k in ('pid', 'ppid', 'start_ticks', 'name', 'host_app')})
            if int(parent['start_ticks']) > int(node['start_ticks']): stable = False
            if host is None and parent['host_app']: host = parent['host_app']
            cursor = parent['ppid']
        # Recheck the whole observed chain after metadata collection.
        for member in [node, *chain]:
            try:
                current = _stat(proc_root / str(member['pid']))
                if any(current[k] != member[k] for k in ('pid', 'ppid', 'start_ticks')): stable = False
            except (OSError, ValueError, IndexError): stable = False
        if not stable: host = None
        rows.append({k: v for k, v in node.items() if k != 'host_app'} | {
            'current_host': host or 'unknown', 'ancestry_stable': stable, 'ancestors': chain,
            'host_evidence': 'process-ancestry' if host else 'unresolved',
            'conversation_id': None, 'conversation_binding': 'unresolved',
            'launch_host_inference': 'JetBrains' if node['inherited_markers'].get('TERMINAL_EMULATOR') == 'JetBrains-JediTerm' else None})
    return {'schema': 'uncrash.session-hosts/v1', 'observed_at': now, 'boot_id': boot,
            'processes': rows, 'rejected_observations': dict(rejected),
            'limitations': ['Process ancestry describes observed containment, not a window or tab ID.',
                'Shared servers and inherited markers do not bind conversations to interactive clients.',
                'Reparented, multiplexed, remote or container clients can remain unresolved.']}


def check_sqlite_integrity(path: Path) -> tuple[str, str | None]:
    """Bound a read-only integrity check; inaccessible does not mean corrupted."""
    connection = None
    try:
        path = no_links(path)
        if not path.exists():
            return 'missing', f'File does not exist: {path}'
        if not path.is_file():
            return 'unavailable', 'SQLite input is not a regular file'
        deadline = time.monotonic() + 1.0
        connection = sqlite3.connect('file:' + quote(str(path), safe='/') + '?mode=ro', uri=True, timeout=0.2)
        connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        rows = connection.execute('PRAGMA quick_check(20)').fetchall()
        if rows != [('ok',)]:
            msg = rows[0][0] if rows else 'empty result'
            return 'corrupted', f'quick_check failed: {msg}'
        return 'ok', None
    except sqlite3.Error as exc:
        code = getattr(exc, 'sqlite_errorcode', 0) & 0xff
        status = 'corrupted' if code in {sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB} else 'unavailable'
        return status, str(exc)
    except (OSError, RecoveryError) as exc:
        return 'unavailable', str(exc)
    finally:
        if connection is not None:
            connection.close()


def check_sqlite_integrity_batch(paths: list[Path], max_workers: int = 8) -> list[tuple[Path, str, str | None]]:
    """Check integrity of multiple SQLite databases concurrently while preserving input order."""
    if not paths:
        return []
    if len(paths) == 1 or max_workers <= 1:
        return [(p, *check_sqlite_integrity(p)) for p in paths]

    workers = min(max_workers, len(paths))

    def _worker(p: Path) -> tuple[Path, str, str | None]:
        try:
            status, err = check_sqlite_integrity(p)
            return p, status, err
        except Exception as exc:
            return p, 'unavailable', str(exc)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(_worker, paths))


def native_scan_agent_log_panics(log_dir: Path, max_files: int = 20, state_root: Path = None) -> list[dict] | None:
    """Attempt fast native Rust scan of agent logs; returns None if native worker is unavailable."""
    if not isinstance(max_files, int) or not 1 <= max_files <= 100:
        raise ValueError('Log file budget must be between 1 and 100')
    try:
        log_dir = no_links(log_dir)
    except (OSError, RecoveryError):
        return []
    binary = find_native_worker(state_root)
    if binary is None:
        return None
    try:
        proc = subprocess.run(
            [str(binary), '--scan-panics', str(log_dir), str(max_files)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0:
            data = json.loads(proc.stdout.strip() or '[]')
            if isinstance(data, list):
                return data
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError):
        pass
    return None


def scan_agent_log_panics(log_dir: Path, max_files: int = 20, state_root: Path = None) -> list[dict]:
    """Scan recent agent log files for unhandled panic/crash signatures."""
    if not isinstance(max_files, int) or not 1 <= max_files <= 100:
        raise ValueError('Log file budget must be between 1 and 100')
    native_result = native_scan_agent_log_panics(log_dir, max_files, state_root)
    if native_result is not None:
        return native_result
    try:
        log_dir = no_links(log_dir)
        candidates = []
        for path in log_dir.glob('*.log'):
            try:
                info = no_links(path).stat()
                if stat.S_ISREG(info.st_mode):
                    candidates.append((info.st_mtime_ns, path))
            except (OSError, RecoveryError):
                continue
    except (OSError, RecoveryError):
        return []
    panics = []
    log_files = [path for _, path in sorted(candidates, reverse=True)[:max_files]]
    panic_patterns = [
        re.compile(r'Caught panic:\s*(.*)', re.IGNORECASE),
        re.compile(r'runtime error:\s*(invalid memory address or nil pointer dereference.*)', re.IGNORECASE),
        re.compile(r'Failed to load conversation ([a-f0-9-]+):\s*(.*database disk image is malformed.*)', re.IGNORECASE),
        re.compile(r'program was killed:\s*(program experienced a panic.*)', re.IGNORECASE),
    ]
    for log_path in log_files:
        try:
            fd = os.open(no_links(log_path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, 'rb') as f:
                info = os.fstat(f.fileno())
                if not stat.S_ISREG(info.st_mode):
                    continue
                f.seek(max(0, info.st_size - 512 * 1024))
                content = f.read(512 * 1024).decode('utf-8', errors='replace')
            for pattern in panic_patterns:
                match = pattern.search(content)
                if match:
                    panics.append({
                        'log_path': str(log_path),
                        'log_name': log_path.name,
                        'signature': match.group(0).strip(),
                        'matched_detail': match.group(1).strip() if match.lastindex else match.group(0).strip(),
                    })
                    break
        except (OSError, UnicodeError, RecoveryError):
            continue
    return panics


def check_agent_storage_health(home: Path) -> dict:
    """Comprehensive health and integrity check for coding agent storage across providers."""
    home = Path(home)
    report = {
        'schema': 'uncrash.llm-session-diagnostics/v1',
        'observed_at': datetime.now(timezone.utc).isoformat(),
        'status': 'HEALTHY',
        'providers': {},
        'corrupted_sessions': [],
        'unavailable_sessions': [],
        'detected_panics': [],
    }

    # Antigravity (agy)
    agy_root = home / '.gemini/antigravity-cli'
    if agy_root.is_dir():
        corrupt_dbs = []
        unavailable_dbs = []
        checked_count = 0
        conv_dir = agy_root / 'conversations'
        if conv_dir.is_dir():
            db_paths = sorted(conv_dir.glob('*.db'))
            checked_count = len(db_paths)
            results = check_sqlite_integrity_batch(db_paths)
            for db_path, status, err in results:
                if status != 'ok':
                    (corrupt_dbs if status == 'corrupted' else unavailable_dbs).append({
                        'provider': 'agy',
                        'session_id': db_path.stem,
                        'path': str(db_path),
                        'error': err or 'unknown integrity failure',
                        'remediation': 'Preserve the source; recover to a new private path only after verifying an offline or consistent snapshot.' if status == 'corrupted' else 'Retry the read-only check when the database is accessible.',
                    })

        summary_db = agy_root / 'conversation_summaries.db'
        summary_status = 'not-present'
        if summary_db.is_file():
            s_status, s_err = check_sqlite_integrity(summary_db)
            summary_status = s_status
            if s_status != 'ok':
                (corrupt_dbs if s_status == 'corrupted' else unavailable_dbs).append({
                    'provider': 'agy',
                    'session_id': 'conversation_summaries',
                    'path': str(summary_db),
                    'error': s_err or 'summary database malformed',
                    'remediation': 'Preserve the source and verify recovery to a new private path.' if s_status == 'corrupted' else 'Retry when the database is accessible.',
                })

        panics = scan_agent_log_panics(agy_root / 'log')

        report['providers']['agy'] = {
            'checked_sessions': checked_count,
            'summary_integrity': summary_status,
            'corrupted_count': len(corrupt_dbs),
            'unavailable_count': len(unavailable_dbs),
            'panic_count': len(panics),
        }
        report['corrupted_sessions'].extend(corrupt_dbs)
        report['unavailable_sessions'].extend(unavailable_dbs)
        report['detected_panics'].extend(panics)

    if report['corrupted_sessions']:
        report['status'] = 'CORRUPTED'
    elif report['detected_panics'] or report['unavailable_sessions']:
        report['status'] = 'DEGRADED'

    return report


def native_provider_inventory(home: Path, state_root: Path = None) -> dict | None:
    """Attempt fast native Rust scan of provider sessions; returns None if native worker is unavailable."""
    try:
        home = no_links(home)
    except (OSError, RecoveryError):
        return None
    binary = find_native_worker(state_root)
    if binary is None:
        return None
    try:
        proc = subprocess.run(
            [str(binary), '--provider-inventory', str(home)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0:
            data = json.loads(proc.stdout.strip() or '{}')
            if isinstance(data, dict) and 'codex' in data and 'claude' in data and 'agy_db_stems' in data:
                return data
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError):
        pass
    return None


def provider_inventory(home, check_integrity=False, state_root=None):
    home = Path(home)
    result = {}
    native_data = native_provider_inventory(home, state_root=state_root)
    if native_data is not None:
        result['codex'] = native_data['codex']
        result['claude'] = native_data['claude']
        db_files = set(native_data['agy_db_stems'])
    else:
        ids = []
        labels = Counter()
        invalid = 0
        files = list((home / '.codex/sessions').rglob('*.jsonl'))
        for path in files:
            try:
                with no_links(path).open('rb') as stream:
                    raw = stream.readline(1024**2 + 1)
                if len(raw) > 1024**2:
                    raise ValueError('oversized metadata')
                record = json.loads(raw)
                if record.get('type') != 'session_meta':
                    raise ValueError('missing metadata')
                meta = record['payload']
                sid = meta['id']
                if not isinstance(sid, str):
                    raise ValueError('invalid identity')
                ids.append(sid)
                label = meta.get('source')
                labels[label if isinstance(label, str) else 'structured-source'] += 1
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                invalid += 1
        result['codex'] = {
            'files': len(files),
            'metadata_records': len(ids),
            'unique_ids': len(set(ids)),
            'invalid_metadata': invalid,
            'source_labels': dict(labels),
            'host_binding': 'not-present'
        }
        try:
            root = no_links(home / '.gemini/antigravity-cli')
            conv_dir = root / 'conversations'
            db_files = {p.stem for p in conv_dir.glob('*.db')} if conv_dir.is_dir() else set()
        except (OSError, RecoveryError):
            db_files = set()
        result['claude'] = {
            'jsonl_files': sum(1 for _ in (home / '.claude/projects').rglob('*.jsonl')),
            'conversation_ids': 'not-enumerated',
            'host_binding': 'not-verified'
        }

    try:
        root = no_links(home / '.gemini/antigravity-cli')
        summary = root / 'conversation_summaries.db'
    except (OSError, RecoveryError):
        result['agy'] = {'db_files': len(db_files), 'summary_status': 'unavailable', 'database_integrity': 'unavailable'}
        return result

    connection = None
    corrupted_dbs = []
    unavailable_dbs = []
    try:
        connection = sqlite3.connect('file:' + quote(str(no_links(summary)), safe='/') + '?mode=ro', uri=True, timeout=1)
        rows = [r[0] for r in connection.execute('SELECT conversation_id FROM conversation_summaries')]
        valid = {r for r in rows if isinstance(r, str)}
        if check_integrity:
            conv_dir = root / 'conversations'
            if conv_dir.is_dir():
                db_paths = sorted(conv_dir.glob('*.db'))
                results = check_sqlite_integrity_batch(db_paths)
                for db_file, st, err in results:
                    if st != 'ok':
                        (corrupted_dbs if st == 'corrupted' else unavailable_dbs).append({'id': db_file.stem, 'error': err})
            integrity_status = 'corrupted' if corrupted_dbs else 'unavailable' if unavailable_dbs else 'ok'
        else:
            integrity_status = 'not-checked'
        result['agy'] = {
            'summary_rows': len(rows),
            'unique_summary_ids': len(valid),
            'db_files': len(db_files),
            'summary_with_file': len(valid & db_files),
            'summary_without_file': len(valid - db_files),
            'file_without_summary': len(db_files - valid),
            'host_binding': 'not-present',
            'database_integrity': integrity_status,
            'corrupted_sessions': corrupted_dbs,
            'unavailable_sessions': unavailable_dbs,
            'resume_verified': False
        }
    except (OSError, sqlite3.Error, RecoveryError):
        result['agy'] = {'db_files': len(db_files), 'summary_status': 'unavailable', 'database_integrity': 'unavailable'}
    finally:
        if connection is not None:
            connection.close()
    return result


def native_snapshot_health(state: Path, interval: int = 300, now: datetime = None, state_root: Path = None) -> dict | None:
    """Attempt cached native verification; unsupported or unavailable workers use Python."""
    try:
        state = no_links(state)
    except (OSError, RecoveryError):
        return None
    binary = find_native_worker(state_root or state)
    if binary is None:
        return None
    try:
        args = [str(binary), '--snapshot-health', str(state), str(interval)]
        if now is not None:
            args.append(now.isoformat())
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode == 0:
            data = json.loads(proc.stdout.strip() or '{}')
            if isinstance(data, dict) and 'verified_plain_manifests' in data:
                return data
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError):
        pass
    return None


def snapshot_health(state, interval=300, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        no_links(state)
        native_result = native_snapshot_health(state, interval, now)
        if native_result is not None:
            return native_result
    except (OSError, RecoveryError):
        pass
    snapshots = []; invalid = 0; historical = {}; encrypted = []
    root = no_links(Path(state) / 'snapshots')
    for directory in sorted(root.glob('*')):
        if directory.name.startswith('.'): continue
        manifest = directory / 'manifest.json'
        if not manifest.exists():
            if (directory / 'manifest.enc').is_file(): encrypted.append(directory.name)
            continue  # Encrypted copies need an explicit key-aware audit.
        try:
            data, raw = _read_json(manifest)
            if hashlib.sha256(raw).hexdigest() != _read_regular_bytes(directory / 'manifest.sha256', 4096).decode().strip():
                raise ValueError('checksum mismatch')
            if data.get('schema') != 'uncrash.snapshot/v1' or data.get('id') != directory.name:
                raise ValueError('manifest identity mismatch')
            created = datetime.fromisoformat(data['created_at'])
            if created.tzinfo is None or created > now: raise ValueError('invalid capture time')
            snapshots.append((created, directory.name))
            jb = data.get('jetbrains', {}); descendants = {r['pid']: r for r in jb.get('descendants', [])}
            roots = {r['pid'] for r in jb.get('processes', []) if r.get('root_ide_candidate')}
            for pid, row in descendants.items():
                if row.get('name') not in PROVIDERS: continue
                cursor = row.get('ppid'); seen = {pid}; chain = []
                while cursor in descendants and cursor not in seen:
                    seen.add(cursor); chain.append(cursor)
                    if cursor in roots: break
                    cursor = descendants[cursor].get('ppid')
                if cursor not in roots: continue
                # Old snapshots lack boot identity: group only as an observation key, not globally unique PID identity.
                key = (data.get('origin'), pid, row['start_ticks'], cursor)
                record = historical.setdefault(key, {'provider': row['name'], 'pid': pid,
                    'start_ticks': row['start_ticks'], 'ide_pid': cursor, 'cwd': row.get('cwd'),
                    'terminal': row.get('terminal'), 'first_snapshot': directory.name,
                    'conversation_id': None, 'boot_id': None, 'observations': 0})
                record['last_snapshot'] = directory.name; record['observations'] += 1
        except (OSError, ValueError, KeyError, TypeError, AttributeError): invalid += 1
    newest = max(snapshots) if snapshots else None
    age = (now - newest[0]).total_seconds() if newest else None
    newer_encrypted = bool(encrypted and (newest is None or max(encrypted) > newest[1]))
    return {'verified_plain_manifests': len(snapshots), 'invalid_manifests': invalid,
            'latest_snapshot': newest[1] if newest else None, 'age_seconds': round(age, 1) if age is not None else None,
            'stale': None if newer_encrypted else age is None or age > 2 * interval,
            'freshness': 'unknown-encrypted' if newer_encrypted else 'verified-plaintext-manifest',
            'stale_threshold_seconds': 2 * interval,
            'payload_hashes_verified': False, 'encrypted_manifests': 'not-inspected',
            'encrypted_manifest_count': len(encrypted),
            'historical_ide_provider_observations': list(historical.values())}


def diagnose(home=None, state=None, interval=300):
    home = Path(home or Path.home()); state = Path(state or home / '.local/state/uncrash')
    current = session_hosts(state_root=state); inventory = provider_inventory(home, state_root=state); backups = snapshot_health(state, interval)
    agent_health = check_agent_storage_health(home)
    findings = []
    if backups['stale']: findings.append('UNCRASH-BACKUP-STALE')
    if backups['stale'] is None: findings.append('UNCRASH-MANIFEST-UNVERIFIED')
    if backups['invalid_manifests']: findings.append('UNCRASH-MANIFEST-INVALID')
    if inventory['agy'].get('summary_without_file', 0): findings.append('UNCRASH-SESSION-FILE-MISSING')
    if any(p['conversation_id'] is None for p in current['processes']): findings.append('UNCRASH-HOST-BINDING-UNKNOWN')
    if agent_health.get('corrupted_sessions'): findings.append('UNCRASH-SESSION-STORAGE-CORRUPTED')
    if agent_health.get('detected_panics'): findings.append('UNCRASH-AGENT-PANIC-DETECTED')
    return {'schema': 'uncrash.diagnostics/v1', 'observed_at': current['observed_at'],
            'current': current, 'providers': inventory, 'backups': backups,
            'agent_health': agent_health, 'findings': findings,
            'applications_restarted': False, 'signals_sent': False, 'terminal_contents_read': False}


def save_report(report, destination):
    destination = no_links(destination)
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    raw = json.dumps(report, ensure_ascii=False, indent=2).encode()
    write_file(destination / 'diagnostics.json', raw)
    from .events import append_event
    append_event(destination, event_type='uncrash.diagnosis_completed', outcome='SUCCEEDED',
                 evidence=[{'path': 'diagnostics.json', 'sha256': hashlib.sha256(raw).hexdigest()}])
    return str(destination / 'diagnostics.json')
