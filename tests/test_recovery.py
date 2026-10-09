import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import sqlite3
import time
from datetime import datetime

import pytest

from uncrash.store import Store, RecoveryError
from uncrash.runtime import Launcher, recover_at_startup, run_daemon, start_ticks
from uncrash.inventory import desktop_inventory
from uncrash.contracts import process_export, parse_restore_action


@pytest.fixture
def fixture(tmp_path):
    source = tmp_path/'source'; source.mkdir()
    (source/'state.txt').write_text('saved-app-state')
    store = Store(tmp_path/'store', 'fixture-origin')
    config = {'encrypt': True, 'snapshot_engine': 'python', 'profiles': [{'id': 'app', 'state_dir': str(source), 'argv': []}]}
    return source, store, config


def test_encrypted_roundtrip_and_quarantine(fixture, tmp_path):
    source, store, config = fixture
    (source/'empty-directory').mkdir()
    sid = store.capture(config)['snapshot']
    assert all(b'saved-app-state' not in p.read_bytes() for p in (store.snapshots/sid).iterdir())
    destination = tmp_path/'restored'
    first = store.restore(sid, config, destination)
    assert first['completed']
    assert (destination/'app/state.txt').read_text() == 'saved-app-state'
    assert (destination/'app/empty-directory').is_dir()
    (destination/'app/state.txt').write_text('new unsaved work')
    result = store.restore(sid, config, destination, replace=True)
    assert (Path(result['pre_restore'][0])/'state.txt').read_text() == 'new unsaved work'
    assert (destination/'app/state.txt').read_text() == 'saved-app-state'
    assert (store.root/'key').stat().st_mode & 0o777 == 0o600


def test_corruption_refuses_before_target_change(fixture, tmp_path):
    _, store, config = fixture
    sid = store.capture(config)['snapshot']
    blob = next(p for p in (store.snapshots/sid).glob('*.enc') if p.name != 'manifest.enc')
    raw = bytearray(blob.read_bytes()); raw[-1] ^= 1; blob.write_bytes(raw)
    destination = tmp_path/'restored'; (destination/'app').mkdir(parents=True)
    (destination/'app/state.txt').write_text('preserve current work')
    with pytest.raises(RecoveryError, match='authentication'):
        store.restore(sid, config, destination, replace=True)
    assert (destination/'app/state.txt').read_text() == 'preserve current work'


def test_secrets_excluded_and_symlinks_refused(fixture, tmp_path):
    source, store, config = fixture
    (source/'auth.json').write_text('secret credential')
    (source/'antigravity-oauth-token').write_text('synthetic credential')
    (source/'.credentials.json').write_text('synthetic credential')
    (source/'.ssh').mkdir(); (source/'.ssh/key').write_text('private-key')
    sid = store.capture(config)['snapshot']
    dest = tmp_path/'restore'; store.restore(sid, config, dest)
    assert not (dest/'app/auth.json').exists()
    assert not (dest/'app/antigravity-oauth-token').exists()
    assert not (dest/'app/.credentials.json').exists()
    assert not (dest/'app/.ssh').exists()
    (source/'link').symlink_to(tmp_path)
    with pytest.raises(RecoveryError):
        store.capture(config)
    assert len(store.list()) == 1


def test_wrong_origin_and_key_permissions(fixture, tmp_path):
    _, store, config = fixture
    sid = store.capture(config)['snapshot']
    store.origin = 'different-machine'
    with pytest.raises(RecoveryError):
        store.restore(sid, config, tmp_path/'restored')
    store.origin = 'fixture-origin'; os.chmod(store.root/'key', 0o644)
    with pytest.raises(RecoveryError, match='0600'):
        store.capture(config)


def test_budget_and_retention(fixture):
    source, store, config = fixture
    config['retention'] = 2
    for text in ['one', 'two', 'three']:
        (source/'state.txt').write_text(text); store.capture(config)
    assert len(store.list()) == 2
    config['max_bytes'] = 1
    with pytest.raises(RecoveryError, match='budget'):
        store.capture(config)
    assert len(store.list()) == 2


def test_startup_skips_corrupted_snapshot_and_recovers_once(fixture, tmp_path):
    _, store, config = fixture
    good = store.capture(config)['snapshot']
    bad = store.capture(config)['snapshot']
    if bad < good:
        good, bad = bad, good
    (store.snapshots/bad/'manifest.enc').write_bytes(b'corrupt')
    config.update(startup_restore=True, recovery_destination=str(tmp_path/'startup'))
    result = recover_at_startup(store, config)
    assert result['status'] == 'restored'
    assert result['receipt']['snapshot'] == good
    assert result['invalid_snapshots_skipped'] == 1
    assert recover_at_startup(store, config)['status'] == 'already-recovered-this-boot'


def test_owned_stop_preserves_unrelated_process_and_refuses_pid_reuse(fixture, tmp_path):
    _, store, config = fixture
    outside = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(60)'])
    try:
        config['profiles'][0]['argv'] = [sys.executable, '-c', 'import time;time.sleep(60)']
        sid = store.capture(config)['snapshot']; result = store.restore(sid, config, tmp_path/'restored')
        launcher = Launcher(store)
        launched = launcher.launch(config, result, ':999')
        launcher.stop(); assert outside.poll() is None
        launcher.save([{'id': 'app', 'pid': outside.pid, 'start_ticks': 'incorrect'}])
        with pytest.raises(RecoveryError, match='identity changed'):
            launcher.stop()
        assert outside.poll() is None
    finally:
        outside.terminate(); outside.wait()


def test_desktop_inventory_does_not_execute_exec(tmp_path):
    (tmp_path/'dangerous.desktop').write_text('[Desktop Entry]\nType=Application\nName=fixture\nExec=sh -c "touch forbidden-file"\n')
    result = desktop_inventory([tmp_path])
    assert result[0]['restore_status'] == 'UNTESTED'
    assert not (tmp_path/'forbidden-file').exists()


def test_daemon_captures_immediately_and_waits_five_minutes(fixture):
    _, store, config = fixture
    class Stop:
        done = False
        def is_set(self): return self.done
        def wait(self, seconds):
            assert 299 <= seconds <= 300
            self.done = True
    run_daemon(store, config, stop=Stop())
    assert len(store.list()) == 1


def test_total_encrypted_storage_budget(fixture):
    _, store, config = fixture
    config['max_total_bytes'] = 1
    with pytest.raises(RecoveryError, match='total storage budget'):
        store.capture(config)
    assert not store.list()


def test_online_sqlite_backup_includes_committed_wal_and_omits_pending_transaction(fixture, tmp_path):
    source, store, config = fixture
    config['profiles'][0]['sqlite_backup_files'] = ['chat.db']
    connection = sqlite3.connect(source/'chat.db')
    try:
        assert connection.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
        connection.execute('CREATE TABLE messages (text TEXT)')
        connection.execute('INSERT INTO messages VALUES (?)', ('committed saved chat',))
        connection.commit()
        connection.execute('INSERT INTO messages VALUES (?)', ('uncommitted text',))
        assert (source/'chat.db-wal').exists()
        sid = store.capture(config)['snapshot']
        store.restore(sid, config, tmp_path/'restored')
        restored = tmp_path/'restored/app'
        assert not (restored/'chat.db-wal').exists() and not (restored/'chat.db-shm').exists()
        with sqlite3.connect(restored/'chat.db') as db:
            assert db.execute('SELECT text FROM messages').fetchall() == [('committed saved chat',)]
            assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        _, _, _, manifest = store.load(sid)
        assert next(f for f in manifest['profiles'][0]['files'] if f['path']=='chat.db')['capture_method'] == 'sqlite-online-backup'
    finally:
        connection.close()


def test_sqlite_profile_paths_and_byte_bounds(fixture):
    source, store, config = fixture
    for paths in [['../outside.db'], ['/outside.db'], ['chat.db', 'chat.db'], 'chat.db']:
        config['profiles'][0]['sqlite_backup_files'] = paths
        with pytest.raises(RecoveryError, match='relative paths'):
            store.capture(config)
    config['profiles'][0]['sqlite_backup_files'] = ['missing.db']
    with pytest.raises(RecoveryError, match='missing or excluded'):
        store.capture(config)
    config['profiles'][0]['sqlite_backup_files'] = ['chat.db']
    with sqlite3.connect(source/'chat.db') as db:
        db.execute('CREATE TABLE messages (text TEXT)')
    config['max_file_bytes'] = 4096
    with pytest.raises(RecoveryError, match='bounded regular|byte budget'):
        store.capture(config)
    assert not store.list()


def test_uri_refuses_shell_and_duplicate_fields():
    for uri in ['shell://run?command=rm', 'action://uncrash/restore?snapshot=latest&destination=/tmp&command=id',
                'action://uncrash/restore?snapshot=latest&snapshot=latest',
                'action://uncrash/restore?snapshot=latest&destination=relative']:
        with pytest.raises(RecoveryError):
            parse_restore_action(uri)
    assert parse_restore_action('action://uncrash/restore?snapshot=latest&destination=%2Ftmp%2Ffixture')[1] == Path('/tmp/fixture')


def test_matrix_does_not_conflate_snap_launchers(tmp_path):
    from uncrash.inventory import classify_inventory
    driver = tmp_path/'snap'; driver.write_text('shared launcher')
    one = tmp_path/'one'; one.symlink_to(driver)
    two = tmp_path/'two'; two.symlink_to(driver)
    inventory = [{'executable': str(two), 'executable_present': True}]
    rows = [{'executable': str(one), 'status': 'DATA_AND_WINDOW_PASS', 'reason': 'only one was tested'}]
    assert classify_inventory(inventory, rows)[0]['restore_status'] == 'ADAPTER_OR_FIXTURE_REQUIRED'


def test_process_export_is_honest_about_chat_fidelity(fixture):
    _, store, config = fixture
    sid = store.capture(config)['snapshot']
    exported = process_export(store, sid)
    assert exported['schema'] == 'wellmanifest.conversational-process-snapshot/v1'
    assert exported['chat'] == {'messageCount': 0, 'messages': []}
    assert exported['state']['chatAdapterAvailable'] is False
    schema_path = os.environ.get('UNCRASH_CPI_SCHEMA')
    if schema_path:
        import jsonschema
        jsonschema.validate(exported, json.loads(Path(schema_path).read_text()))


@pytest.mark.skipif(os.environ.get('UNCRASH_SYSTEMD_TEST') != '1', reason='Opt-in test of the installed user service, including real five-minute wait')
def test_installed_service_restart_and_real_five_minute_capture():
    unit = Path.home()/'.config/systemd/user/uncrash.service'
    assert 'uncrash.cli' in unit.read_text()
    assert str(Path(sys.executable).parent) in unit.read_text()
    config = json.loads((Path.home()/'.config/uncrash/config.json').read_text())
    assert config['profiles'] == [], 'This lifecycle fixture only uses metadata, never personal app data'
    store = Store(Path.home()/'.local/state/uncrash')
    def until(probe, seconds):
        end = time.monotonic()+seconds
        while time.monotonic() < end:
            result = probe()
            if result:
                return result
            time.sleep(.5)
        raise AssertionError('Installed user service readiness timeout')
    first = until(store.list, 30)[-1]
    pid = int(subprocess.check_output(['systemctl', '--user', 'show', 'uncrash.service', '--property=MainPID', '--value']))
    identity = start_ticks(pid)
    assert 'uncrash.cli' in Path(f'/proc/{pid}/cmdline').read_bytes().decode().replace('\x00', ' ')
    assert identity == start_ticks(pid)
    # systemd targets only this named unit's main process; no application signals.
    subprocess.run(['systemctl', '--user', 'kill', '--kill-whom=main', '--signal=KILL', 'uncrash.service'], check=True)
    second = until(lambda: next((s for s in store.list() if s > first), None), 30)
    new_pid = int(subprocess.check_output(['systemctl', '--user', 'show', 'uncrash.service', '--property=MainPID', '--value']))
    assert new_pid != pid
    third = until(lambda: next((s for s in store.list() if s > second), None), 320)
    manifests = [store.load(s)[3] for s in [first, second, third]]
    cadence = (datetime.fromisoformat(manifests[2]['created_at'])-datetime.fromisoformat(manifests[1]['created_at'])).total_seconds()
    assert 299 <= cadence <= 320
    assert all(m['profiles'] == [] for m in manifests)
    receipt = {'service_active': True, 'restart_after_kill': True, 'cadence_seconds': cadence,
        'snapshots': [first, second, third], 'profile_count': 0, 'personal_app_data_backed_up': False}
    path = Path(os.environ['UNCRASH_SERVICE_RECEIPT'])
    path.write_text(json.dumps(receipt, indent=2)+'\n')
