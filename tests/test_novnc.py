"""Opt-in real desktop proofs using synthetic profiles and owned Twinerd sessions."""
import json
import os
from pathlib import Path
import subprocess
import time

import pytest

from uncrash.store import Store
from uncrash.runtime import Launcher


pytestmark = pytest.mark.skipif(os.environ.get('UNCRASH_NOVNC_TEST') != '1', reason='Opt-in real Twinerd desktop fixture')


def sandbox(home, display, argv):
    return ['bwrap', '--ro-bind', '/', '/', '--unshare-user', '--unshare-pid',
        '--unshare-ipc', '--unshare-uts', '--proc', '/proc', '--dev', '/dev',
        '--tmpfs', '/home', '--tmpfs', '/tmp', '--tmpfs', '/run',
        '--bind', home, '/home/tom', '--ro-bind', '/tmp/.X11-unix', '/tmp/.X11-unix',
        '--die-with-parent', '--setenv', 'HOME', '/home/tom', '--setenv', 'DISPLAY', display,
        '--setenv', 'XDG_CONFIG_HOME', '/home/tom/.config', '--setenv', 'XDG_CACHE_HOME', '/home/tom/.cache',
        '--setenv', 'XDG_DATA_HOME', '/home/tom/.local/share', '--setenv', 'XDG_RUNTIME_DIR', '/home/tom/runtime',
        '--setenv', 'GSK_RENDERER', 'cairo', '--setenv', 'LIBGL_ALWAYS_SOFTWARE', '1',
        '--unsetenv', 'DBUS_SESSION_BUS_ADDRESS', *argv]


def wait(probe, timeout=30):
    end = time.monotonic()+timeout
    while time.monotonic() < end:
        try:
            value = probe()
            if value:
                return value
        except (OSError, ValueError, ConnectionError):
            pass
        time.sleep(.1)
    raise TimeoutError('Owned test application readiness timeout')


def test_chrome_session_and_terminal_recovery_on_twinerd_novnc(tmp_path):
    from twinerd_native.session import NativeClone, port, tabs, value
    from twinerd_cdp import CDPClient
    root = Path(os.environ.get('UNCRASH_TEST_ARTIFACTS', str(tmp_path)))
    root.mkdir(parents=True, exist_ok=True)
    novnc = Path(os.environ['UNCRASH_NOVNC_ASSETS'])
    source = NativeClone(root/'source-desktop', novnc)
    target = None
    store = Store(root/'encrypted-store', 'novnc-fixture')
    launcher = Launcher(store)
    token = 'uncrash-'+source.token
    proof = {'schema': 'uncrash.novnc-test-receipt/v1', 'token': token,
        'chrome': {}, 'xterm': {}, 'fidelity': 'browser saved localStorage/session + terminal durable-file replay; no live RAM/PTY'}
    try:
        source.start()
        CDPClient(source.chrome_tab['webSocketDebuggerUrl']).evaluate('localStorage.setItem("uncrash-marker", '+json.dumps(token)+'); localStorage.getItem("uncrash-marker")')
        assert value(source.chrome_tab, 'localStorage.getItem("uncrash-marker")') == token
        (source.home/'Projects/tab2.html').write_text('<title>Uncrash second tab '+source.token+'</title><h1>Second saved tab</h1>')
        CDPClient(source.chrome_tab['webSocketDebuggerUrl']).send_command('Target.createTarget', {'url': 'file:///home/tom/Projects/tab2.html'})
        wait(lambda: len(tabs(source.chrome_port)) == 2)
        # Target creation precedes navigation and saved-session readiness.
        wait(lambda: any(t.get('url') == 'file:///home/tom/Projects/tab2.html'
            and source.token in t.get('title', '') for t in tabs(source.chrome_port)))
        source.stop()
        browser_port = port()
        chrome = ['/opt/google/chrome/chrome', '--no-sandbox', '--ozone-platform=x11',
            '--disable-gpu', '--disable-dev-shm-usage', '--disable-background-networking',
            '--disable-sync', '--no-first-run', '--no-default-browser-check', '--restore-last-session',
            '--user-data-dir=/home/tom/chrome-profile', f'--remote-debugging-port={browser_port}',
            '--remote-debugging-address=127.0.0.1', '--remote-allow-origins=*',
            '--window-size=1024,700']
        config = {'profiles': [{'id': 'chrome', 'state_dir': str(source.home),
            'argv': sandbox('{state_dir}', '{display}', chrome)}]}
        sid = store.capture(config)['snapshot']
        # Mutate only the owned, stopped synthetic source after the snapshot.
        (source.home/'Projects/demo.html').write_text('<title>changed after capture</title>')
        result = store.restore(sid, config, root/'recovered')
        target = NativeClone(root/'target-desktop', novnc)
        target.start()
        launcher.launch(config, result, f':{target.display}')
        tab = wait(lambda: next((t for t in tabs(browser_port) if t.get('url') == 'file:///home/tom/Projects/demo.html' and source.token in t.get('title', '')), None))
        assert value(tab, 'localStorage.getItem("uncrash-marker")') == token
        assert value(tab, 'document.getElementById("token").textContent') == source.token
        expected_urls = {'file:///home/tom/Projects/demo.html', 'file:///home/tom/Projects/tab2.html'}
        wait(lambda: {t['url'] for t in tabs(browser_port)} == expected_urls)
        assert {t['url'] for t in tabs(browser_port)} == expected_urls
        assert len(tabs(browser_port)) == 2
        CDPClient(tab['webSocketDebuggerUrl']).send_command('Page.bringToFront')
        env = {**os.environ, 'DISPLAY': f':{target.display}'}
        win = wait(lambda: subprocess.run(['xdotool', 'search', '--name', 'Twinerd clone '+source.token], env=env, capture_output=True, text=True).stdout.strip())
        subprocess.run(['xdotool', 'windowactivate', '--sync', win.splitlines()[0]], env=env, check=True)
        time.sleep(.5)
        viewer = CDPClient(target.viewer_tab['webSocketDebuggerUrl'])
        assert value(target.viewer_tab, 'window.connected') is True
        (root/'restored-chrome-novnc.png').write_bytes(viewer.capture_screenshot())
        proof['chrome'] = {'status': 'PASS', 'snapshot': sid, 'localStorage_restored': True,
            'original_html_restored': True, 'saved_tab_count': 2, 'saved_tab_urls_restored': True,
            'window_seen_on_owned_display': True, 'novnc_connected': True,
            'screenshot': 'restored-chrome-novnc.png'}
        launcher.stop()
        assert any(p.poll() is None for p in target.processes), 'Stopping recovered Chrome must preserve Twinerd desktop'

        terminal = root/'terminal-source'; terminal.mkdir()
        (terminal/'note.txt').write_text(token+'\nSaved terminal document restored by Uncrash.\n')
        config = {'profiles': [{'id': 'xterm', 'state_dir': str(terminal),
            'argv': sandbox('{state_dir}', '{display}', ['/usr/bin/xterm', '-T', token,
                '-geometry', '90x20', '-bg', '#245b43', '-fg', 'white', '-hold', '-e',
                '/usr/bin/cat', '/home/tom/note.txt'])}]}
        sid = store.capture(config)['snapshot']
        (terminal/'note.txt').write_text('changed after capture')
        result = store.restore(sid, config, root/'terminal-recovered')
        launcher.launch(config, result, f':{target.display}')
        win = wait(lambda: subprocess.run(['xdotool', 'search', '--name', token], env=env, capture_output=True, text=True).stdout.strip())
        subprocess.run(['xdotool', 'windowactivate', '--sync', win.splitlines()[0]], env=env, check=True)
        assert (root/'terminal-recovered/xterm/note.txt').read_text().startswith(token)
        time.sleep(.5)
        (root/'restored-xterm-novnc.png').write_bytes(viewer.capture_screenshot())
        proof['xterm'] = {'status': 'PASS_DURABLE_FILE_REPLAY', 'snapshot': sid,
            'saved_document_restored': True, 'window_seen_on_owned_display': True,
            'live_pty_restored': False, 'screenshot': 'restored-xterm-novnc.png'}
        launcher.stop()
        (root/'recovery-proof.json').write_text(json.dumps(proof, indent=2)+'\n')
    finally:
        try:
            launcher.stop()
        finally:
            if target:
                target.stop()
            if source.processes and any(p.poll() is None for p in source.processes):
                source.stop()


def test_portable_pycharm_files_launch_on_owned_twinerd_novnc(tmp_path):
    from uncrash.recovery import export_bundle, import_bundle
    from twinerd_native.session import NativeClone, value
    from twinerd_cdp import CDPClient
    executable = Path('/snap/pycharm-professional/current/bin/pycharm')
    if not executable.is_file():pytest.skip('Installed PyCharm needed for this owned fixture')
    source=tmp_path/'source';(source/'UncrashPyCharmRecovery').mkdir(parents=True);(source/'runtime').mkdir(mode=0o700)
    marker='UncrashPyCharmRecovery-'+tmp_path.name
    (source/'UncrashPyCharmRecovery/saved_editor.py').write_text('print('+repr(marker)+')\n')
    (source/'fixture.vmoptions').write_text('-Xms64m\n-Xmx512m\n-Didea.config.path=/home/tom/ide-config\n-Didea.system.path=/home/tom/ide-system\n-Didea.log.path=/home/tom/ide-log\n-Didea.plugins.path=/home/tom/ide-plugins\n-Dawt.toolkit.name=XToolkit\n')
    config={'profiles':[{'id':'pycharm','state_dir':str(source),'argv':[]}]}
    original=Store(tmp_path/'source-store');sid=original.capture(config)['snapshot']
    archive=tmp_path/'portable.tar';export_bundle(original,sid,archive)
    imported=import_bundle(archive,tmp_path/'target-store');cfg=json.loads(Path(imported['config']).read_text())
    store=Store(tmp_path/'target-store',cfg['origin']);receipt=store.restore(sid,cfg,tmp_path/'target-files')
    recovered=Path(receipt['restored'][0]['state_dir'])
    assert (recovered/'UncrashPyCharmRecovery/saved_editor.py').read_bytes()==(source/'UncrashPyCharmRecovery/saved_editor.py').read_bytes()
    desktop=NativeClone(tmp_path/'desktop',Path(os.environ['UNCRASH_NOVNC_ASSETS']));launcher=Launcher(store)
    proof={'file_state_roundtrip':True,'live_ram_or_host_terminal_restored':False,'personal_profiles_used':False}
    try:
        desktop.start();display=f':{desktop.display}'
        command=sandbox('{state_dir}','{display}',[
            '/bin/sh','-c','exec "$@" > /home/tom/fixture-launch.log 2>&1','fixture',
            '/usr/bin/dbus-run-session','--',str(executable),'/home/tom/UncrashPyCharmRecovery'])
        command[1:1]=['--unshare-net','--setenv','PYCHARM_VM_OPTIONS','/home/tom/fixture.vmoptions']
        cfg['profiles'][0]['argv']=command;launcher.launch(cfg,receipt,display)
        env={**os.environ,'DISPLAY':display}
        def project_windows():
            ids=subprocess.run(['xdotool','search','--onlyvisible','--class','pycharm'],env=env,capture_output=True,text=True).stdout.splitlines()
            titles=[subprocess.run(['xdotool','getwindowname',window],env=env,capture_output=True,text=True).stdout.strip() for window in ids]
            return titles if any(title and title not in ('splash','Content window') for title in titles) else None
        titles=wait(project_windows,timeout=90)
        assert value(desktop.viewer_tab,'window.connected') is True
        proof.update(ide_window_on_owned_display=True,novnc_connected=True,window_titles=titles,
            project_editor_view_verified=any('UncrashPyCharmRecovery' in title for title in titles),
            fidelity='portable file restoration plus IDE window; project/editor visibility recorded separately')
        artifacts=Path(os.environ.get('UNCRASH_NOVNC_ARTIFACTS',str(tmp_path)));artifacts.mkdir(parents=True,exist_ok=True)
        (artifacts/'portable-pycharm-novnc.png').write_bytes(CDPClient(desktop.viewer_tab['webSocketDebuggerUrl']).capture_screenshot())
    finally:
        launcher.stop();desktop.stop()
        artifacts=Path(os.environ.get('UNCRASH_NOVNC_ARTIFACTS',str(tmp_path)));artifacts.mkdir(parents=True,exist_ok=True)
        (artifacts/'portable-pycharm-proof.json').write_text(json.dumps(proof,indent=2)+'\n')
