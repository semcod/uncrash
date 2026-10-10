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
    cli_commands = [
        'codex', 'claude', 'agy', 'tmux', 'screen',
        'nvidia-smi', 'nvtop', 'nvidia-settings',
        'cursor', 'code', 'zed', 'warp-terminal',
        'blender', 'virt-manager', 'qemu-system-x86_64',
        'docker', 'podman'
    ]
    for command in cli_commands:
        executable = shutil.which(command)
        if executable:
            records.append({'id': 'cli-'+command, 'name': command, 'executable': executable,
                'executable_present': True, 'restore_status': 'UNTESTED',
                'reason': 'Native conversation/session-resume adapter needed; live PTY memory is not captured.'})
    return records


_last_gpu_check = 0.0
_cached_gpu_status = None


def get_gpu_status(max_age_seconds: float = 3.0):
    """Inspect Nvidia GPU hardware and monitor availability."""
    global _last_gpu_check, _cached_gpu_status
    import time
    now = time.time()
    if _cached_gpu_status is not None and (now - _last_gpu_check) < max_age_seconds:
        return _cached_gpu_status

    smi = shutil.which('nvidia-smi')
    if not smi:
        return {
            'available': False,
            'present': False,
            'name': 'None',
            'driver_version': None,
            'cuda_version': None,
            'memory_total_mb': 0,
            'memory_used_mb': 0,
            'memory_free_mb': 0,
            'temperature_c': 0,
            'utilization_pct': 0,
            'gpu_utilization_pct': 0,
            'tools': {
                'nvidia-smi': False,
                'nvidia_smi': False,
                'nvtop': False,
                'nvidia-settings': False,
                'nvidia_settings': False
            },
            'compute_cache_dir': str(Path.home() / '.nv')
        }
    try:
        out = subprocess.check_output(
            ['nvidia-smi', '--query-gpu=name,driver_version,memory.total,memory.used,memory.free,temperature.gpu,utilization.gpu',
             '--format=csv,noheader,nounits'],
            text=True, timeout=2
        ).strip()
        parts = [p.strip() for p in out.split(',')]
        if len(parts) >= 7:
            res = {
                'available': True,
                'present': True,
                'name': parts[0],
                'driver_version': parts[1],
                'memory_total_mb': int(parts[2]),
                'memory_used_mb': int(parts[3]),
                'memory_free_mb': int(parts[4]),
                'temperature_c': int(parts[5]),
                'utilization_pct': int(parts[6]),
                'gpu_utilization_pct': int(parts[6]),
                'cuda_version': '13.0',
                'tools': {
                    'nvidia-settings': bool(shutil.which('nvidia-settings')),
                    'nvidia_settings': bool(shutil.which('nvidia-settings')),
                    'nvtop': bool(shutil.which('nvtop')),
                    'nvidia-smi': True,
                    'nvidia_smi': True,
                },
                'compute_cache_dir': str(Path.home() / '.nv')
            }
            _last_gpu_check = now
            _cached_gpu_status = res
            return res
    except Exception:
        pass
    fallback = {
        'available': False,
        'present': False,
        'name': 'None',
        'driver_version': None,
        'cuda_version': None,
        'memory_total_mb': 0,
        'memory_used_mb': 0,
        'memory_free_mb': 0,
        'temperature_c': 0,
        'utilization_pct': 0,
        'gpu_utilization_pct': 0,
        'tools': {
            'nvidia-smi': False,
            'nvidia_smi': False,
            'nvtop': False,
            'nvidia-settings': False,
            'nvidia_settings': False
        },
        'compute_cache_dir': str(Path.home() / '.nv')
    }
    _last_gpu_check = now
    _cached_gpu_status = fallback
    return fallback


def get_application_matrix():
    """Classify all installed PC applications by category with recovery capability."""
    inv = desktop_inventory()
    categories = {
        'gpu_hardware': {
            'label': 'GPU & Hardware (NVIDIA)',
            'icon': '🎮',
            'apps': []
        },
        'ai_agents': {
            'label': 'AI & Agentic IDEs / Assistants',
            'icon': '🤖',
            'apps': []
        },
        'jetbrains': {
            'label': 'JetBrains Ecosystem',
            'icon': '⚡',
            'apps': []
        },
        'code_terminals': {
            'label': 'Code Editors & Terminals',
            'icon': '💻',
            'apps': []
        },
        'browsers': {
            'label': 'Web Browsers',
            'icon': '🌐',
            'apps': []
        },
        'virtualization': {
            'label': 'Virtualization & Remote Desktop',
            'icon': '📦',
            'apps': []
        },
        'creative_media': {
            'label': '3D & Media Creation',
            'icon': '🎨',
            'apps': []
        },
        'system_utils': {
            'label': 'System Utilities & Tools',
            'icon': '🛠️',
            'apps': []
        }
    }

    PROFILE_MAP = [
        ('codex', 'codex-sessions'),
        ('claude', 'claude-sessions'),
        ('agy', 'agy-sessions'),
        ('pycharm', 'jetbrains-settings'),
        ('webstorm', 'jetbrains-settings'),
        ('idea', 'jetbrains-settings'),
        ('jetbrains', 'jetbrains-settings'),
        ('nvidia', 'nvidia-compute-cache'),
        ('nvtop', 'nvidia-compute-cache'),
        ('cursor', 'cursor-settings'),
        ('vscode', 'vscode-settings'),
        ('code', 'vscode-settings'),
        ('antigravity', 'antigravity2-settings'),
        ('warp', 'warp-terminal-settings'),
        ('zed', 'zed-settings'),
        ('devin', 'devin-desktop'),
        ('opencode', 'opencode-desktop'),
        ('qoder', 'qoder-settings'),
        ('blender', 'blender-settings'),
        ('google-chrome', 'google-chrome-profiles'),
        ('chrome', 'google-chrome-profiles'),
        ('chromium', 'chromium-profiles'),
        ('remmina', 'remmina-connections'),
        ('sublime', 'sublime-text-settings'),
    ]

    gpu_match = {'nvidia-settings', 'nvtop', 'nvidia-smi', 'cli-nvidia-smi', 'cli-nvtop', 'cli-nvidia-settings', 'org.rnd2.cpupower_gui'}
    ai_match = {'antigravity', 'antigravity-ide', 'cursor', 'devin-desktop', 'opencode-desktop', 'ai.opencode.desktop', 'qoder', 'grok-bot', 'cli-codex', 'cli-claude', 'cli-agy'}
    jb_match = {'jetbrains-pycharm', 'jetbrains-webstorm', 'jetbrains-idea-ce', 'jetbrains-studio', 'jetbrains-gateway', 'jetbrains-toolbox', 'jetbrainsd'}
    code_match = {'com.microsoft.VSCode', 'dev.zed.Zed', 'dev.warp.Warp', 'org.gnome.Terminal', 'debian-xterm', 'debian-uxterm', 'vim', 'idle', 'idle-python3.13', 'cli-code', 'cli-zed', 'cli-warp-terminal', 'cli-tmux', 'cli-screen'}
    browser_match = {'google-chrome', 'com.google.Chrome', 'chromium', 'firefox'}
    virt_match = {'virt-manager', 'qemu', 'remote-viewer', 'org.remmina.Remmina', 'xtigervncviewer', 'com.teamviewer.TeamViewer', 'cli-virt-manager', 'cli-docker', 'cli-podman'}
    creative_match = {'blender', 'cli-blender', 'org.strawberrymusicplayer.strawberry', 'org.rncbc.qjackctl'}

    for item in inv:
        if not item.get('executable_present'):
            continue
        iid = item.get('id', '')
        name = item.get('name', iid)
        matched_profile = None
        for key, prof in PROFILE_MAP:
            if key in iid.lower():
                matched_profile = prof
                break
        entry = {
            'id': iid,
            'name': name,
            'category': 'system_utils',
            'cmd': item.get('executable', iid),
            'executable': item.get('executable'),
            'launcher': item.get('launcher', ''),
            'desktop_file': item.get('launcher', ''),
            'recoverable': True,
            'has_recovery_profile': bool(matched_profile),
            'profile_id': matched_profile
        }
        if any(g in iid.lower() for g in gpu_match):
            entry['category'] = 'gpu_hardware'
            categories['gpu_hardware']['apps'].append(entry)
        elif any(a in iid.lower() for a in ai_match):
            entry['category'] = 'ai_agents'
            categories['ai_agents']['apps'].append(entry)
        elif any(j in iid.lower() for j in jb_match):
            entry['category'] = 'jetbrains'
            categories['jetbrains']['apps'].append(entry)
        elif any(c in iid.lower() for c in code_match):
            entry['category'] = 'code_terminals'
            categories['code_terminals']['apps'].append(entry)
        elif any(b in iid.lower() for b in browser_match):
            entry['category'] = 'browsers'
            categories['browsers']['apps'].append(entry)
        elif any(v in iid.lower() for v in virt_match):
            entry['category'] = 'virtualization'
            categories['virtualization']['apps'].append(entry)
        elif any(cr in iid.lower() for cr in creative_match):
            entry['category'] = 'creative_media'
            categories['creative_media']['apps'].append(entry)
        else:
            entry['category'] = 'system_utils'
            categories['system_utils']['apps'].append(entry)

    gpu = get_gpu_status()
    total_apps = sum(len(c['apps']) for c in categories.values())
    return {
        'schema': 'uncrash.application-matrix/v1',
        'total_installed': total_apps,
        'gpu': gpu,
        'categories': categories
    }


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

