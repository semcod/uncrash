from __future__ import annotations

import configparser
import os
from pathlib import Path
import shlex
import shutil
import subprocess


DESKTOP_ROOTS = [Path('/usr/share/applications'), Path('/usr/local/share/applications'),
    Path.home()/'.local/share/applications', Path('/var/lib/snapd/desktop/applications'),
    Path('/var/lib/flatpak/exports/share/applications'),
    Path.home()/'.local/share/flatpak/exports/share/applications']


def desktop_inventory(roots=None):
    """Inspect launchers without executing their arbitrary Exec strings."""
    records = []
    for root in DESKTOP_ROOTS if roots is None else roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob('*.desktop')):
            parser = configparser.ConfigParser(interpolation=None, strict=False)
            parser.optionxform = str
            try:
                parser.read(path, encoding='utf-8')
                entry = parser['Desktop Entry']
                if entry.get('Type') != 'Application':
                    continue
                argv = shlex.split(entry.get('Exec', ''))
                executable = argv[0] if argv else entry.get('TryExec', '')
                # env launchers are metadata only, never evaluated here.
                if executable == 'env' or executable.endswith('/env'):
                    executable = next((v for v in argv[1:] if '=' not in v and not v.startswith('-')), '')
                available = bool(executable and (Path(executable).is_file() if '/' in executable else shutil.which(executable)))
                records.append({'id': path.stem, 'name': entry.get('Name', path.stem),
                    'launcher': str(path), 'executable': executable, 'executable_present': available,
                    'hidden': entry.get('NoDisplay', 'false').lower() == 'true' or entry.get('Hidden', 'false').lower() == 'true',
                    'restore_status': 'UNTESTED',
                    'reason': 'Requires an explicit synthetic state profile and application-specific assertions.'})
            except (OSError, ValueError, configparser.Error, KeyError) as exc:
                records.append({'id': path.stem, 'launcher': str(path), 'restore_status': 'INVALID_LAUNCHER', 'reason': type(exc).__name__})
    for command in ['codex', 'claude', 'agy', 'tmux', 'screen']:
        executable = shutil.which(command)
        if executable:
            records.append({'id': 'cli-'+command, 'name': command, 'executable': executable,
                'executable_present': True, 'restore_status': 'UNTESTED',
                'reason': 'Native conversation/session-resume adapter needed; live PTY memory is not captured.'})
    return records


def process_inventory():
    """Collect identities, never environments, command arguments or chat contents."""
    records = []
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            if path.stat().st_uid != os.getuid():
                continue
            fields = (path/'stat').read_text().rsplit(')', 1)[1].split()
            records.append({'pid': int(path.name), 'start_ticks': fields[19],
                'name': (path/'comm').read_text().strip()})
        except (OSError, IndexError, ValueError):
            continue
    return records


def classify_inventory(inventory, rows):
    """Match launch routes without conflating every Snap symlink with /usr/bin/snap."""
    for item in inventory:
        raw = item.get('executable', '')
        resolved = (raw if '/' in raw else shutil.which(raw)) if raw else None
        matched = next((r for r in rows if resolved and os.path.abspath(r['executable']) == os.path.abspath(resolved)), None)
        if matched:
            item.update(restore_status=matched['status'], app_session_state_verified=False,
                synthetic_files_restored=True, tested_executable=matched['executable'], reason=matched['reason'])
        elif not item.get('executable_present'):
            item.update(restore_status='EXECUTABLE_MISSING', reason='Launcher exists but its executable was not resolved.')
        else:
            item.update(restore_status='ADAPTER_OR_FIXTURE_REQUIRED',
                reason='Not executed automatically: system components, URL handlers, credential managers, proprietary launchers or missing state assertions.')
    return inventory

