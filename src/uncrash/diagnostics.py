"""Read-only terminal provenance and backup health; never read a PTY or chat body."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from urllib.parse import quote

from .store import RecoveryError, no_links, write_file


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


def _read_json(path, maximum=32 * 1024**2):
    path = no_links(path)
    with path.open('rb') as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError('metadata limit exceeded')
    return json.loads(raw), raw


def session_hosts(proc_root=Path('/proc')):
    """Observe PID/start identity twice; source labels never determine the host."""
    proc_root = Path(proc_root)
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
    for pid, node in nodes.items():
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


def provider_inventory(home):
    home = Path(home); result = {}; ids = []; labels = Counter(); invalid = 0
    files = list((home / '.codex/sessions').rglob('*.jsonl'))
    for path in files:
        try:
            with no_links(path).open('rb') as stream: raw = stream.readline(1024**2 + 1)
            if len(raw) > 1024**2: raise ValueError('oversized metadata')
            record = json.loads(raw)
            if record.get('type') != 'session_meta': raise ValueError('missing metadata')
            meta = record['payload']; sid = meta['id']
            if not isinstance(sid, str): raise ValueError('invalid identity')
            ids.append(sid); label = meta.get('source')
            labels[label if isinstance(label, str) else 'structured-source'] += 1
        except (OSError, ValueError, KeyError, TypeError, AttributeError): invalid += 1
    result['codex'] = {'files': len(files), 'metadata_records': len(ids), 'unique_ids': len(set(ids)),
                       'invalid_metadata': invalid, 'source_labels': dict(labels), 'host_binding': 'not-present'}
    root = no_links(home / '.gemini/antigravity-cli'); db_files = {p.stem for p in (root / 'conversations').glob('*.db')}
    summary = root / 'conversation_summaries.db'; connection = None
    try:
        connection = sqlite3.connect('file:' + quote(str(no_links(summary)), safe='/') + '?mode=ro', uri=True, timeout=1)
        rows = [r[0] for r in connection.execute('SELECT conversation_id FROM conversation_summaries')]
        valid = {r for r in rows if isinstance(r, str)}
        result['agy'] = {'summary_rows': len(rows), 'unique_summary_ids': len(valid), 'db_files': len(db_files),
            'summary_with_file': len(valid & db_files), 'summary_without_file': len(valid - db_files),
            'file_without_summary': len(db_files - valid), 'host_binding': 'not-present',
            'database_integrity': 'not-checked', 'resume_verified': False}
    except (OSError, sqlite3.Error, RecoveryError):
        result['agy'] = {'db_files': len(db_files), 'summary_status': 'unavailable'}
    finally:
        if connection is not None: connection.close()
    result['claude'] = {'jsonl_files': sum(1 for _ in (home / '.claude/projects').rglob('*.jsonl')),
                        'conversation_ids': 'not-enumerated', 'host_binding': 'not-verified'}
    return result


def snapshot_health(state, interval=300, now=None):
    now = now or datetime.now(timezone.utc); snapshots = []; invalid = 0; historical = {}; encrypted = []
    root = no_links(Path(state) / 'snapshots')
    for directory in sorted(root.glob('*')):
        if directory.name.startswith('.'): continue
        manifest = directory / 'manifest.json'
        if not manifest.exists():
            if (directory / 'manifest.enc').is_file(): encrypted.append(directory.name)
            continue  # Encrypted copies need an explicit key-aware audit.
        try:
            data, raw = _read_json(manifest)
            if hashlib.sha256(raw).hexdigest() != no_links(directory / 'manifest.sha256').read_text().strip():
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
    current = session_hosts(); inventory = provider_inventory(home); backups = snapshot_health(state, interval)
    findings = []
    if backups['stale']: findings.append('UNCRASH-BACKUP-STALE')
    if backups['stale'] is None: findings.append('UNCRASH-MANIFEST-UNVERIFIED')
    if backups['invalid_manifests']: findings.append('UNCRASH-MANIFEST-INVALID')
    if inventory['agy'].get('summary_without_file', 0): findings.append('UNCRASH-SESSION-FILE-MISSING')
    if any(p['conversation_id'] is None for p in current['processes']): findings.append('UNCRASH-HOST-BINDING-UNKNOWN')
    return {'schema': 'uncrash.diagnostics/v1', 'observed_at': current['observed_at'],
            'current': current, 'providers': inventory, 'backups': backups, 'findings': findings,
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
