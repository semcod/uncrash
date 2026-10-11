import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from uncrash import diagnostics as d, events, recovery, runtime
from uncrash.store import RecoveryError


def process(root, pid, parent, name, exe, start, terminal='/dev/pts/1', environment=b''):
    p = root / str(pid); (p / 'fd').mkdir(parents=True); (p / 'ns').mkdir()
    fields = ['S', str(parent), '1', '1', '1'] + ['0'] * 14 + [str(start)]
    (p / 'stat').write_text(f'{pid} ({name}) ' + ' '.join(fields))
    (p / 'comm').write_text(name); (p / 'exe').symlink_to(exe)
    (p / 'cwd').symlink_to('/fixture-project'); (p / 'fd/0').symlink_to(terminal)
    (p / 'ns/pid').symlink_to('pid:[123]'); (p / 'environ').write_bytes(environment)
    (p / 'cmdline').write_bytes(exe.encode() + b'\0')
    return p


def test_discovers_all_hosts_and_does_not_promote_inherited_marker(tmp_path):
    process(tmp_path, 10, 1, 'pycharm', '/apps/pycharm', 10)
    process(tmp_path, 11, 10, 'bash', '/bin/bash', 11)
    process(tmp_path, 12, 11, 'codex', '/bin/codex', 12)
    process(tmp_path, 20, 1, 'gnome-terminal-', '/bin/gnome-terminal-server', 20)
    process(tmp_path, 21, 20, 'agy', '/bin/agy', 21)
    process(tmp_path, 30, 1, 'codex', '/bin/codex', 30, '/dev/null', b'TERMINAL_EMULATOR=JetBrains-JediTerm\0TOKEN=do-not-record\0')
    rows = {r['pid']: r for r in d.session_hosts(tmp_path)['processes']}
    assert rows[12]['current_host'] == 'PyCharm'
    assert rows[21]['current_host'] == 'GNOME Terminal'
    assert rows[30]['current_host'] == 'unknown'
    assert rows[30]['role'] == 'unknown'
    assert rows[30]['launch_host_inference'] == 'JetBrains'
    assert all(r['conversation_id'] is None for r in rows.values())
    assert 'do-not-record' not in json.dumps(rows)


def test_reused_parent_identity_does_not_confirm_host(tmp_path, monkeypatch):
    process(tmp_path, 10, 1, 'pycharm', '/apps/pycharm', 10)
    process(tmp_path, 12, 10, 'codex', '/bin/codex', 12)
    original = d._stat; counts = {}
    def changing(path):
        row = original(path); counts[path.name] = counts.get(path.name, 0) + 1
        if path.name == '10' and counts[path.name] > 2: row['start_ticks'] = '1000'
        return row
    monkeypatch.setattr(d, '_stat', changing)
    row = d.session_hosts(tmp_path)['processes'][0]
    assert row['current_host'] == 'unknown' and not row['ancestry_stable']


def test_provider_index_distinguishes_files_from_summary_and_ignores_body(tmp_path):
    root = tmp_path / '.gemini/antigravity-cli'; (root / 'conversations').mkdir(parents=True)
    (root / 'conversations/present.db').touch(); (root / 'conversations/orphan.db').touch()
    with sqlite3.connect(root / 'conversation_summaries.db') as c:
        c.execute('CREATE TABLE conversation_summaries(conversation_id TEXT)')
        c.executemany('INSERT INTO conversation_summaries VALUES(?)', [('present',), ('missing',)])
    sessions = tmp_path / '.codex/sessions'; sessions.mkdir(parents=True)
    (sessions / 'one.jsonl').write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'one', 'source': 'vscode'}}) + '\nPRIVATE CHAT BODY')
    result = d.provider_inventory(tmp_path)
    assert result['agy']['summary_with_file'] == 1
    assert result['agy']['summary_without_file'] == 1
    assert result['agy']['file_without_summary'] == 1
    assert result['agy']['database_integrity'] == 'not-checked'
    assert result['codex']['host_binding'] == 'not-present'
    assert 'PRIVATE' not in json.dumps(result)


def test_snapshot_age_checks_checksum_and_does_not_claim_payload_verification(tmp_path):
    sid = 'snapshot-one'; p = tmp_path / 'snapshots' / sid; p.mkdir(parents=True)
    raw = json.dumps({'schema': 'uncrash.snapshot/v1', 'id': sid, 'created_at': '2026-01-01T00:00:00+00:00'}).encode()
    (p / 'manifest.json').write_bytes(raw); (p / 'manifest.sha256').write_text(hashlib.sha256(raw).hexdigest())
    result = d.snapshot_health(tmp_path)
    assert result['stale'] and result['verified_plain_manifests'] == 1
    assert result['payload_hashes_verified'] is False
    (p / 'manifest.json').write_bytes(raw + b' ')
    result = d.snapshot_health(tmp_path)
    assert result['invalid_manifests'] == 1 and result['latest_snapshot'] is None


def test_canonical_event_chain_and_changed_evidence_refusal(tmp_path):
    first = events.append_event(tmp_path, event_type='uncrash.snapshot_completed')
    second = events.append_event(tmp_path, event_type='uncrash.snapshot_failed', code='UNCRASH-CAPTURE-FAILED', outcome='FAILED')
    assert second['sequence'] == 2 and second['previousHash'] == first['eventHash']
    path = next((tmp_path / 'logs').glob('*.jsonl'))
    assert path.stat().st_mode & 0o777 == 0o600
    raw = path.read_bytes().replace(b'"sequence":1', b'"sequence":9'); path.write_bytes(raw)
    with pytest.raises(RecoveryError, match='chain'):
        events.append_event(tmp_path, event_type='uncrash.snapshot_completed')
    assert path.read_bytes() == raw


def test_no_exception_text_in_error_code():
    assert events.error_code(ValueError('secret-prompt')) == 'UNCRASH-CAPTURE-FAILED'
    assert events.error_code(RecoveryError('SQLite consistency backup failed')) == 'UNCRASH-SQLITE-BACKUP'


def test_encrypted_only_copy_has_unknown_freshness_without_reading_key(tmp_path):
    p = tmp_path / 'snapshots/20261009T090000000000-aaaaaaaaaaaa'; p.mkdir(parents=True)
    (p / 'manifest.enc').write_bytes(b'opaque ciphertext')
    result = d.snapshot_health(tmp_path)
    assert result['stale'] is None
    assert result['freshness'] == 'unknown-encrypted'
    assert result['encrypted_manifest_count'] == 1


@pytest.mark.parametrize('force,expected', [(False, [signal.SIGTERM]), (True, [signal.SIGTERM, signal.SIGKILL])])
def test_close_respects_force_with_pinned_descriptor(monkeypatch, force, expected):
    monkeypatch.setattr(recovery, 'detected_gui_apps', lambda: [{'pid': 555, 'start_ticks': '123', 'name': 'test', 'comm': 'test'}])
    monkeypatch.setattr(runtime, 'pidfd', lambda pid: 777)
    monkeypatch.setattr(runtime, 'start_ticks', lambda pid: '123')
    monkeypatch.setattr(recovery, 'Path', lambda path: SimpleNamespace(stat=lambda: SimpleNamespace(st_uid=os.getuid())))
    monkeypatch.setattr('select.poll', lambda: SimpleNamespace(register=lambda *a: None, poll=lambda timeout: []))
    sent = []; closed = []
    monkeypatch.setattr(signal, 'pidfd_send_signal', lambda fd, sig: sent.append((fd, sig)))
    monkeypatch.setattr(os, 'close', closed.append)
    result = recovery.close_gui_app(pid=555, expected_start='123', force=force)
    assert sent == [(777, sig) for sig in expected] and closed == [777]
    assert result['status'] == 'still-running' and result['method'] == expected[-1].name


def test_close_refuses_implicit_and_stale_targets(monkeypatch):
    monkeypatch.setattr(recovery, 'detected_gui_apps', lambda: [{'pid': 555, 'start_ticks': '124'}])
    send = Mock(); monkeypatch.setattr(signal, 'pidfd_send_signal', send)
    with pytest.raises(RecoveryError, match='explicit PID'): recovery.close_gui_app(name='pycharm')
    with pytest.raises(RecoveryError, match='identity changed'): recovery.close_gui_app(pid=555, expected_start='123')
    send.assert_not_called()


def test_pycharm_close_dry_run_does_not_signal(monkeypatch, capsys):
    from uncrash import cli
    close = Mock(side_effect=AssertionError('must not close'))
    monkeypatch.setattr(cli, 'close_gui_app', close)
    assert cli.main(['pycharm', 'close', '--dry-run']) == 0
    assert json.loads(capsys.readouterr().out)['signals_sent'] is False
    close.assert_not_called()


def test_pid_identity_change_after_open_sends_no_signal(monkeypatch):
    monkeypatch.setattr(recovery, 'detected_gui_apps', lambda: [{'pid': 555, 'start_ticks': '123', 'name': 'test', 'comm': 'test'}])
    monkeypatch.setattr(runtime, 'pidfd', lambda pid: 777)
    monkeypatch.setattr(runtime, 'start_ticks', lambda pid: '124')
    monkeypatch.setattr(recovery, 'Path', lambda path: SimpleNamespace(stat=lambda: SimpleNamespace(st_uid=os.getuid())))
    closed = []; send = Mock()
    monkeypatch.setattr(os, 'close', closed.append)
    monkeypatch.setattr(signal, 'pidfd_send_signal', send)
    with pytest.raises(RecoveryError, match='identity changed before'):
        recovery.close_gui_app(pid=555, expected_start='123')
    send.assert_not_called(); assert closed == [777]


def test_owned_child_closes_via_pidfd(monkeypatch):
    import subprocess
    import sys
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    try:
        start = runtime.start_ticks(child.pid)
        monkeypatch.setattr(recovery, 'detected_gui_apps', lambda: [
            {'pid': child.pid, 'start_ticks': start, 'name': 'owned synthetic fixture', 'comm': 'python'}])
        result = recovery.close_gui_app(pid=child.pid, expected_start=start)
        assert result['stopped'] and result['signals_sent'] == ['SIGTERM']
        assert child.wait(timeout=5) == -signal.SIGTERM
    finally:
        if child.poll() is None: child.kill(); child.wait()


def test_daemon_failure_code_is_durable_without_private_exception(tmp_path, capsys):
    class Store:
        root = tmp_path
        def capture(self, config): raise RecoveryError('SQLite consistency backup failed: PRIVATE')
    class Stop:
        done = False
        def is_set(self): return self.done
        def wait(self, seconds): self.done = True
    runtime.run_daemon(Store(), {}, stop=Stop())
    text = capsys.readouterr().out + next((tmp_path / 'logs').glob('*.jsonl')).read_text()
    assert 'UNCRASH-SQLITE-BACKUP' in text and 'PRIVATE' not in text


def test_sqlite_integrity_detection_identifies_corrupt_database(tmp_path):
    healthy_db = tmp_path / 'healthy.db'
    with sqlite3.connect(healthy_db) as c:
        c.execute('CREATE TABLE t (id INT);')
        c.execute('INSERT INTO t VALUES (1);')
    status, err = d.check_sqlite_integrity(healthy_db)
    assert status == 'ok' and err is None

    broken_db = tmp_path / 'broken.db'
    broken_db.write_bytes(b'SQLite format 3\x00corrupted bytes invalid page')
    status, err = d.check_sqlite_integrity(broken_db)
    assert status == 'corrupted' and err is not None


def test_scan_agent_log_panics_finds_unhandled_panics(tmp_path):
    log_dir = tmp_path / 'log'
    log_dir.mkdir()
    log_file = log_dir / 'cli-20261010_120000.log'
    log_file.write_text(
        "I1010 12:00:00 server.go:3185 GetConversationDetail: found conversation abc-123\n"
        "Caught panic: runtime error: invalid memory address or nil pointer dereference\n"
        "Restoring terminal...\n"
    )
    panics = d.scan_agent_log_panics(log_dir)
    assert len(panics) == 1
    assert 'runtime error: invalid memory address' in panics[0]['signature']
    assert panics[0]['log_name'] == 'cli-20261010_120000.log'


def test_check_agent_storage_health_reports_corruptions(tmp_path):
    home = tmp_path / 'home'
    agy_conv = home / '.gemini/antigravity-cli/conversations'
    agy_conv.mkdir(parents=True)
    good_db = agy_conv / 'good.db'
    with sqlite3.connect(good_db) as c:
        c.execute('CREATE TABLE steps (id INT);')
    bad_db = agy_conv / 'bad.db'
    bad_db.write_bytes(b'SQLite format 3\x00' + b'\xff' * 100)

    report = d.check_agent_storage_health(home)
    assert report['status'] == 'CORRUPTED'
    assert len(report['corrupted_sessions']) >= 1
    corrupt_ids = {s['session_id'] for s in report['corrupted_sessions']}
    assert 'bad' in corrupt_ids


def test_salvage_agent_session_db(tmp_path):
    src = tmp_path / 'test_session.db'
    with sqlite3.connect(src) as c:
        c.execute('CREATE TABLE steps (idx INT PRIMARY KEY, content TEXT);')
        c.execute('INSERT INTO steps VALUES (1, "step one");')
    src.chmod(0o640)

    dest = tmp_path / 'salvaged.db'
    receipt = recovery.salvage_agent_session_db(src, dest)
    assert receipt['status'] == 'COMPLETED'
    assert receipt['verifiedIntegrity'] == 'ok'
    assert receipt['salvagedStepCount'] == 1
    assert dest.is_file()
    assert dest.stat().st_mode & 0o777 == 0o600
    quarantine = Path(receipt['quarantinedPath'])
    assert quarantine.is_file()
    assert quarantine.stat().st_mode & 0o777 == 0o600

    with sqlite3.connect(dest) as c:
        cnt = c.execute('SELECT count(*) FROM steps').fetchone()[0]
        assert cnt == 1


def test_salvage_agent_session_db_multi_table(tmp_path):
    src = tmp_path / 'multi_session.db'
    with sqlite3.connect(src) as c:
        c.execute('CREATE TABLE steps (id INT, text TEXT);')
        c.execute('INSERT INTO steps VALUES (1, "s1"), (2, "s2"), (3, "s3");')
        c.execute('CREATE TABLE messages (id INT, role TEXT);')
        c.execute('INSERT INTO messages VALUES (1, "user"), (2, "assistant");')

    dest = tmp_path / 'salvaged_multi.db'
    receipt = recovery.salvage_agent_session_db(src, dest)
    assert receipt['status'] == 'COMPLETED'
    assert receipt['verifiedIntegrity'] == 'ok'
    assert receipt['salvagedStepCount'] == 5


def test_salvage_agent_session_db_non_sqlite_input(tmp_path):
    src = tmp_path / 'garbage.db'
    src.write_bytes(b'non-sqlite random text that cannot be dumped\n')
    dest = tmp_path / 'salvaged_garbage.db'

    receipt = recovery.salvage_agent_session_db(src, dest)
    assert receipt['status'] == 'FAILED'



def test_diagnose_includes_agent_health_and_session_corruption_findings(tmp_path):
    home = tmp_path / 'home'
    conv_dir = home / '.gemini/antigravity-cli/conversations'
    conv_dir.mkdir(parents=True)
    bad_db = conv_dir / 'corrupt.db'
    bad_db.write_bytes(b'SQLite format 3\x00' + b'\xff' * 100)

    log_dir = home / '.gemini/antigravity-cli/log'
    log_dir.mkdir(parents=True)
    panic_log = log_dir / 'panic.log'
    panic_log.write_text("Caught panic: runtime error: invalid memory address or nil pointer dereference\n")

    state = tmp_path / 'state'
    state.mkdir()
    (state / 'snapshots').mkdir()

    report = d.diagnose(home=home, state=state)
    assert 'agent_health' in report
    assert report['agent_health']['status'] == 'CORRUPTED'
    assert 'UNCRASH-SESSION-STORAGE-CORRUPTED' in report['findings']
    assert 'UNCRASH-AGENT-PANIC-DETECTED' in report['findings']


def _session_database(path):
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE steps(id INTEGER)')
        connection.execute('INSERT INTO steps VALUES(7)')
    return path


def test_salvage_refuses_existing_output_and_same_input(tmp_path):
    source = _session_database(tmp_path / 'source.db')
    original = source.read_bytes()
    output = tmp_path / 'existing.db'
    output.write_bytes(b'OWNER DATA')
    for target in (output, source):
        with pytest.raises(RecoveryError, match='already exists'):
            recovery.salvage_agent_session_db(source, target)
    assert output.read_bytes() == b'OWNER DATA' and source.read_bytes() == original


def test_salvage_preserves_private_source_copy_and_verified_steps(tmp_path, monkeypatch):
    import hashlib
    import stat
    source = _session_database(tmp_path / 'source.db')
    original = source.read_bytes()
    monkeypatch.setattr(recovery.subprocess, 'run', lambda *a, **k: pytest.fail('External SQLite CLI is unnecessary'))
    output = tmp_path / 'output.db'
    result = recovery.salvage_agent_session_db(source, output)
    quarantined = Path(result['quarantinedPath'])
    assert result['status'] == 'COMPLETED' and result['salvagedStepCount'] == 1
    assert source.read_bytes() == quarantined.read_bytes() == original
    assert result['originalSha256'] == hashlib.sha256(original).hexdigest()
    assert result['recoveredSha256'] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert stat.S_IMODE(quarantined.stat().st_mode) == stat.S_IMODE(output.stat().st_mode) == 0o600
    assert stat.S_IMODE(quarantined.parent.stat().st_mode) == 0o700
    assert not list(tmp_path.glob('uncrash-session-staging-*'))


def test_salvage_failed_sql_import_preserves_source_and_does_not_publish(tmp_path, monkeypatch):
    source = _session_database(tmp_path / 'source.db')
    original = source.read_bytes()
    real_connect = sqlite3.connect

    class FailedImport(sqlite3.Connection):
        def execute(self, sql, *args):
            if sql.startswith('INSERT INTO'):
                raise sqlite3.OperationalError('injected private-session-marker')
            return super().execute(sql, *args)

    def connect(path, **kwargs):
        if isinstance(path, Path):
            kwargs['factory'] = FailedImport
        return real_connect(path, **kwargs)

    monkeypatch.setattr(sqlite3, 'connect', connect)
    output = tmp_path / 'failed.db'
    result = recovery.salvage_agent_session_db(source, output)
    assert result['status'] == 'FAILED' and result['salvagedStepCount'] == 0
    assert 'private-session-marker' not in json.dumps(result)
    assert not output.exists() and source.read_bytes() == original
    assert Path(result['quarantinedPath']).read_bytes() == original
    assert not list(tmp_path.glob('uncrash-session-staging-*'))


@pytest.mark.parametrize('failure', ['insert', 'destination-open'])
def test_failed_salvage_closes_connections_before_directory_cleanup(tmp_path, monkeypatch, failure):
    import tempfile

    source = _session_database(tmp_path / 'source.db')
    original = source.read_bytes()
    real_connect = sqlite3.connect
    real_directory = tempfile.TemporaryDirectory
    connections = []
    cleanups = []

    class FailedImport(sqlite3.Connection):
        def execute(self, sql, *args):
            if sql.startswith('INSERT INTO'):
                raise sqlite3.OperationalError('injected import failure')
            return super().execute(sql, *args)

    def connect(path, **kwargs):
        if isinstance(path, Path):
            if failure == 'destination-open':
                raise sqlite3.OperationalError('injected connection failure')
            kwargs['factory'] = FailedImport
        connection = real_connect(path, **kwargs)
        connections.append(connection)
        return connection

    class CheckedDirectory(real_directory):
        def cleanup(self):
            for connection in connections:
                with pytest.raises(sqlite3.ProgrammingError, match='closed'):
                    connection.execute('SELECT 1')
            cleanups.append(True)
            super().cleanup()

    monkeypatch.setattr(sqlite3, 'connect', connect)
    monkeypatch.setattr(tempfile, 'TemporaryDirectory', CheckedDirectory)
    output = tmp_path / 'output.db'
    result = recovery.salvage_agent_session_db(source, output)
    assert result['status'] == 'FAILED' and result['verifiedIntegrity'] == 'failed'
    assert cleanups and len(connections) == (2 if failure == 'insert' else 1)
    assert source.read_bytes() == Path(result['quarantinedPath']).read_bytes() == original
    assert not output.exists() and not list(tmp_path.glob('uncrash-session-staging-*'))


def test_salvage_corrupt_source_never_claims_empty_recovery_success(tmp_path):
    source = tmp_path / 'broken.db'
    source.write_bytes(b'SQLite format 3\0' + b'\xff' * 100)
    output = tmp_path / 'output.db'
    result = recovery.salvage_agent_session_db(source, output)
    assert result['status'] == 'FAILED' and not output.exists()
    assert result['recoveredSha256'] == '0' * 64
    assert Path(result['quarantinedPath']).read_bytes() == source.read_bytes()


def test_salvage_does_not_overwrite_output_created_during_recovery(tmp_path, monkeypatch):
    source = _session_database(tmp_path / 'source.db')
    output = tmp_path / 'output.db'
    real_link = recovery.os.link

    def competing_link(src, dst, **kwargs):
        output.write_bytes(b'OTHER WRITER')
        return real_link(src, dst, **kwargs)

    monkeypatch.setattr(recovery.os, 'link', competing_link)
    result = recovery.salvage_agent_session_db(source, output)
    assert result['status'] == 'FAILED' and output.read_bytes() == b'OTHER WRITER'


def test_salvage_refuses_live_wal_instead_of_losing_committed_rows(tmp_path):
    source = tmp_path / 'live.db'
    connection = sqlite3.connect(source)
    try:
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('CREATE TABLE steps(id INTEGER)')
        connection.execute('INSERT INTO steps VALUES(7)')
        connection.commit()
        with pytest.raises(RecoveryError, match='consistent snapshot'):
            recovery.salvage_agent_session_db(source, tmp_path / 'output.db')
        assert connection.execute('SELECT id FROM steps').fetchall() == [(7,)]
        assert not (tmp_path / 'output.db').exists()
    finally:
        connection.close()


def test_salvage_refuses_symlink_source_and_destination(tmp_path):
    source = _session_database(tmp_path / 'source.db')
    alias = tmp_path / 'alias.db'
    alias.symlink_to(source)
    for src, dst in ((alias, tmp_path / 'output.db'), (source, alias)):
        with pytest.raises(RecoveryError, match='Symlink'):
            recovery.salvage_agent_session_db(src, dst)
    assert alias.is_symlink()


def test_locked_session_is_unavailable_and_health_degraded(tmp_path):
    conversations = tmp_path / '.gemini/antigravity-cli/conversations'
    conversations.mkdir(parents=True)
    source = _session_database(conversations / 'locked.db')
    connection = sqlite3.connect(source)
    try:
        connection.execute('BEGIN EXCLUSIVE')
        assert d.check_sqlite_integrity(source)[0] == 'unavailable'
        report = d.check_agent_storage_health(tmp_path)
        assert report['status'] == 'DEGRADED' and not report['corrupted_sessions']
        assert report['providers']['agy']['unavailable_count'] == 1
        assert report['unavailable_sessions'][0]['session_id'] == 'locked'
    finally:
        connection.rollback(); connection.close()


def test_integrity_symlink_and_nonfile_are_unavailable(tmp_path):
    source = _session_database(tmp_path / 'source.db')
    alias = tmp_path / 'alias.db'
    alias.symlink_to(source)
    assert d.check_sqlite_integrity(alias)[0] == 'unavailable'
    assert d.check_sqlite_integrity(tmp_path)[0] == 'unavailable'
    assert d.check_sqlite_integrity(tmp_path / 'missing.db')[0] == 'missing'


def test_recent_panic_after_large_log_prefix_is_detected(tmp_path):
    log = tmp_path / 'session.log'
    log.write_bytes(b'x' * 600000 + b'\nCaught panic: recent crash\n')
    results = d.scan_agent_log_panics(tmp_path)
    assert len(results) == 1 and results[0]['matched_detail'] == 'recent crash'


def test_panic_scan_ignores_symlink_and_directory_entries(tmp_path):
    outside = tmp_path / 'private.txt'
    outside.write_text('Caught panic: private log')
    (tmp_path / 'linked.log').symlink_to(outside)
    (tmp_path / 'directory.log').mkdir()
    assert d.scan_agent_log_panics(tmp_path) == []


def test_panic_scan_rejects_invalid_file_budgets(tmp_path):
    for budget in (-1, 0, 101):
        with pytest.raises(ValueError, match='budget'):
            d.scan_agent_log_panics(tmp_path, budget)


def test_native_scan_agent_log_panics_matches_python_results(tmp_path):
    log1 = tmp_path / 'session_1.log'
    log1.write_text(
        "I1011 10:00:00 server.go:100 start\n"
        "Caught panic: runtime error: invalid memory address or nil pointer dereference\n"
        "I1011 10:00:01 server.go:101 end\n"
    )
    log2 = tmp_path / 'session_2.log'
    log2.write_text(
        "Failed to load conversation abc-123-def: Error: database disk image is malformed in sqlite\n"
    )
    log3 = tmp_path / 'session_3.log'
    log3.write_text(
        "program was killed: program experienced a panic due to stack overflow\n"
    )
    log4 = tmp_path / 'session_4.log'
    log4.write_text("All operations completed normally\n")

    native_res = d.native_scan_agent_log_panics(tmp_path, max_files=10)
    assert native_res is not None
    assert len(native_res) == 3

    combined_res = d.scan_agent_log_panics(tmp_path, max_files=10)
    assert combined_res == native_res

    signatures = {r['signature'] for r in native_res}
    assert any('runtime error' in s for s in signatures)
    assert any('Failed to load conversation' in s for s in signatures)
    assert any('program was killed' in s for s in signatures)


def test_native_scan_fallback_when_binary_missing(tmp_path, monkeypatch):
    log = tmp_path / 'fallback.log'
    log.write_text("Caught panic: fallback test failure\n")

    monkeypatch.setattr(d, 'find_native_worker', lambda *args, **kwargs: None)
    monkeypatch.setattr('shutil.which', lambda *args, **kwargs: None)

    assert d.native_scan_agent_log_panics(tmp_path) is None
    results = d.scan_agent_log_panics(tmp_path)
    assert len(results) == 1
    assert results[0]['matched_detail'] == 'fallback test failure'


def test_find_native_worker_discovery(tmp_path):
    from uncrash.store import build_native, find_native_worker
    built = build_native(tmp_path)
    assert built.is_file()
    found = find_native_worker(tmp_path)
    assert found == built



