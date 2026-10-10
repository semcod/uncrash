"""Explicit native durable-data selection; no provider calls or window control."""
from pathlib import Path
import json
import os
import uuid

from .store import RecoveryError, no_links, private_dir, profiles, sync_dir, write_file


def discover(home=None):
    home = no_links(home or Path.home())
    definitions = [
        ('codex-sessions', '.codex', ['sessions/**/*.jsonl', 'state_*.sqlite'], ['state_*.sqlite']),
        ('claude-sessions', '.claude/projects', ['**/*.jsonl'], []),
        ('agy-sessions', '.gemini/antigravity-cli',
            ['conversations/*.db', 'conversation_summaries.db', 'history.jsonl'],
            ['conversations/*.db', 'conversation_summaries.db']),
        ('jetbrains-settings', '.config/JetBrains',
            ['*/options/*.xml', '*/options/*.json', '*/keymaps/*.xml', '*/colors/*',
                '*/filetypes/*.xml', '*/templates/*.xml', '*/codestyles/*.xml', '*/dictionaries/*.xml'], []),
        ('jetbrains-recovery', '.cache/JetBrains',
            ['*/LocalHistory/*', '*/workspace/*.xml'], []),
        ('nvidia-compute-cache', '.nv', ['**/*'], []),
        ('cursor-settings', '.config/cursor', ['**/*'], []),
        ('cursor-agent', '.local/share/cursor-agent', ['**/*'], []),
        ('vscode-settings', '.config/Code', ['User/settings.json', 'User/keybindings.json', 'User/snippets/*'], []),
        ('vscode-insiders-settings', '.config/Code - Insiders', ['User/settings.json', 'User/keybindings.json', 'User/snippets/*'], []),
        ('antigravity2-settings', '.config/antigravity2', ['**/*'], []),
        ('antigravity-ide-state', '.local/share/antigravity-ide', ['**/*'], []),
        ('warp-terminal-settings', '.config/warp-terminal', ['**/*'], []),
        ('zed-settings', '.config/zed', ['settings.json', 'keymap.json'], []),
        ('devin-desktop', '.config/devin', ['**/*'], []),
        ('opencode-desktop', '.config/opencode', ['**/*'], []),
        ('qoder-settings', '.config/qoder', ['**/*'], []),
        ('blender-settings', '.config/blender', ['*/*/*.blend', '*/*/*.xml', '*/*/*.py'], []),
        ('google-chrome-profiles', '.config/google-chrome', ['Default/Preferences', 'Default/Bookmarks'], []),
        ('chromium-profiles', '.config/chromium', ['Default/Preferences', 'Default/Bookmarks'], []),
        ('remmina-connections', '.config/remmina', ['**/*.remmina', 'remmina.pref'], []),
        ('sublime-text-settings', '.config/sublime-text', ['Packages/User/*'], []),
    ]
    found = []
    for identity, relative, includes, databases in definitions:
        root = home/relative
        if not root.is_dir(): continue
        no_links(root)
        found.append({'id': identity, 'state_dir': str(root), 'argv': [],
            'include_globs': includes, 'sqlite_backup_globs': databases})
    profiles({'profiles': found})
    return found


def selected_config(config, identities, home=None):
    known = {p['id']: p for p in discover(home)}
    if not identities or len(set(identities)) != len(identities) or set(identities)-set(known):
        raise RecoveryError('Select unique IDs from the discovered native profiles')
    existing = {p['id']: p for p in profiles(config)}
    # An existing user definition is never silently overwritten by discovery.
    if set(identities) & set(existing):
        raise RecoveryError('A selected profile already exists; preserve and review its configuration')
    result = {**config, 'profiles': [*existing.values(), *[known[i] for i in identities]],
        'compress': config.get('compress', False)}
    profiles(result)
    return result


def save_config(path, config):
    path = no_links(path)
    private_dir(path.parent)
    if path.exists():
        info = path.stat()
        if not path.is_file() or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise RecoveryError('Existing config must be an owned private regular file')
        previous = path.with_name(path.name+'.pre-uncrash-'+uuid.uuid4().hex[:12])
        write_file(previous, path.read_bytes())
    temporary = path.with_name('.config-'+uuid.uuid4().hex)
    write_file(temporary, json.dumps(config, indent=2).encode())
    os.replace(temporary, path); sync_dir(path.parent)
