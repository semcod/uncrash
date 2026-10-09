"""Opt-in real local backends, discovered with semcod/search; synthetic data only."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sqlite3
import sys
import time
import uuid
import xml.etree.ElementTree as ET

import pytest

from uncrash.store import RecoveryError, Store
from test_novnc import wait


pytestmark = pytest.mark.skipif(os.environ.get('UNCRASH_LOCAL_BACKENDS') != '1', reason='Opt-in local CloneBox/Clonerd/vnclone runtime fixtures')


def artifact(name):
    root = Path(os.environ['UNCRASH_BACKEND_ARTIFACTS'])/name
    root.mkdir(parents=True, mode=0o700, exist_ok=False)
    return root


def test_clonerd_transfers_encrypted_snapshot_and_requires_separate_key():
    from clonerd import clone_tree
    root = artifact('clonerd')
    source = root/'profile'; source.mkdir()
    (source/'document.txt').write_text('original synthetic document')
    config = {'encrypt': True, 'profiles': [{'id': 'app', 'state_dir': str(source)}]}
    store = Store(root/'source-store', 'clonerd-fixture')
    sid = store.capture(config)['snapshot']
    report = clone_tree(store.root, root/'transferred-store', excludes=('key', 'lock'), verify=True)
    transferred = Store(root/'transferred-store', 'clonerd-fixture')
    with pytest.raises(RecoveryError, match='authentication'):
        transferred.restore(sid, config, root/'without-key')
    # Only this fixture's own generated key is deliberately transferred.
    (transferred.root/'key').write_bytes((store.root/'key').read_bytes())
    os.chmod(transferred.root/'key', 0o600)
    restored = transferred.restore(sid, config, root/'recovered')
    assert (root/'recovered/app/document.txt').read_text() == 'original synthetic document'
    assert restored['completed']
    (root/'proof.json').write_text(json.dumps({'status': 'PASS', 'verified_files': report.files_verified,
        'encrypted_snapshot_transferred': True, 'restore_without_key_refused': True,
        'own_fixture_key_transferred_separately': True, 'document_restored': True}, indent=2)+'\n')


def test_vnclone_manifest_recovery_and_browser_adapter_conformance():
    from twinerd_native.session import NativeClone, tabs, port, value
    from twinerd_cdp import CDPClient
    from vnclone.lifecycle import ChromiumAppAdapter, AppStateSnapshot
    from vnclone.orchestrator import SequentialAppOrchestrator
    from vnclone.state import AppSessionItem, SessionManifest, SessionStateManager
    root = artifact('vnclone')
    clone = NativeClone(root/'desktop', Path(os.environ['UNCRASH_NOVNC_ASSETS']))
    proof = {'personal_profiles_used': False, 'provider_chat_resume_verified': False}
    try:
        clone.start()
        (clone.home/'Projects/second.html').write_text('<title>Uncrash second document</title><h1>Saved second tab</h1>')
        CDPClient(clone.chrome_tab['webSocketDebuggerUrl']).send_command('Target.createTarget', {'url': 'file:///home/tom/Projects/second.html'})
        wait(lambda: len(tabs(clone.chrome_port)) == 2)
        adapter = ChromiumAppAdapter()
        snapshot = adapter.snapshot(cdp_port=clone.chrome_port)
        assert len(snapshot.session_data['tabs']) == 2
        manager = SessionStateManager('uncrash-fixture', root/'state')
        manifest = SessionManifest('uncrash-fixture', time.time(), '2026-10-08T00:00:00Z', 'fixture',
            display=f':{clone.display}', applications=[AppSessionItem('browser', 'Chrome', 'gui',
                session_data={'browser_snapshot': snapshot.to_dict()})])
        manager.save_manifest(manifest)
        store = Store(root/'encrypted-store', 'vnclone-fixture')
        config = {'encrypt': True, 'profiles': [{'id': 'vnclone', 'state_dir': str(manager.session_dir)}]}
        sid = store.capture(config)['snapshot']
        manager.manifest_path().write_text('corrupted after backup')
        store.restore(sid, config, root/'recovered')
        recovered = SessionStateManager('uncrash-fixture', root/'recovered/vnclone').load_manifest()
        assert recovered and len(recovered.applications) == 1
        snapshot = AppStateSnapshot.from_dict(recovered.applications[0].session_data['browser_snapshot'])
        # Probe actual adapter results against actual owned browser state.
        assert adapter.restore(snapshot) is True
        assert wait(lambda: len(tabs(clone.chrome_port)) >= 4)
        proof['native_adapter'] = {'status': 'BUG_CONFIRMED', 'returns_success': True,
            'tab_count_after_restore': len(tabs(clone.chrome_port)), 'expected_tabs': 2,
            'reason': 'restore appends tabs to an already-restored profile'}
        missing = AppStateSnapshot.from_dict(snapshot.to_dict())
        missing.session_data['cdp_port'] = port()
        assert adapter.restore(missing) is True
        proof['unreachable_endpoint'] = {'status': 'BUG_CONFIRMED', 'returns_success_without_browser': True}
        orchestrator = SequentialAppOrchestrator(display=f':{clone.display}')
        counts = []
        for _ in range(2):
            orchestrator._restore_browser_tabs(clone.chrome_port, snapshot.session_data['tabs'])
            wait(lambda: len(tabs(clone.chrome_port)) == 2)
            assert {t['url'] for t in tabs(clone.chrome_port)} == {t['url'] for t in snapshot.session_data['tabs']}
            counts.append(len(tabs(clone.chrome_port)))
        proof['orchestrator'] = {'status': 'PASS_TAB_SET_AND_COUNT', 'tab_counts': counts,
            'tab_order_verified': False, 'native_session_ram_verified': False}
        main = next(t for t in tabs(clone.chrome_port) if t['url'].endswith('/demo.html'))
        assert value(main, 'document.getElementById("token").textContent') == clone.token
        CDPClient(main['webSocketDebuggerUrl']).send_command('Page.bringToFront')
        time.sleep(.4)
        assert value(clone.viewer_tab, 'window.connected') is True
        (root/'restored-vnclone-novnc.png').write_bytes(CDPClient(clone.viewer_tab['webSocketDebuggerUrl']).capture_screenshot())
        proof.update(manifest_restored_from_encrypted_snapshot=True, novnc_connected=True)
        (root/'proof.json').write_text(json.dumps(proof, indent=2)+'\n')
    finally:
        clone.stop()


def test_vnclone_synthetic_agy_database_roundtrip_excludes_oauth(monkeypatch):
    from vnclone.state import SessionStateManager
    from vnclone.lifecycle import AgyAgentAdapter
    root = artifact('agy-data')
    source_home = root/'source-home'; source_home.mkdir()
    target_home = root/'target-home'; target_home.mkdir()
    monkeypatch.setenv('HOME', str(source_home))
    cli = source_home/'.gemini/antigravity-cli'; (cli/'conversations').mkdir(parents=True)
    conversation = str(uuid.uuid4())
    workspace = str(root/'synthetic-project')
    with sqlite3.connect(cli/'conversation_summaries.db') as db:
        db.execute('CREATE TABLE conversation_summaries (conversation_id TEXT, workspace_uris TEXT, last_modified_time INTEGER)')
        db.execute('INSERT INTO conversation_summaries VALUES (?,?,?)', (conversation, workspace, 1))
    with sqlite3.connect(cli/'conversations'/(conversation+'.db')) as db:
        db.execute('CREATE TABLE fixture_messages (text TEXT)')
        db.execute('INSERT INTO fixture_messages VALUES (?)', ('Synthetic saved conversation, not a real provider session',))
    (cli/'history.jsonl').write_text(json.dumps({'conversation_id': conversation})+'\n')
    (cli/'antigravity-oauth-token').write_text('synthetic-token-must-not-be-transferred')
    assert AgyAgentAdapter().get_latest_conversation_id(workspace) == conversation
    manager = SessionStateManager('uncrash-fixture', root/'state')
    manager.backup_artifacts([conversation])
    store = Store(root/'encrypted-store', 'agy-fixture')
    config = {'encrypt': True, 'profiles': [{'id': 'agy-state', 'state_dir': str(manager.session_dir),
        'sqlite_backup_files': ['session-artifacts/agy/conversation_summaries.db',
            'session-artifacts/agy/conversations/'+conversation+'.db']}]}
    sid = store.capture(config)['snapshot']
    store.restore(sid, config, root/'recovered')
    monkeypatch.setenv('HOME', str(target_home))
    target = SessionStateManager('uncrash-fixture', root/'recovered/agy-state')
    target.restore_artifacts()
    assert AgyAgentAdapter().get_latest_conversation_id(workspace) == conversation
    restored = target_home/'.gemini/antigravity-cli'
    with sqlite3.connect(restored/'conversations'/(conversation+'.db')) as db:
        assert db.execute('SELECT text FROM fixture_messages').fetchone()[0].startswith('Synthetic saved conversation')
    assert not (restored/'antigravity-oauth-token').exists()
    (root/'proof.json').write_text(json.dumps({'status': 'PASS_SYNTHETIC_AGY_DATA',
        'native_conversation_id_reader_verified': True, 'sqlite_and_history_restored': True,
        'oauth_token_excluded': True, 'actual_agy_provider_resume_executed': False,
        'sqlite_live_wal_consistency_tested': False}, indent=2)+'\n')


BOOT_SOURCE = r'''.code16
.global _start
_start:
    cli
    xor %ax,%ax
    mov %ax,%ds
    mov %ax,%ss
    mov $0x7c00,%sp
    sti
    mov $0x0003,%ax
    int $0x10
    mov $0x2607,%cx
    mov $0x01,%ah
    int $0x10
    mov $banner,%si
print:
    lodsb
    test %al,%al
    jz keyboard
    mov $0x0e,%ah
    xor %bx,%bx
    int $0x10
    jmp print
keyboard:
    xor %ax,%ax
    int $0x16
    test %al,%al
    jz keyboard
    mov $0x0e,%ah
    xor %bx,%bx
    int $0x10
    jmp keyboard
banner:
    .asciz "Uncrash VM RAM fixture (synthetic boot program, not an OS or live PTY)\r\nMemory-only keyboard text: "
.org 510
.word 0xaa55
'''


PTY_BRIDGE = r'''
#define _GNU_SOURCE
#include <pty.h>
#include <unistd.h>
#include <stdlib.h>
#include <stdio.h>
#include <sys/select.h>
#include <sys/ioctl.h>
#include <termios.h>
int main(void) {
    int master; pid_t child = forkpty(&master, NULL, NULL, NULL);
    if (child < 0) { perror("forkpty"); return 1; }
    if (!child) {
        setenv("TERM", "linux", 1);
        execl("/bin/busybox", "busybox", "sh", "-i", NULL);
        _exit(1);
    }
    struct termios original, raw;
    if (tcgetattr(0, &original) == 0) { raw = original; cfmakeraw(&raw); tcsetattr(0, TCSANOW, &raw); }
    for (;;) {
        fd_set readers; FD_ZERO(&readers); FD_SET(0, &readers); FD_SET(master, &readers);
        if (select(master+1, &readers, NULL, NULL, NULL) < 0) break;
        char data[4096]; ssize_t size;
        if (FD_ISSET(0, &readers)) {
            size = read(0, data, sizeof(data)); if (size <= 0) break;
            for (ssize_t n = 0; n < size; n++) if (write(master, data+n, 1) != 1) return 1;
        }
        if (FD_ISSET(master, &readers)) {
            size = read(master, data, sizeof(data)); if (size <= 0) break;
            for (ssize_t n = 0; n < size; n++) if (write(1, data+n, 1) != 1) return 1;
        }
    }
    return 0;
}
'''


def linux_boot_files(root, payload):
    """Build a private initramfs from explicit system binaries; no user HOME."""
    kernel = Path(os.environ.get('UNCRASH_LINUX_KERNEL', ''))
    if not kernel.is_file():
        pytest.skip('Optional Linux kernel fixture not supplied')
    assert kernel.read_bytes()[0x202:0x206] == b'HdrS'
    shutil.copyfile(kernel, payload/'linux')
    tree = root/'initramfs'; (tree/'bin').mkdir(parents=True)
    for name in ['dev', 'proc', 'sys', 'tmp']: (tree/name).mkdir()
    shutil.copyfile('/usr/bin/busybox', tree/'bin/busybox'); os.chmod(tree/'bin/busybox', 0o755)
    (root/'pty.c').write_text(PTY_BRIDGE)
    subprocess.run(['gcc', '-static', '-O2', '-o', str(tree/'bin/pty'), str(root/'pty.c'), '-lutil'], check=True)
    (tree/'init').write_text('#!/bin/busybox sh\n/bin/busybox mount -t proc proc /proc\n'
        '/bin/busybox mount -t sysfs sysfs /sys\n/bin/busybox mount -t devtmpfs devtmpfs /dev\n'
        '/bin/busybox mkdir -p /dev/pts\n/bin/busybox mount -t devpts devpts /dev/pts\n'
        'echo "Uncrash Linux PTY fixture; synthetic data only"\nexec /bin/pty\n')
    os.chmod(tree/'init', 0o755)
    names = ['.', *[p.relative_to(tree).as_posix() for p in sorted(tree.rglob('*'))]]
    with (payload/'initramfs.cpio').open('wb') as output:
        subprocess.run(['cpio', '--null', '-o', '--format=newc', '--quiet'],
            input=('\0'.join(names)+'\0').encode(), cwd=tree, stdout=output, check=True)
    return (f'<kernel>{payload}/linux</kernel><initrd>{payload}/initramfs.cpio</initrd>'
        '<cmdline>console=tty0 quiet rdinit=/init panic=-1 nokaslr</cmdline>')


def guest_type(rfb, text, guest_kind):
    # Linux console keymaps need actual Shift events for shifted punctuation.
    shifted = dict(zip('~!@#$%^&*()_+{}|:"<>?', '`1234567890-=[]\\;\',./'))
    for character in text.rstrip('\n'):
        if guest_kind == 'linux-pty' and character in shifted:
            rfb.key_combo('shift+'+shifted[character])
        else:
            rfb.type_text(character)
    if guest_kind == 'linux-pty': rfb.press_key('enter')


@pytest.mark.parametrize('guest_kind', ['bios', 'linux-pty'])
def test_clonebox_full_ram_snapshot_survives_guest_crash_and_uncrash_restore(guest_kind):
    # The apt CPython 3.13 extension is used only by this optional test.
    sys.path.append('/usr/lib/python3/dist-packages')
    import libvirt
    import libvirt_qemu
    from clonebox.snapshots import SnapshotManager, SnapshotType
    from twinerd_native.session import child_environment, port
    from twinerd_runtime.rfb import RFBClient
    from playwright.sync_api import sync_playwright
    root = artifact('clonebox' if guest_kind == 'bios' else 'clonebox-linux-pty')
    payload = root/'payload'; payload.mkdir()
    name = 'uncrash-ram-'+uuid.uuid4().hex[:12]
    identity = str(uuid.uuid4())
    asm = root/'boot.S'; asm.write_text(BOOT_SOURCE)
    subprocess.run(['as', '--32', '-o', str(root/'boot.o'), str(asm)], check=True)
    subprocess.run(['ld', '-m', 'elf_i386', '-Ttext', '0x7c00', '--oformat', 'binary',
        '-o', str(root/'boot.bin'), str(root/'boot.o')], check=True)
    boot = (root/'boot.bin').read_bytes()
    assert len(boot) == 512 and boot[-2:] == b'\x55\xaa'
    raw = root/'boot.raw'
    with raw.open('wb') as stream:
        stream.write(boot); stream.truncate(16*1024*1024)
    disk = payload/'disk.qcow2'
    subprocess.run(['qemu-img', 'convert', '-f', 'raw', '-O', 'qcow2', str(raw), str(disk)], check=True)
    boot_extra = linux_boot_files(root, payload) if guest_kind == 'linux-pty' else '<boot dev="hd"/>'
    memory = 256 if guest_kind == 'linux-pty' else 32
    xml = f'''<domain type="kvm"><name>{name}</name><uuid>{identity}</uuid>
      <memory unit="MiB">{memory}</memory><vcpu>1</vcpu>
      <os><type arch="x86_64" machine="pc">hvm</type>{boot_extra}</os>
      <devices><emulator>/usr/bin/qemu-system-x86_64</emulator>
      <disk type="file" device="disk"><driver name="qemu" type="qcow2"/><source file="{disk}"/><target dev="vda" bus="virtio"/></disk>
      <graphics type="vnc" autoport="yes" listen="127.0.0.1"/><video><model type="vga"/></video>
      <input type="keyboard" bus="ps2"/></devices></domain>'''
    manager = SnapshotManager('qemu:///session')
    manager._snapshots_dir = root/'metadata'; manager._snapshots_dir.mkdir()
    connection = manager.conn
    initial = {d.UUIDString(): d.isActive() for d in connection.listAllDomains()}
    assert identity not in initial
    domain = None
    bridge = None
    def owned():
        assert domain and domain.UUIDString() == identity and domain.name() == name
    def memory_text():
        owned()
        response = libvirt_qemu.qemuMonitorCommand(domain, json.dumps({'execute': 'human-monitor-command',
            'arguments': {'command-line': 'xp /4000bx 0xb8000'}}), 0)
        import re
        output = json.loads(response)['return']
        cells = bytes(int(v, 16) for line in output.splitlines() if ':' in line
            for v in re.findall(r'0x([a-fA-F0-9]{2})\b', line.split(':', 1)[1]))
        return cells[::2].decode('ascii', errors='replace')
    def vnc_port():
        return int(ET.fromstring(domain.XMLDesc()).find('.//graphics').get('port'))
    try:
        domain = connection.defineXML(xml); owned(); domain.create()
        ready = 'Uncrash Linux PTY fixture' if guest_kind == 'linux-pty' else 'Memory-only keyboard text:'
        wait(lambda: ready in memory_text())
        command = ('export UNCRASH_MEMORY=SAVEDRAM; echo "before:$UNCRASH_MEMORY:$$:$(/bin/busybox tty)"\n'
            if guest_kind == 'linux-pty' else 'SAVEDRAM')
        with RFBClient(port=vnc_port()) as rfb:
            guest_type(rfb, command, guest_kind)
        wait(lambda: 'before:SAVEDRAM:' in memory_text() if guest_kind == 'linux-pty' else 'SAVEDRAM' in memory_text())
        if guest_kind == 'linux-pty': assert '/dev/pts/0' in memory_text()
        before = memory_text()
        snap = manager.create(name, 'before-crash', snapshot_type=SnapshotType.FULL)
        assert snap.snapshot_type == SnapshotType.FULL
        (payload/'domain.xml').write_text(domain.XMLDesc(libvirt.VIR_DOMAIN_XML_INACTIVE))
        (payload/'snapshot.xml').write_text(domain.snapshotLookupByName('before-crash').getXMLDesc())
        mutation = 'export UNCRASH_MEMORY=MUTATED; echo "mutation:$UNCRASH_MEMORY"\n' if guest_kind == 'linux-pty' else 'MUTATED'
        with RFBClient(port=vnc_port()) as rfb:
            guest_type(rfb, mutation, guest_kind)
        wait(lambda: 'mutation:MUTATED' in memory_text() if guest_kind == 'linux-pty' else 'SAVEDRAMMUTATED' in memory_text())
        owned(); domain.destroy()
        store = Store(root/'encrypted-store', 'clonebox-fixture')
        config = {'encrypt': True, 'profiles': [{'id': 'vm', 'state_dir': str(payload)}],
            'max_file_bytes': 512*1024*1024, 'max_bytes': 1024*1024*1024}
        sid = store.capture(config)['snapshot']
        domain.undefineFlags(libvirt.VIR_DOMAIN_UNDEFINE_SNAPSHOTS_METADATA)
        domain = None
        result = store.restore(sid, config, root/'recovered')
        assert result['completed']
        recovered = root/'recovered/vm'
        def remap(text):
            element = ET.fromstring(text)
            for source in element.iter('source'):
                if source.get('file') == str(disk): source.set('file', str(recovered/'disk.qcow2'))
            for node in element.iter():
                if node.tag in {'kernel', 'initrd'} and node.text in {str(payload/'linux'), str(payload/'initramfs.cpio')}:
                    node.text = str(recovered/Path(node.text).name)
            return ET.tostring(element, encoding='unicode')
        domain = connection.defineXML(remap((recovered/'domain.xml').read_text())); owned()
        domain.snapshotCreateXML(remap((recovered/'snapshot.xml').read_text()),
            libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_REDEFINE | libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_CURRENT)
        assert manager.restore(name, 'before-crash') is True
        wait(lambda: domain.isActive())
        after = memory_text()
        assert 'SAVEDRAM' in after and 'MUTATED' not in after and before == after
        shell_identity = None
        if guest_kind == 'linux-pty':
            import re
            shell_identity = re.search(r'before:SAVEDRAM:(\d+):(/dev/pts/\d+)', before).groups()
            with RFBClient(port=vnc_port()) as rfb:
                guest_type(rfb, 'echo "after:$UNCRASH_MEMORY:$$:$(/bin/busybox tty)"', guest_kind)
            expected = 'after:SAVEDRAM:'+':'.join(shell_identity)
            wait(lambda: expected in memory_text())
            assert 'mutation:MUTATED' not in memory_text()
        bridge_port = port()
        with (root/'bridge.log').open('wb') as log:
            bridge = subprocess.Popen(['twinerd-bridge', '--listen', f'127.0.0.1:{bridge_port}',
                '--target', f'127.0.0.1:{vnc_port()}', '--web', os.environ['UNCRASH_NOVNC_ASSETS']],
                env=child_environment(root), stdout=log, stderr=subprocess.STDOUT)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='/opt/google/chrome/chrome',
                headless=True, env=child_environment(root), args=['--disable-background-networking'])
            try:
                page = browser.new_page(viewport={'width': 1100, 'height': 850})
                page.goto(f'http://127.0.0.1:{bridge_port}/vnc.html?autoconnect=true&resize=scale')
                page.wait_for_function('document.documentElement.classList.contains("noVNC_connected") && document.querySelector("canvas")?.width > 100', timeout=30000)
                time.sleep(.5)
                page.screenshot(path=str(root/'restored-vm-ram-novnc.png'))
            finally:
                browser.close()
        (root/'proof.json').write_text(json.dumps({'status': 'PASS_LINUX_LIVE_PTY' if guest_kind == 'linux-pty' else 'PASS_VM_RAM_PRIMITIVE',
            'manager_api': 'CloneBox SnapshotManager FULL', 'guest_crash_simulated': True,
            'encrypted_uncrash_snapshot': sid, 'disk_and_libvirt_metadata_restored': True,
            'memory_only_text_restored': True, 'post_snapshot_mutation_absent': True,
            'novnc_rendered': True, 'live_pty_tested': guest_kind == 'linux-pty',
            'restored_shell_pid_and_pty': shell_identity,
            'installed_gui_apps_or_provider_sessions_tested': False,
            'guest': 'Owned synthetic Linux/BusyBox initramfs' if guest_kind == 'linux-pty' else 'Owned synthetic BIOS boot program',
            'network_host_mounts_or_credentials': False}, indent=2)+'\n')
    except BaseException:
        if domain and domain.isActive():
            (root/'failure-vga-text.txt').write_text(memory_text())
        raise
    finally:
        if bridge:
            bridge.terminate(); bridge.wait(timeout=10)
        if domain:
            owned()
            if domain.isActive(): domain.destroy()
            domain.undefineFlags(libvirt.VIR_DOMAIN_UNDEFINE_SNAPSHOTS_METADATA)
        for ident, active in initial.items():
            assert connection.lookupByUUIDString(ident).isActive() == active
        connection.close()
