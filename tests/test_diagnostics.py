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
