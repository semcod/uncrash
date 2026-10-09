import json
import os
from pathlib import Path
import sqlite3

import pytest

from uncrash.native import discover, selected_config, save_config
from uncrash.store import Store, RecoveryError
from uncrash.runtime import run_daemon


def test_native_selection_is_explicit_and_preserves_existing_config(tmp_path):
    (tmp_path/'.codex/sessions').mkdir(parents=True)
    (tmp_path/'.claude/projects').mkdir(parents=True)
    config = {'profiles': [], 'startup_restore': False, 'retention': 7}
    assert len(discover(tmp_path)) == 2
    selected = selected_config(config, ['codex-sessions'], tmp_path)
    assert not config['profiles']
    assert selected['retention'] == 7 and selected['startup_restore'] is False
    assert selected['compress'] is False
    with pytest.raises(RecoveryError): selected_config(config, ['unavailable'], tmp_path)
    with pytest.raises(RecoveryError): selected_config(selected, ['codex-sessions'], tmp_path)
    path = tmp_path/'configuration/config.json';path.parent.mkdir()
    path.write_text(json.dumps(config));os.chmod(path, 0o600)
    save_config(path, selected)
    assert json.loads(next(path.parent.glob('*.pre-uncrash-*')).read_text()) == config
    assert path.stat().st_mode & 0o777 == 0o600


def test_native_codex_multilevel_sessions_compressed_and_credentials_omitted(tmp_path):
    root = tmp_path/'home';source = root/'.codex';logs = source/'sessions/2026/10/08';logs.mkdir(parents=True)
    text = json.dumps({'synthetic': 'saved text '*50000})+'\n'
    (logs/'session.jsonl').write_text(text)
    (source/'auth.json').write_text('synthetic-credential')
    (source/'plugins').symlink_to(tmp_path/'outside')
    with sqlite3.connect(source/'state_5.sqlite') as db: db.execute('CREATE TABLE threads(id TEXT)')
    config = selected_config({'profiles': [], 'compress': True}, ['codex-sessions'], root)
    store = Store(tmp_path/'store', 'native-test');sid = store.capture(config)['snapshot']
    _, _, _, manifest = store.load(sid)
    files = manifest['profiles'][0]['files']
    assert {f['path'] for f in files} == {'sessions/2026/10/08/session.jsonl', 'state_5.sqlite'}
    assert next(f for f in files if f['path'].endswith('jsonl'))['encoding'] == 'zlib'
    compressed = next(f for f in files if f['path'].endswith('jsonl'))
    assert (store.snapshots/sid/compressed['blob']).stat().st_size < len(text)//10
    store.restore(sid, config, tmp_path/'restored')
    assert (tmp_path/'restored/codex-sessions/sessions/2026/10/08/session.jsonl').read_text() == text
    assert not (tmp_path/'restored/codex-sessions/auth.json').exists()


def test_sqlite_globs_include_new_live_databases_and_skip_sidecars(tmp_path):
    source = tmp_path/'source';source.mkdir();(source/'conversations').mkdir()
    config = {'profiles': [{'id': 'app', 'state_dir': str(source),
        'include_globs': ['conversations/*.db'], 'sqlite_backup_globs': ['conversations/*.db']}], 'compress': True}
    store = Store(tmp_path/'store')
    for name in ['first.db', 'later.db']:
        with sqlite3.connect(source/'conversations'/name) as db:
            db.execute('PRAGMA journal_mode=WAL');db.execute('CREATE TABLE messages(text TEXT)')
            db.execute("INSERT INTO messages VALUES ('synthetic saved row')");db.commit()
            sid = store.capture(config)['snapshot']
    _, _, _, manifest = store.load(sid)
    assert {f['path'] for f in manifest['profiles'][0]['files']} == {'conversations/first.db', 'conversations/later.db'}
    assert all(f['capture_method'] == 'sqlite-online-backup' for f in manifest['profiles'][0]['files'])
    store.restore(sid, config, tmp_path/'restore')


def test_compressed_restore_bounds_and_corruption_preserve_target(tmp_path):
    source = tmp_path/'source';source.mkdir();(source/'file').write_bytes(b'A'*100000)
    config = {'encrypt': True, 'profiles': [{'id': 'app', 'state_dir': str(source)}], 'compress': True}
    store = Store(tmp_path/'store');sid = store.capture(config)['snapshot']
    target = tmp_path/'restore/app';target.mkdir(parents=True);(target/'keep').write_text('current work')
    with pytest.raises(RecoveryError, match='byte budget'):
        store.restore(sid, {**config, 'max_file_bytes': 4096}, tmp_path/'restore', replace=True)
    blob = next(p for p in (store.snapshots/sid).iterdir() if p.name != 'manifest.enc')
    data = bytearray(blob.read_bytes());data[-1] ^= 1;blob.write_bytes(data)
    with pytest.raises(RecoveryError, match='authentication'):
        store.restore(sid, config, tmp_path/'restore', replace=True)
    assert (target/'keep').read_text() == 'current work'


def test_unsafe_profile_patterns_refused(tmp_path):
    for pattern in ['../outside', '/outside']:
        config = {'profiles': [{'id': 'app', 'state_dir': str(tmp_path), 'include_globs': [pattern]}]}
        with pytest.raises(RecoveryError): Store(tmp_path.parent/'store').capture(config)


def test_capture_duration_does_not_extend_five_minute_start_cadence(monkeypatch, tmp_path):
    from uncrash import runtime
    times = iter([1000, 1120])
    monkeypatch.setattr(runtime.time, 'monotonic', lambda: next(times))
    class StoreFixture:
        root = tmp_path
        def capture(self, config): return {'snapshot': 'synthetic'}
    class Stop:
        done = False
        def is_set(self): return self.done
        def wait(self, seconds):
            assert seconds == 180
            self.done = True
    run_daemon(StoreFixture(), {}, stop=Stop())


@pytest.mark.parametrize('encrypt', [False, True])
@pytest.mark.parametrize('compress', [False, True])
def test_rust_roundtrip_and_optional_encryption(tmp_path, encrypt, compress):
    source = tmp_path/'source'; source.mkdir(); data = ('saved state 日本語\n'*10000).encode()
    (source/'日本語.txt').write_bytes(data)
    config = {'profiles': [{'id': 'app', 'state_dir': str(source)}], 'encrypt': encrypt, 'compress': compress}
    store = Store(tmp_path/'store'); result = store.capture(config)
    _, path, cipher, manifest = store.load(result['snapshot'])
    assert result['engine'] == 'rust'
    assert manifest['encryption'] == ('aes-256-gcm' if encrypt else 'none')
    assert (cipher is not None) == encrypt
    assert (store.root/'key').exists() == encrypt
    assert (path/('manifest.enc' if encrypt else 'manifest.json')).exists()
    store.restore(result['snapshot'], config, tmp_path/'restore')
    assert (tmp_path/'restore/app/日本語.txt').read_bytes() == data


def test_rust_reuse_and_physical_budget_preserve_history(tmp_path):
    from uncrash.store import physical_bytes
    source = tmp_path/'source'; source.mkdir(); (source/'large').write_bytes(b'A'*1024*1024)
    config = {'profiles': [{'id': 'app', 'state_dir': str(source)}], 'max_total_bytes': 1600000}
    store = Store(tmp_path/'store'); first = store.capture(config); second = store.capture(config)
    assert second['reused_files'] == 1 and len(store.list()) == 2
    logical = sum(f.stat().st_size for x in store.list() for f in (store.snapshots/x).iterdir())
    assert physical_bytes([store.snapshots/x for x in store.list()]) < logical-900000
    _, _, _, a = store.load(first['snapshot']); _, _, _, b = store.load(second['snapshot'])
    left = store.snapshots/first['snapshot']/a['profiles'][0]['files'][0]['blob']
    right = store.snapshots/second['snapshot']/b['profiles'][0]['files'][0]['blob']
    assert left.stat().st_ino == right.stat().st_ino != (source/'large').stat().st_ino
    info = (source/'large').stat(); (source/'large').write_bytes(b'B'*1024*1024)
    os.utime(source/'large', ns=(info.st_atime_ns, info.st_mtime_ns))
    third = store.capture(config); assert third['reused_files'] == 0
    store.restore(third['snapshot'], config, tmp_path/'restore')
    assert (tmp_path/'restore/app/large').read_bytes() == b'B'*1024*1024


def test_plain_manifest_and_file_checksums_refuse_corruption(tmp_path):
    source = tmp_path/'source'; source.mkdir(); (source/'saved').write_bytes(b'original state')
    config = {'profiles': [{'id': 'app', 'state_dir': str(source)}]}; store = Store(tmp_path/'store')
    sid = store.capture(config)['snapshot']; _, path, _, m = store.load(sid)
    blob = path/m['profiles'][0]['files'][0]['blob']; blob.write_bytes(b'damaged!')
    with pytest.raises(RecoveryError): store.restore(sid, config, tmp_path/'restore')
    assert not (tmp_path/'restore').exists()
    (path/'manifest.json').write_text('{}')
    with pytest.raises(RecoveryError, match='checksum'): store.load(sid)


def test_sqlite_reuse_tracks_committed_wal_changes(tmp_path):
    source = tmp_path/'source'; source.mkdir()
    config = {'profiles': [{'id': 'app', 'state_dir': str(source), 'sqlite_backup_files': ['chat.db']}]}
    store = Store(tmp_path/'store')
    with sqlite3.connect(source/'chat.db') as db:
        db.execute('PRAGMA journal_mode=WAL'); db.execute('CREATE TABLE messages(text)')
        db.execute("INSERT INTO messages VALUES ('one')"); db.commit()
        store.capture(config); second = store.capture(config)
        assert second['reused_files'] == 1
        db.execute("INSERT INTO messages VALUES ('two')"); db.commit()
        third = store.capture(config); assert third['reused_files'] == 0
        store.restore(third['snapshot'], config, tmp_path/'restore')
    with sqlite3.connect(tmp_path/'restore/app/chat.db') as db:
        assert db.execute('SELECT count(*) FROM messages').fetchone()[0] == 2


def test_legacy_encrypted_snapshot_and_new_plain_snapshot_coexist(tmp_path):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    source = tmp_path/'source'; source.mkdir(); (source/'file').write_text('legacy')
    config = {'profiles': [{'id': 'app', 'state_dir': str(source)}]}; store = Store(tmp_path/'store')
    old = store.capture({**config, 'encrypt': True, 'snapshot_engine': 'python'})['snapshot']
    _, path, cipher, m = store.load(old); m.pop('encryption'); m.pop('compress')
    (path/'manifest.enc').write_bytes(store.encrypt(AESGCM(store.key()), old, 'manifest', json.dumps(m).encode()))
    new = store.capture(config)['snapshot']; assert store.load(new)[2] is None
    store.restore(old, config, tmp_path/'old'); assert (tmp_path/'old/app/file').read_text() == 'legacy'


def test_environment_settings_literals_and_precedence(tmp_path):
    from uncrash.cli import environment_settings, main
    env = tmp_path/'.env'; env.write_text('UNCRASH_ENCRYPT=false\nUNCRASH_SNAPSHOT_ENGINE=rust\nUNCRASH_COMPRESS=false\n')
    assert environment_settings(env, {})['encrypt'] is False
    assert environment_settings(env, {'UNCRASH_ENCRYPT': 'true'})['encrypt'] is True
    source = tmp_path/'source'; source.mkdir(); (source/'data').write_text('saved')
    config = tmp_path/'config.json'; config.write_text(json.dumps({'encrypt': True, 'compress': True, 'profiles': [{'id':'app','state_dir':str(source)}]}))
    assert main(['--env-file', str(env), '--config', str(config), '--state', str(tmp_path/'store'), 'snapshot']) == 0
    _, _, cipher, manifest = Store(tmp_path/'store').load('latest')
    assert cipher is None and manifest['compress'] is False
    for value in ['UNCRASH_ENCRYPT=yes', 'UNCRASH_ENCRYPT=false\nUNCRASH_ENCRYPT=true', 'UNCRASH_RUST_BINARY=$(id)', 'UNKNOWN_KEY=x']:
        env.write_text(value)
        with pytest.raises(RecoveryError): environment_settings(env, {})


def test_rust_refuses_symlinked_ancestor(tmp_path):
    from uncrash.store import rust_capture
    real = tmp_path/'real'; real.mkdir(); (real/'file').write_text('safe')
    (tmp_path/'link').symlink_to(real, target_is_directory=True)
    store = Store(tmp_path/'store'); destination = tmp_path/'blob'
    job = {'source':tmp_path/'link/file', 'destination':destination, 'limit':1000, 'aad':b'', 'old':{}, 'cache':None}
    with pytest.raises(RecoveryError): rust_capture(store.root, [job], {}, None)
    assert not destination.exists()


def test_rust_build_works_with_fixture_home(monkeypatch, tmp_path):
    from uncrash.store import build_native
    monkeypatch.setenv('HOME', str(tmp_path/'isolated-home'))
    assert build_native(tmp_path/'cache').is_file()


def test_rust_final_budget_accounts_for_files_grown_after_planning(monkeypatch, tmp_path):
    from uncrash import store as module
    source = tmp_path/'source'; source.mkdir(); file = source/'active'; file.write_bytes(b'x')
    config = {'profiles':[{'id':'app','state_dir':str(source)}], 'max_bytes':32}
    original = module.rust_capture
    def grow_then_capture(root, jobs, config, key):
        file.write_bytes(b'x'*64)
        return original(root, jobs, config, key)
    monkeypatch.setattr(module, 'rust_capture', grow_then_capture)
    store = Store(tmp_path/'store')
    with pytest.raises(RecoveryError, match='byte budget'): store.capture(config)
    assert store.list() == []


def test_rust_failure_diagnostic_omits_paths_and_keeps_previous_snapshot(tmp_path, monkeypatch):
    import hashlib
    import subprocess
    import uncrash.store as module
    source = tmp_path/'private-source';source.mkdir();(source/'chat.jsonl').write_text('{"synthetic":true}\n')
    config = {'profiles': [{'id': 'app', 'state_dir': str(source)}]}
    store = Store(tmp_path/'store');previous = store.capture(config)['snapshot']
    real_run = module.subprocess.run
    def fail_worker(argv, **kwargs):
        if Path(argv[0]).name == 'uncrash-snapshot':
            return subprocess.CompletedProcess(argv, 1, stdout=b'')
        return real_run(argv, **kwargs)
    monkeypatch.setattr(module.subprocess, 'run', fail_worker)
    with pytest.raises(RecoveryError, match='Rust snapshot worker refused'):
        store.capture(config)
    receipt = store.root/'worker-error.json'
    proof = json.loads(receipt.read_text())
    assert proof['failed_index'] == 0
    assert proof['source_sha256'] == hashlib.sha256(os.fsencode(source/'chat.jsonl')).hexdigest()
    assert str(source) not in receipt.read_text() and 'synthetic' not in receipt.read_text()
    assert receipt.stat().st_mode & 0o777 == 0o600
    assert store.list() == [previous]


@pytest.mark.parametrize('encrypt,compress', [(False,False),(False,True),(True,False),(True,True)])
def test_rust_jsonl_prefix_survives_continuous_appends(tmp_path, encrypt, compress):
    import threading
    source = tmp_path/'source';source.mkdir();chat = source/'chat.jsonl'
    line = b'{"synthetic":true}\n';chat.write_bytes(line*2000000)
    stop = threading.Event()
    def append():
        with chat.open('ab', buffering=0) as stream:
            while not stop.is_set():
                stream.write(line*100);stop.wait(.002)
    writer = threading.Thread(target=append);writer.start()
    store = Store(tmp_path/'store')
    config = {'encrypt': encrypt, 'compress': compress, 'profiles': [{'id': 'app', 'state_dir': str(source)}]}
    try:
        sid = store.capture(config)['snapshot']
    finally:
        stop.set();writer.join()
    _,_,_,manifest = store.load(sid)
    record = manifest['profiles'][0]['files'][0]
    assert record['copy_method'] == 'jsonl-prefix'
    store.restore(sid, config, tmp_path/'restore')
    restored = (tmp_path/'restore/app/chat.jsonl').read_bytes()
    assert len(restored) == record['size'] and restored.endswith(b'\n')
    assert chat.read_bytes().startswith(restored)
    assert chat.stat().st_size > len(restored)


@pytest.mark.parametrize('encrypt,compress', [(False,False),(False,True),(True,False),(True,True)])
def test_portable_bundle_new_store_restore_and_key_separation(tmp_path, encrypt, compress):
    import tarfile
    from uncrash.recovery import export_bundle, import_bundle
    app = tmp_path/'original';app.mkdir();(app/'saved.txt').write_text('synthetic portable state\n'*1000)
    config = {'encrypt':encrypt,'compress':compress,'profiles':[{'id':'ide','state_dir':str(app)}]}
    store = Store(tmp_path/'source-store','different-source-host');sid = store.capture(config)['snapshot']
    archive = tmp_path/'transfer/portable.tar';exported = export_bundle(store,sid,archive)
    with tarfile.open(archive) as tar:
        assert tar.getnames()[0] == 'bundle.json'
        assert all('key' not in name for name in tar.getnames())
    result = import_bundle(archive,tmp_path/'new-host-store')
    assert result['apps_launched'] is False and result['requires_separate_key'] is encrypt
    imported_config = json.loads(Path(result['config']).read_text())
    imported = Store(tmp_path/'new-host-store',imported_config['origin'])
    if encrypt:
        assert not (imported.root/'key').exists()
        (imported.root/'key').write_bytes(store.key());(imported.root/'key').chmod(0o600)
    imported.restore(sid,imported_config,tmp_path/'new-environment')
    assert (tmp_path/'new-environment/ide/saved.txt').read_bytes() == (app/'saved.txt').read_bytes()
    assert exported['key_included'] is False and archive.stat().st_mode & 0o777 == 0o600
    with pytest.raises(RecoveryError):import_bundle(archive,tmp_path/'new-host-store')
    with pytest.raises(RecoveryError):export_bundle(store,sid,archive)


@pytest.mark.parametrize('attack',['traversal','symlink','duplicate','corrupt','unknown'])
def test_bundle_import_refuses_unsafe_members_and_removes_only_new_target(tmp_path, attack):
    import io,tarfile
    from uncrash.recovery import export_bundle, import_bundle
    app=tmp_path/'app';app.mkdir();(app/'state').write_text('synthetic')
    store=Store(tmp_path/'store');sid=store.capture({'profiles':[{'id':'ide','state_dir':str(app)}]})['snapshot']
    original=tmp_path/'original.tar';export_bundle(store,sid,original)
    with tarfile.open(original) as archive:
        rows=[(m,archive.extractfile(m).read()) for m in archive.getmembers()]
    target=tmp_path/'bad.tar'
    with tarfile.open(target,'w',format=tarfile.USTAR_FORMAT) as archive:
        for i,(member,data) in enumerate(rows):
            if i==1:
                if attack=='traversal':member.name='payload/../../escape'
                elif attack=='symlink':member.type=tarfile.SYMTYPE;member.linkname='/tmp/unsafe';member.size=0;data=b''
                elif attack=='corrupt':data=bytes([data[0]^1])+data[1:]
                elif attack=='unknown':member.name='payload/key'
            archive.addfile(member,io.BytesIO(data))
            if i==1 and attack=='duplicate':archive.addfile(member,io.BytesIO(data))
    existing=tmp_path/'keep';existing.write_text('unchanged')
    with pytest.raises(RecoveryError):import_bundle(target,tmp_path/'new-store')
    assert not (tmp_path/'new-store').exists() and existing.read_text()=='unchanged'
    assert store.list()==[sid]


@pytest.mark.parametrize('attack',['none','truncated','corrupt','extra','traversal'])
def test_ssh_receiver_hashes_and_publishes_only_a_new_private_archive(tmp_path, attack):
    import hashlib,subprocess,sys
    from uncrash.recovery import SSH_RECEIVER
    data=b'synthetic opaque archive\n'*100
    header={'name':'fixture.tar','size':len(data),'sha256':hashlib.sha256(data).hexdigest()}
    transmitted=data
    if attack=='truncated':transmitted=data[:-1]
    elif attack=='corrupt':transmitted=b'X'+data[1:]
    elif attack=='extra':transmitted=data+b'X'
    elif attack=='traversal':header['name']='../outside.tar'
    result=subprocess.run([sys.executable,'-c',SSH_RECEIVER],input=json.dumps(header).encode()+b'\n'+transmitted,
        env={**os.environ,'HOME':str(tmp_path)},capture_output=True,timeout=10)
    target=tmp_path/'.local/state/uncrash-inbox/fixture.tar'
    if attack=='none':
        assert result.returncode==0 and target.read_bytes()==data
        assert target.stat().st_mode&0o777==0o600
        duplicate=subprocess.run([sys.executable,'-c',SSH_RECEIVER],input=json.dumps(header).encode()+b'\n'+data,
            env={**os.environ,'HOME':str(tmp_path)},capture_output=True,timeout=10)
        assert duplicate.returncode and target.read_bytes()==data
    else:
        assert result.returncode and not target.exists()
    assert not list(tmp_path.rglob('.incoming-*'))


def test_jetbrains_recovery_profile_and_persisted_project_discovery(tmp_path):
    from uncrash.recovery import jetbrains_state, transfer_bundle
    settings=tmp_path/'.config/JetBrains/PyCharmFixture/options';settings.mkdir(parents=True)
    (settings/'recentProjects.xml').write_text('<application><entry key="$USER_HOME$/project"><RecentProjectMetaInfo opened="true"/></entry></application>')
    history=tmp_path/'.cache/JetBrains/PyCharmFixture/LocalHistory';history.mkdir(parents=True)
    (history/'changes.storageData').write_text('synthetic history')
    proc=tmp_path/'proc';proc.mkdir()
    report=jetbrains_state(tmp_path,proc)
    assert report['projects'][0]['path']==str(tmp_path/'project')
    assert report['signals_sent'] is False and report['window_count_verified'] is False
    config=selected_config({'profiles':[]},['jetbrains-recovery'],tmp_path)
    store=Store(tmp_path/'store');sid=store.capture(config)['snapshot']
    store.restore(sid,config,tmp_path/'restore')
    assert (tmp_path/'restore/jetbrains-recovery/PyCharmFixture/LocalHistory/changes.storageData').read_text()=='synthetic history'
    with pytest.raises(RecoveryError):transfer_bundle(tmp_path/'nonexistent','-oProxyCommand=unsafe')


def test_window_close_on_wayland_refuses_focus_injection(monkeypatch):
    from uncrash.recovery import request_window_close
    monkeypatch.setenv('XDG_SESSION_TYPE','wayland')
    with pytest.raises(RecoveryError,match='no focus keystroke'):
        request_window_close(123,456,'789')


def test_window_close_requires_explicit_identities(monkeypatch):
    from uncrash.recovery import request_window_close
    monkeypatch.setenv('XDG_SESSION_TYPE','x11')
    with pytest.raises(RecoveryError,match='explicit window'):
        request_window_close(0,456,'789')


def test_jetbrains_metadata_capture_is_explicit_and_does_not_signal(tmp_path, monkeypatch):
    from uncrash.cli import environment_settings
    import uncrash.recovery as recovery
    monkeypatch.setattr(recovery,'jetbrains_state',lambda: {'signals_sent':False,'root_ide_candidates':1,'descendants':[{'pid':42,'terminal':'/dev/pts/1'}]})
    store=Store(tmp_path/'store');config={'profiles':[],'jetbrains_metadata':True}
    sid=store.capture(config)['snapshot'];*_,manifest=store.load(sid)
    assert manifest['jetbrains']['signals_sent'] is False
    assert manifest['jetbrains']['descendants'][0]['terminal']=='/dev/pts/1'
    settings=environment_settings(None,{'UNCRASH_JETBRAINS_METADATA':'true'})
    assert settings['jetbrains_metadata'] is True


def test_jetbrains_projects_identifies_last_closed_and_last_opened(tmp_path):
    from uncrash.recovery import jetbrains_projects, restore_pycharm
    settings = tmp_path/'.config/JetBrains/PyCharm2026.3/options'; settings.mkdir(parents=True)
    xml_content = '''<application>
      <component name="RecentProjectsManager">
        <option name="additionalInfo">
          <map>
            <entry key="$USER_HOME$/proj-old">
              <value>
                <RecentProjectMetaInfo frameTitle="old">
                  <option name="activationTimestamp" value="1000" />
                </RecentProjectMetaInfo>
              </value>
            </entry>
            <entry key="$USER_HOME$/proj-closed">
              <value>
                <RecentProjectMetaInfo frameTitle="closed">
                  <option name="activationTimestamp" value="3000" />
                </RecentProjectMetaInfo>
              </value>
            </entry>
            <entry key="$USER_HOME$/proj-opened">
              <value>
                <RecentProjectMetaInfo frameTitle="opened" opened="true">
                  <option name="activationTimestamp" value="2000" />
                </RecentProjectMetaInfo>
              </value>
            </entry>
          </map>
        </option>
        <option name="lastOpenedProject" value="$USER_HOME$/proj-opened" />
      </component>
    </application>'''
    (settings/'recentProjects.xml').write_text(xml_content)
    res = jetbrains_projects(tmp_path, selector_filter='PyCharm')
    assert res['last_opened'] == str(tmp_path/'proj-opened')
    assert res['last_closed'] == str(tmp_path/'proj-closed')
    assert res['open_count'] == 1
    assert res['closed_count'] == 2

    planned = restore_pycharm(home=tmp_path, executable='/bin/echo', dry_run=True)
    assert planned['status'] == 'planned'
    assert planned['project'] == str(tmp_path/'proj-closed')
    assert planned['executable'] == '/bin/echo'


def test_cli_pycharm_subcommand(tmp_path, capsys, monkeypatch):
    from uncrash.cli import main
    settings = tmp_path/'.config/JetBrains/PyCharm2026.3/options'; settings.mkdir(parents=True)
    (settings/'recentProjects.xml').write_text('<application><entry key="$USER_HOME$/test-proj"><RecentProjectMetaInfo opened="true"/></entry></application>')
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('XDG_SESSION_TYPE', 'wayland')

    code = main(['pycharm'])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert 'running_processes' in out
    assert 'all_recent_projects' in out

    code = main(['pycharm', '--dry-run', '--restore', '--executable', '/bin/true'])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out['status'] == 'planned'
    assert out['project'] == str(tmp_path/'test-proj')

    # Test positional action: restore
    code = main(['pycharm', 'restore', '--dry-run', '--executable', '/bin/true'])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out['status'] == 'planned'

    # Test main_pycharm entry point
    from uncrash.cli import main_pycharm
    code = main_pycharm(['--dry-run', '--restore', '--executable', '/bin/true'])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out['status'] == 'planned'


def test_environment_file_resolution_prioritizes_user_config_over_home_env(monkeypatch, tmp_path, capsys):
    from uncrash.cli import main
    fake_home = tmp_path / 'home'
    fake_home.mkdir()
    # Unrelated .env in user's home directory (e.g. third-party API keys)
    (fake_home / '.env').write_text('UNRELATED_API_KEY=secret\nSOME_OTHER_VAR=123\n')

    # Dedicated uncrash config in ~/.config/uncrash/.env
    uncrash_config_dir = fake_home / '.config/uncrash'
    uncrash_config_dir.mkdir(parents=True)
    (uncrash_config_dir / '.env').write_text('UNCRASH_ENCRYPT=false\nUNCRASH_SNAPSHOT_ENGINE=rust\n')

    # Prepare JetBrains fixture in fake home
    settings = fake_home / '.config/JetBrains/PyCharm2026.2/options'
    settings.mkdir(parents=True)
    (settings / 'recentProjects.xml').write_text('<application><entry key="$USER_HOME$/test-proj"><RecentProjectMetaInfo opened="true"/></entry></application>')

    monkeypatch.setenv('HOME', str(fake_home))
    monkeypatch.setenv('XDG_SESSION_TYPE', 'wayland')
    monkeypatch.delenv('UNCRASH_ENV_FILE', raising=False)
    monkeypatch.chdir(fake_home)

    # Executing from $HOME should load ~/.config/uncrash/.env without failing on $HOME/.env
    code = main(['pycharm', '--dry-run', '--restore', '--executable', '/bin/true'])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out['status'] == 'planned'


