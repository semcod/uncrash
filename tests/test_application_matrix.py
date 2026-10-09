"""Inventory all launchers; exercise safe GUI fixtures without personal profiles."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import select
import re
import time

import pytest

from uncrash.inventory import desktop_inventory
from uncrash.runtime import Launcher, pidfd
from uncrash.store import Store

from test_novnc import sandbox


pytestmark = pytest.mark.skipif(os.environ.get('UNCRASH_APP_MATRIX') != '1', reason='Opt-in installed GUI fixture matrix')


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


def test_installed_application_fixture_matrix(tmp_path):
    from twinerd_native.session import NativeClone
    from twinerd_cdp import CDPClient
    root = Path(os.environ.get('UNCRASH_MATRIX_ARTIFACTS', str(tmp_path)))
    root.mkdir(parents=True, exist_ok=True)
    clone = NativeClone(root/'desktop', Path(os.environ['UNCRASH_NOVNC_ASSETS']))
    store = Store(root/'store', 'installed-app-fixture')
    launcher = Launcher(store)
    prior = os.environ.get('UNCRASH_MATRIX_PRIOR')
    rows = json.loads(Path(prior).read_text()) if prior else []
    candidates = {
        'gnome-calculator': [], 'gnome-text-editor': ['/home/tom/document.txt'],
        'papers': [], 'evince': [], 'blender': ['--factory-startup'], 'vlc': ['--no-one-instance'],
        'remmina': [], 'subl': ['--multiinstance', '/home/tom/document.txt'],
        'code': ['--no-sandbox', '--disable-gpu', '--user-data-dir=/home/tom/settings', '--extensions-dir=/home/tom/extensions', '/home/tom/document.txt'],
        'code-insiders': ['--no-sandbox', '--disable-gpu', '--user-data-dir=/home/tom/settings', '--extensions-dir=/home/tom/extensions', '/home/tom/document.txt'],
        'codium': ['--no-sandbox', '--disable-gpu', '--user-data-dir=/home/tom/settings', '--extensions-dir=/home/tom/extensions', '/home/tom/document.txt'],
        'cursor': ['--no-sandbox', '--disable-gpu', '--user-data-dir=/home/tom/settings', '--extensions-dir=/home/tom/extensions', '/home/tom/document.txt'],
        'antigravity': ['--no-sandbox', '--disable-gpu', '--user-data-dir=/home/tom/settings', '--extensions-dir=/home/tom/extensions', '/home/tom/document.txt'],
        'qoder': ['--no-sandbox', '--disable-gpu', '--user-data-dir=/home/tom/settings', '--extensions-dir=/home/tom/extensions', '/home/tom/document.txt'],
        'opencode-desktop': [], 'warp-terminal': [], 'gnome-clocks': [], 'gnome-characters': [],
        'gnome-font-viewer': [], 'gnome-system-monitor': [], 'gnome-logs': [],
        'strawberry': [], 'clementine': [], 'firefox': ['--no-remote', '--profile', '/home/tom/profile'],
        'chromium': ['--no-sandbox', '--disable-gpu', '--user-data-dir=/home/tom/profile'],
        'libreoffice': ['-env:UserInstallation=file:///home/tom/profile', '--writer', '/home/tom/document.txt'],
        'nautilus': ['--new-window', '/home/tom/project'], 'baobab': ['/home/tom/project'],
        'eog': [], 'yelp': [], 'gnome-terminal': ['--', '/bin/cat', '/home/tom/document.txt'],
        'zenity': ['--text-info', '--filename=/home/tom/document.txt', '--title=Uncrash fixture'],
        'qjackctl': [], 'remote-viewer': [], 'virt-manager': [], 'sysprof': [],
        'gnome-power-statistics': [], 'nvidia-settings': [], 'gnome-control-center': [],
        'idle-python3.13': ['/home/tom/project/fixture.py'],
        'ai.opencode.desktop': ['--no-sandbox', '--disable-gpu'],
        'devin-desktop': ['--no-sandbox', '--disable-gpu'],
        'exef': ['--no-sandbox', '--disable-gpu'],
    }
    direct = {'pycharm-snap': ('/snap/pycharm-professional/current/bin/pycharm', 'PYCHARM_VM_OPTIONS')}
    direct.update({name: (executable, None) for name, executable in {
        'ai.opencode.desktop': '/opt/OpenCode/ai.opencode.desktop',
        'devin-desktop': '/usr/share/devin-desktop/devin-desktop',
        'exef': '/opt/ExEF Desktop/exef',
    }.items()})
    toolbox = Path.home()/'.local/share/JetBrains/Toolbox/apps'
    for name, product, binary, options in [
        ('pycharm-toolbox', 'pycharm-2', 'pycharm', 'PYCHARM_VM_OPTIONS'),
        ('idea-community', 'intellij-idea-community-edition', 'idea', 'IDEA_VM_OPTIONS'),
        ('webstorm', 'webstorm', 'webstorm', 'WEBSTORM_VM_OPTIONS'),
        ('webstorm-3', 'webstorm-3', 'webstorm', 'WEBSTORM_VM_OPTIONS'),
        ('android-studio', 'android-studio', 'studio', 'STUDIO_VM_OPTIONS'),
        ('jetbrains-gateway', 'gateway', 'gateway', 'GATEWAY_VM_OPTIONS')]:
        direct[name] = (str(toolbox/product/'bin'/binary), options)
    direct['zed'] = (str(Path.home()/'.local/zed.app/bin/zed'), None)
    direct['zed-preview'] = (str(Path.home()/'.local/zed-preview.app/bin/zed'), None)
    direct['antigravity-ide'] = (str(Path.home()/'.local/opt/antigravity-ide/bin/antigravity-ide'), None)
    for name, (executable, _) in direct.items():
        if Path(executable).is_file():
            candidates.setdefault(name, ['/home/tom/document.txt'] if name in {'zed', 'zed-preview', 'antigravity-ide'} else ['/home/tom/project'])
    selection = os.environ.get('UNCRASH_APP_SELECTION')
    if selection:
        names = set(selection.split(','))
        candidates = {name: arguments for name, arguments in candidates.items() if name in names}
    env = None
    try:
        clone.start()
        env = {**os.environ, 'DISPLAY': f':{clone.display}'}
        def windows():
            result = subprocess.run(['xdotool', 'search', '--onlyvisible', '--class', '.'], env=env, capture_output=True, text=True)
            return set(result.stdout.splitlines())
        viewer = CDPClient(clone.viewer_tab['webSocketDebuggerUrl'])
        for name, arguments in candidates.items():
            executable = direct[name][0] if name in direct else shutil.which(name)
            if not executable:
                continue
            source = root/('source-'+name); source.mkdir()
            (source/'document.txt').write_text('Uncrash synthetic state: '+name+'\n')
            (source/'profile').mkdir()
            (source/'runtime').mkdir(mode=0o700)
            (source/'project').mkdir()
            (source/'project/fixture.py').write_text('print("Uncrash synthetic project")\n')
            (source/'fixture.vmoptions').write_text('-Xms64m\n-Xmx512m\n-Didea.config.path=/home/tom/ide-config\n-Didea.system.path=/home/tom/ide-system\n-Didea.log.path=/home/tom/ide-log\n-Didea.plugins.path=/home/tom/ide-plugins\n')
            command = sandbox('{state_dir}', '{display}', ['/bin/sh', '-c',
                'exec "$@" > /home/tom/fixture-launch.log 2>&1', 'fixture',
                '/usr/bin/dbus-run-session', '--', executable, *arguments])
            # Offline app fixtures cannot reach external accounts or host session buses.
            command.insert(1, '--unshare-net')
            if name in direct:
                install = str(Path(executable).parent.parent)
                if install.startswith(str(Path.home())+'/'):
                    position = command.index('--die-with-parent')
                    command[position:position] = ['--ro-bind', install, install]
                if direct[name][1]:
                    command[1:1] = ['--setenv', direct[name][1], '/home/tom/fixture.vmoptions']
            profile_id = re.sub('[^a-z0-9_-]', '-', name)
            config = {'profiles': [{'id': profile_id, 'state_dir': str(source), 'argv': command}]}
            row = {'application': name, 'executable': executable, 'app_session_state_verified': False}
            sid = store.capture(config)['snapshot']
            (source/'document.txt').write_text('changed after snapshot')
            receipt = store.restore(sid, config, root/('restored-'+name))
            assert (root/('restored-'+name)/profile_id/'document.txt').read_text() == 'Uncrash synthetic state: '+name+'\n'
            row['synthetic_files_restored'] = True
            before = windows()
            try:
                launched = launcher.launch(config, receipt, f':{clone.display}')
                deadline = time.monotonic()+(20 if name in direct else 10 if name in {'blender', 'cursor', 'antigravity', 'qoder'} else 5)
                new = set()
                fd = pidfd(launched[0]['pid'])
                try:
                    while time.monotonic() < deadline:
                        new = windows()-before
                        if new or select.select([fd], [], [], 0)[0]:
                            break
                        time.sleep(.2)
                finally:
                    os.close(fd)
                if new:
                    settle = float(os.environ.get('UNCRASH_WINDOW_SETTLE_SECONDS', '0'))
                    if settle:
                        time.sleep(settle)
                        new = windows()-before
                if new:
                    window = sorted(new)[0]
                    subprocess.run(['xdotool', 'windowraise', window], env=env, capture_output=True, timeout=4)
                    time.sleep(.25)
                    (root/(name+'-novnc.png')).write_bytes(viewer.capture_screenshot())
                    row.update(status='DATA_AND_WINDOW_PASS', window_seen=True, screenshot=name+'-novnc.png',
                        window_titles=[subprocess.run(['xdotool', 'getwindowname', w], env=env, capture_output=True, text=True).stdout.strip() for w in sorted(new)],
                        reason='Synthetic file bytes and a visible window (possibly splash/setup) verified; native saved session state is not verified.')
                else:
                    row.update(status='NO_WINDOW_IN_ISOLATED_FIXTURE', window_seen=False,
                        reason='No visible window within bounded startup; Snap/service/display/runtime prerequisites may differ in a full VM.')
            except (OSError, ValueError, TimeoutError, subprocess.SubprocessError) as exc:
                row.update(status='FIXTURE_FAILED', reason=type(exc).__name__)
            finally:
                launcher.stop()
            rows.append(row)
            (root/'application-fixture-results.json').write_text(json.dumps(rows, indent=2)+'\n')
            print(name+': '+row['status'], flush=True)
        inventory = classify_inventory(desktop_inventory(), rows)
        (root/'installed-application-matrix.json').write_text(json.dumps({'schema': 'uncrash.application-matrix/v1',
            'coverage': 'All discovered desktop launchers plus selected CLI tools; installed libraries/services are package inventory.',
            'applications': inventory, 'fixture_results': rows}, ensure_ascii=False, indent=2)+'\n')
        assert rows
        assert any(row['status'] == 'DATA_AND_WINDOW_PASS' for row in rows)
    finally:
        try:
            launcher.stop()
        finally:
            clone.stop()
