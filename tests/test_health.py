import asyncio
from datetime import datetime
import hashlib
import json
import os
import subprocess

import pytest

from uncrash import cli, health
from uncrash.store import RecoveryError


NOW = 1791658800.0


def thread(name, stack):
    return f'"{name}" #1 tid=0x1\n   java.lang.Thread.State: WAITING\n{stack}\n'


@pytest.fixture
def evidence(tmp_path):
    proc = tmp_path / 'proc'
    (proc / 'pressure').mkdir(parents=True)
    (proc / 'meminfo').write_text('MemTotal: 100000 kB\nMemAvailable: 50000 kB\nSwapTotal: 90000 kB\nSwapFree: 1000 kB\n')
    for kind in ('cpu', 'memory', 'io'):
        (proc / 'pressure' / kind).write_text('some avg10=0.00 avg60=0.00 avg300=0.00 total=0\nfull avg10=0.00 avg60=0.00 avg300=0.00 total=0\n')
    logs = tmp_path / 'logs'; logs.mkdir()
    (logs / 'idea.log').write_text(datetime.fromtimestamp(NOW).strftime('%Y-%m-%d %H:%M:%S,%f')[:-3] + ' INFO - still logging\n')
    dump = tmp_path / 'dump.txt'; dump.write_text(thread('main', 'at java.lang.Object.wait(Native Method)'))
    os.utime(dump, (NOW, NOW))
    return {'log_dir': logs, 'thread_dump': dump, 'proc_root': proc, 'now': NOW}


def test_incident_counts_do_not_include_coroutine_creation_stacks(evidence):
    docker = 'at DockerAgentContainerImpl$waitForExit.await(containerExit)'
    ijent = 'at IjentFileSystem.readAttributes\nat NativeIconProvider.initialize'
    raw = ''.join(thread(f'DefaultDispatcher-worker-{i}', docker) for i in range(63))
    raw += ''.join(thread(f'DefaultDispatcher-worker-{i+63}', ijent) for i in range(115))
    raw += thread('AWT-EventQueue-0', 'at TerminalTabCloseListener.runCloseCheckBlocking')
    raw += '\nCoroutine dump\n' + thread('duplicate', docker) * 200
    evidence['thread_dump'].write_text(raw)
    os.utime(evidence['thread_dump'], (NOW, NOW))
    report = health.inspect_health(**evidence)
    assert report['thread_dump']['docker_exit_waits'] == 63
    assert report['thread_dump']['ijent_filesystem_waits'] == 115
    assert report['thread_dump']['java_threads'] == 179
    assert report['status'] == 'critical' and report['preflight_exit_code'] == 2
    assert report['findings'][0]['code'] == 'docker_ijent_wait_concentration'
    assert any(f['code'] == 'terminal_close_blocked' for f in report['findings'])
    assert 'containerExit' not in json.dumps(report)


def test_clean_fresh_evidence_and_used_swap_alone_are_not_pressure(evidence):
    report = health.inspect_health(**evidence)
    assert report['status'] == 'no_risk_observed'
    assert report['resources']['swap_used_kib'] == 89000
    assert report['findings'] == []


@pytest.mark.parametrize('age,status', [(0, 'critical'), (3600, 'no_risk_observed')])
def test_log_event_age_not_file_mtime_controls_active_alarm(evidence, age, status):
    path = evidence['log_dir'] / 'idea.log'
    line = datetime.fromtimestamp(NOW-age).strftime('%Y-%m-%d %H:%M:%S,%f')[:-3]
    path.write_text(line + ' ERROR - Thread pool exhaustion: Dispatchers.IO\n' + path.read_text())
    os.utime(path, (NOW, NOW))
    report = health.inspect_health(**evidence)
    assert report['status'] == status
    assert report['findings'][0]['evidence']['age_seconds'] == age


def test_stale_dump_never_allows_preflight(evidence):
    os.utime(evidence['thread_dump'], (NOW-3600, NOW-3600))
    report = health.inspect_health(**evidence)
    assert report['thread_dump']['status'] == 'stale'
    assert report['status'] == 'unknown' and report['preflight_exit_code'] == 3


def test_discovery_selects_latest_saved_dump_without_attach(evidence):
    folder = evidence['log_dir'] / 'threadDumps-Dispatchers.IO'; folder.mkdir()
    older, newer = folder / 'threadDump-old.txt', folder / 'threadDump-new.txt'
    older.write_text(thread('main', 'at DockerAgentContainerImpl$waitForExit'))
    newer.write_text(evidence['thread_dump'].read_text())
    os.utime(older, (NOW-100, NOW-100)); os.utime(newer, (NOW, NOW))
    report = health.inspect_health(**{**evidence, 'thread_dump': None})
    assert report['status'] == 'no_risk_observed'
    assert report['thread_dump']['source'] == 'discovered'
    assert report['thread_dump']['docker_exit_waits'] == 0


@pytest.mark.parametrize('unsafe', ['symlink', 'fifo', 'too_many_entries', 'too_many_directories'])
def test_discovery_refuses_incomplete_or_unsafe_inventory(evidence, unsafe):
    folder = evidence['log_dir'] / 'threadDumps-1'; folder.mkdir()
    path = folder / 'threadDump-test.txt'
    if unsafe == 'symlink':
        path.symlink_to(evidence['thread_dump'])
    elif unsafe == 'fifo':
        os.mkfifo(path)
    elif unsafe == 'too_many_entries':
        for i in range(129): (folder / str(i)).touch()
    else:
        for i in range(17): (evidence['log_dir'] / f'threadDumps-extra-{i}').mkdir()
    report = health.inspect_health(**{**evidence, 'thread_dump': None})
    assert report['status'] == 'unknown'
    assert report['thread_dump']['status'] == 'unavailable'


def test_discovery_stale_or_future_dump_does_not_allow_launch(evidence):
    folder = evidence['log_dir'] / 'threadDumps-1'; folder.mkdir()
    path = folder / 'threadDump-test.txt'; path.write_text(evidence['thread_dump'].read_text())
    for stamp in (NOW-3600, NOW+3600):
        os.utime(path, (stamp, stamp))
        assert health.inspect_health(**{**evidence, 'thread_dump': None})['status'] == 'unknown'


@pytest.mark.parametrize('kind', ['missing', 'malformed', 'oversized', 'symlink', 'fifo', 'future'])
def test_unusable_dump_never_produces_green(evidence, tmp_path, kind):
    path = evidence['thread_dump']
    if kind == 'malformed':
        path.write_text('arbitrary output without Java threads')
    elif kind == 'oversized':
        with path.open('wb') as out:
            out.truncate(health.DUMP_BYTES+1)
    elif kind == 'future':
        os.utime(path, (NOW+3600, NOW+3600))
    else:
        path.unlink()
        if kind == 'symlink':
            target = tmp_path / 'target'; target.write_text(thread('main', 'safe'))
            path.symlink_to(target)
        elif kind == 'fifo':
            os.mkfifo(path)
    assert health.inspect_health(**evidence)['status'] == 'unknown'


@pytest.mark.parametrize('raw', ['nan', '-1', '101', 'missing'])
def test_bad_pressure_is_unknown(evidence, raw):
    (evidence['proc_root'] / 'pressure' / 'memory').write_text('some avg10='+raw+'\nfull avg10='+raw+'\n')
    assert health.inspect_health(**evidence)['status'] == 'unknown'


@pytest.mark.parametrize('kind,average', [('memory', 12), ('io', 60)])
def test_memory_and_io_pressure_block_extra_load(evidence, kind, average):
    (evidence['proc_root'] / 'pressure' / kind).write_text(f'some avg10={average}\nfull avg10={average}\n')
    report = health.inspect_health(**evidence)
    assert report['status'] == 'critical'
    assert any(f['code'] == kind+'_pressure' for f in report['findings'])


def test_low_memory_blocks_load_without_swap_or_pressure(evidence):
    (evidence['proc_root'] / 'meminfo').write_text('MemTotal: 100000 kB\nMemAvailable: 1000 kB\n')
    assert health.inspect_health(**evidence)['status'] == 'critical'


def test_missing_evidence_is_unknown(tmp_path):
    assert health.inspect_health(proc_root=tmp_path, now=NOW)['status'] == 'unknown'


def test_project_gitignore_is_not_an_ide_exclusion(evidence, tmp_path):
    project = tmp_path / 'project'; (project / '.subactor/cache').mkdir(parents=True)
    (project / '.gitignore').write_text('.subactor/\n')
    report = health.inspect_health(**evidence, project=project)
    assert report['status'] == 'warning'
    assert report['project']['generated_roots'][0]['ide_exclusion'] == 'unknown'
    (project / '.idea').mkdir()
    module = project / '.idea/project.iml'
    module.write_text('<module><content url="file://$MODULE_DIR$/.."><excludeFolder url="file://$MODULE_DIR$/../.subactor/cache2"/></content></module>')
    assert health.inspect_health(**evidence, project=project)['project']['generated_roots'][0]['ide_exclusion'] == 'not_excluded'
    module.write_text('<module><content url="file://$MODULE_DIR$/.."><excludeFolder url="file://$MODULE_DIR$/../.subactor"/></content></module>')
    assert health.inspect_health(**evidence, project=project)['status'] == 'no_risk_observed'


def test_symlinked_project_metadata_is_unknown(evidence, tmp_path):
    root = tmp_path / 'project'; root.mkdir()
    (root / '.idea').symlink_to(evidence['log_dir'], target_is_directory=True)
    report = health.inspect_health(**evidence, project=root)
    assert report['project']['status'] == 'unavailable' and report['status'] == 'unknown'


def test_exclusion_in_one_module_does_not_cover_another(evidence, tmp_path):
    root = tmp_path / 'project'; (root / '.subactor/cache').mkdir(parents=True)
    (root / '.idea').mkdir()
    (root / '.idea/one.iml').write_text('<module><content url="file://$PROJECT_DIR$"><excludeFolder url="file://$PROJECT_DIR$/.subactor"/></content></module>')
    (root / '.idea/two.iml').write_text('<module><content url="file://$PROJECT_DIR$"/></module>')
    report = health.inspect_health(**evidence, project=root)
    assert report['project']['generated_roots'][0]['ide_exclusion'] == 'not_excluded'


def test_log_tail_quota_and_bad_encoding_are_unknown(evidence):
    path = evidence['log_dir'] / 'idea.log'
    original = path.read_bytes()
    path.write_bytes(b'x' * (health.LOG_BYTES+1) + b'\n' + original)
    report = health.inspect_health(**evidence)
    assert report['log']['tail_limited'] and report['status'] == 'unknown'
    path.write_bytes(original + b'\xff')
    assert health.inspect_health(**evidence)['status'] == 'unknown'


def test_invalid_io_event_date_does_not_become_healthy(evidence):
    path = evidence['log_dir'] / 'idea.log'
    path.write_text(path.read_text() + '2026-99-99 00:00:00,000 Thread pool exhaustion: Dispatchers.IO\n')
    assert health.inspect_health(**evidence)['status'] == 'unknown'


def test_module_quota_and_outside_paths_are_unavailable(evidence, tmp_path):
    root = tmp_path / 'project'; (root / '.idea').mkdir(parents=True)
    modules = root / '.idea/modules.xml'
    modules.write_text('<modules><module filepath="/outside/project.iml"/></modules>')
    assert health.inspect_health(**evidence, project=root)['status'] == 'unknown'
    modules.write_text('<modules>' + '<module filepath="$PROJECT_DIR$/a.iml"/>' * 65 + '</modules>')
    assert health.inspect_health(**evidence, project=root)['status'] == 'unknown'


def test_directory_entry_quota_and_xml_entities_are_unavailable(evidence, tmp_path):
    root = tmp_path / 'project'; (root / '.idea').mkdir(parents=True)
    module = root / '.idea/project.iml'
    module.write_text('<!DOCTYPE module [<!ENTITY x "value">]><module>&x;</module>')
    assert health.inspect_health(**evidence, project=root)['status'] == 'unknown'
    module.write_text('<module><content url="file://$PROJECT_DIR$"/></module>')
    for i in range(129):
        (root / str(i)).touch()
    assert health.inspect_health(**evidence, project=root)['status'] == 'unknown'


def test_process_identity_is_rechecked(evidence, monkeypatch):
    values = iter(['456', None])
    monkeypatch.setattr(health, '_identity', lambda *a: next(values))
    report = health.inspect_health(**evidence, pid=123, expected_start='456')
    assert report['process_identity'] == 'unknown' and report['preflight_exit_code'] == 3


def test_proc_identity_parser_handles_spaces_and_closing_parentheses(evidence):
    process = evidence['proc_root'] / '123'; process.mkdir()
    (process / 'stat').write_text('123 (java (IDE)) S ' + '0 ' * 18 + '456 0 0\n')
    report = health.inspect_health(**evidence, pid=123, expected_start='456')
    assert report['process_identity'] == 'verified'
    assert health.inspect_health(**evidence, pid=123, expected_start='999')['status'] == 'unknown'


@pytest.mark.parametrize('options', [{'pid': 1}, {'expected_start': '456'}, {'max_age_seconds': 0}, {'max_age_seconds': True}])
def test_bad_options_are_rejected(options):
    with pytest.raises(RecoveryError):
        health.inspect_health(**options)


def test_inspection_changes_no_files_and_sends_no_signals(evidence, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('read-only doctor attempted process mutation')
    monkeypatch.setattr(os, 'kill', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    root = evidence['proc_root'].parent
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
    health.inspect_health(**evidence)
    after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
    assert before == after


@pytest.mark.parametrize('code', [0, 1, 2, 3])
def test_cli_preflight_codes_bypass_store_and_environment(monkeypatch, capsys, code):
    monkeypatch.setattr(cli, 'inspect_health', lambda **kw: {'preflight_exit_code': code})
    monkeypatch.setattr(cli, 'environment_settings', lambda *a, **kw: pytest.fail('doctor read env or initialized state'))
    assert cli.main(['doctor', '--preflight']) == code
    assert cli.main(['doctor']) == 0
    assert capsys.readouterr().out


@pytest.mark.parametrize('code', [1, 2, 3])
@pytest.mark.parametrize('dry_run', [False, True])
def test_restore_preflight_never_reaches_launcher_when_blocked(monkeypatch, capsys, code, dry_run):
    monkeypatch.setattr(cli, 'inspect_health', lambda **kw: {'preflight_exit_code': code})
    monkeypatch.setattr(cli, 'restore_pycharm', lambda **kw: pytest.fail('blocked preflight reached restore'))
    command = ['pycharm', 'restore', '--project', '/project', '--preflight']
    assert cli.main(command + (['--dry-run'] if dry_run else [])) == code
    assert json.loads(capsys.readouterr().out)['launched'] is False


def test_successful_restore_uses_exact_inspected_project_and_original_options(monkeypatch, capsys):
    inspected, launched = [], []
    monkeypatch.setattr(cli, 'inspect_health', lambda **kw: inspected.append(kw) or {'preflight_exit_code': 0})
    monkeypatch.setattr(cli, 'restore_pycharm', lambda **kw: launched.append(kw) or {'status': 'dry-run'})
    assert cli.main(['pycharm', '--restore-last', '--project', '/project', '--preflight', '--log-dir', '/logs', '--executable', '/ide', '--dry-run']) == 0
    assert inspected[0]['project'] == launched[0]['project'] == '/project'
    assert launched[0] == {'project': '/project', 'executable': '/ide', 'dry_run': True}
    assert json.loads(capsys.readouterr().out)['preflight']['preflight_exit_code'] == 0


@pytest.mark.parametrize('args', [['pycharm', '--preflight'], ['pycharm', 'restore', '--preflight'], ['pycharm', 'restore', '--preflight', '--project', '/project', '--close']])
def test_ambiguous_or_unbound_preflight_is_refused(monkeypatch, args):
    monkeypatch.setattr(cli, 'restore_pycharm', lambda **kw: pytest.fail('ambiguous restore reached launcher'))
    monkeypatch.setattr(cli, 'close_gui_app', lambda **kw: pytest.fail('preflight reached process signalling'))
    assert cli.main(args) == 1


def test_rest_doctor_and_transport_health_are_distinct(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from uncrash import api
    from uncrash.store import Store
    monkeypatch.setattr(api, 'inspect_health', lambda **kw: {'status': 'critical', 'read_only': True})
    client = TestClient(api.create_fastapi_app(Store(tmp_path / 'store'), {}))
    assert client.get('/api/v1/doctor').json()['status'] == 'critical'
    assert client.get('/api/v1/health').json()['status'] == 'ok'
    monkeypatch.setattr(api, 'inspect_health', health.inspect_health)
    assert client.get('/api/v1/doctor?pid=123').status_code == 400


def test_mcp_exposes_read_only_preflight(tmp_path, monkeypatch):
    from uncrash import api
    from uncrash.store import Store
    monkeypatch.setattr(api, 'inspect_health', lambda **kw: {'status': 'unknown', 'read_only': True})
    server = api.create_mcp_server(Store(tmp_path / 'store'), {})
    async def run():
        result = await server.call_tool('uncrash_inspect_health', {})
        assert any('"read_only": true' in getattr(c, 'text', '') for c in result.content)
    asyncio.run(run())
