import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import venv
import zipfile
from unittest.mock import Mock

import pytest

from uncrash import cli, installation
from uncrash.store import RecoveryError


@pytest.fixture(scope='module')
def wheel(tmp_path_factory):
    """A valid wheel of the current package, installed by pip in each fixture."""
    root = tmp_path_factory.mktemp('installer-wheel')
    package = Path(installation.__file__).parent
    entries = {str(p.relative_to(package.parent)): p.read_bytes()
               for p in package.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    metadata = 'uncrash-0.1.2.dist-info'
    entries[metadata + '/METADATA'] = b'Metadata-Version: 2.1\nName: uncrash\nVersion: 0.1.2\nRequires-Python: >=3.11\n'
    entries[metadata + '/WHEEL'] = b'Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n'
    entries[metadata + '/entry_points.txt'] = b'[console_scripts]\nuncrash = uncrash.cli:main\n'
    records = io.StringIO()
    writer = csv.writer(records)
    for name, data in entries.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('=')
        writer.writerow([name, 'sha256=' + digest, len(data)])
    writer.writerow([metadata + '/RECORD', '', ''])
    entries[metadata + '/RECORD'] = records.getvalue().encode()
    path = root / 'uncrash-0.1.2-py3-none-any.whl'
    with zipfile.ZipFile(path, 'w') as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return path


@pytest.fixture
def runtime(tmp_path, wheel):
    prefix = tmp_path / 'runtime'
    venv.EnvBuilder(system_site_packages=True).create(prefix)
    interpreter = prefix / 'bin/python'
    environment = {k: v for k, v in os.environ.items() if k != 'PYTHONPATH'}
    subprocess.run([sys.executable, '-m', 'pip', '--python', str(interpreter), '--isolated',
                    'install', '--no-index', '--no-deps', '--ignore-installed', str(wheel)],
                   env=environment, cwd=tmp_path, capture_output=True, check=True, timeout=60)
    return interpreter


def child(interpreter, code, cwd, *, environment=None):
    env = dict(os.environ if environment is None else environment)
    env.pop('PYTHONPATH', None)
    return subprocess.run([str(interpreter), '-E', '-P', '-c', code], cwd=cwd, env=env,
                          text=True, capture_output=True, timeout=20)


def library(interpreter, cwd):
    result = child(interpreter, 'import sysconfig; print(sysconfig.get_path("purelib"))', cwd)
    assert result.returncode == 0, result.stderr
    return Path(result.stdout.strip())


def test_installed_wheel_is_verified_from_an_independent_cwd(runtime, tmp_path):
    result = child(runtime, 'from uncrash.installation import service_interpreter; '
                   'print(service_interpreter())', tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(runtime)


@pytest.mark.parametrize('failure', ['editable', 'missing-metadata', 'missing-source', 'linked-checkout'])
def test_real_runtime_refuses_nonpersistent_installation(runtime, tmp_path, failure):
    lib = library(runtime, tmp_path)
    metadata = lib / 'uncrash-0.1.2.dist-info'
    if failure == 'editable':
        (metadata / 'direct_url.json').write_text(json.dumps({'dir_info': {'editable': True}}))
    elif failure == 'missing-metadata':
        (metadata / 'RECORD').unlink()
    elif failure == 'missing-source':
        (lib / 'uncrash/installation.py').unlink()
    else:
        (tmp_path / '.git').write_text('gitdir: fixture-owned-disposable-registration\n')
    result = child(runtime, 'from uncrash import cli; raise SystemExit(cli.main('
                   + repr(['--state', str(tmp_path / 'state'), '--config', str(tmp_path / 'config.json'),
                           'install-user']) + '))', tmp_path,
                   environment={**os.environ, 'HOME': str(tmp_path / 'home')})
    assert result.returncode != 0
    assert not (tmp_path / 'state').exists()
    assert not (tmp_path / 'config.json').exists()
    assert not (tmp_path / 'home/.config/systemd/user/uncrash.service').exists()


def test_borrowed_editable_interpreter_and_deleted_source_are_refused(runtime, tmp_path):
    lib = library(runtime, tmp_path)
    for p in (lib / 'uncrash').rglob('*.py'):
        p.unlink()
    metadata = lib / 'uncrash-0.1.2.dist-info'
    (metadata / 'direct_url.json').write_text(json.dumps({'dir_info': {'editable': True}}))
    source = str(Path(installation.__file__).parent.parent)
    (lib / 'borrowed-uncrash.pth').write_text('import sys; sys.path.insert(0, ' + repr(source) + ')\n')
    monkey_code = ('from uncrash.installation import service_interpreter; '
                  'service_interpreter()')
    result = child(runtime, monkey_code, tmp_path)
    assert result.returncode != 0 and 'Service installation requires' in result.stderr
    (lib / 'borrowed-uncrash.pth').write_text(str(tmp_path / 'removed-worktree/src') + '\n')
    # A caller that has already imported the editable package must also refuse
    # after its recorded source vanishes, even if another wheel is available.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(installation.sys, 'executable', str(runtime))
        with pytest.raises(RecoveryError, match='Service installation requires'):
            installation.service_interpreter()


def test_source_caller_cannot_install_an_unrelated_wheel(runtime, monkeypatch):
    monkeypatch.setattr(installation.sys, 'executable', str(runtime))
    monkeypatch.setenv('PYTHONPATH', str(Path(installation.__file__).parent.parent))
    with pytest.raises(RecoveryError, match='Service installation requires'):
        installation.service_interpreter()


def test_source_only_pythonpath_is_refused_without_private_failure_detail(tmp_path, monkeypatch):
    prefix = tmp_path / 'PRIVATE-removed-project-interpreter'
    venv.EnvBuilder().create(prefix)
    monkeypatch.setattr(installation.sys, 'executable', str(prefix / 'bin/python'))
    monkeypatch.setenv('PYTHONPATH', str(Path(installation.__file__).parent.parent))
    with pytest.raises(RecoveryError) as failure:
        installation.service_interpreter()
    assert 'Service installation requires' in str(failure.value)
    assert 'PRIVATE' not in str(failure.value)


def test_probe_rejects_private_noise_and_reaps_timed_out_child(monkeypatch):
    with pytest.raises(RecoveryError) as failure:
        installation._probe([sys.executable, '-c', 'print("PRIVATE" * 1000)'], {})
    assert 'PRIVATE' not in str(failure.value)
    original = subprocess.Popen
    children = []

    def capture(*args, **kwargs):
        process = original(*args, **kwargs)
        children.append(process)
        return process

    monkeypatch.setattr(installation.subprocess, 'Popen', capture)
    monkeypatch.setattr(installation, '_PROBE_SECONDS', 0.1)
    with pytest.raises(RecoveryError):
        installation._probe([sys.executable, '-c', 'import time; time.sleep(30)'], {})
    assert len(children) == 1 and children[0].poll() is not None


def test_cli_refusal_preserves_configuration_unit_and_state(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.delenv('UNCRASH_ENV_FILE', raising=False)
    config = tmp_path / 'config.json'; config.write_text('{"profiles": []}')
    unit = tmp_path / 'home/.config/systemd/user/uncrash.service'
    unit.parent.mkdir(parents=True); unit.write_bytes(b'preserve existing unit\n')
    before = {p: (p.read_bytes(), p.stat().st_mode) for p in (config, unit)}
    reject = Mock(side_effect=RecoveryError('Service installation requires an installed wheel'))
    monkeypatch.setattr(cli, 'service_interpreter', reject)
    effects = Mock(side_effect=AssertionError('installation effect before validation'))
    monkeypatch.setattr(cli, 'Store', effects)
    monkeypatch.setattr(cli.subprocess, 'run', effects)
    assert cli.main(['--state', str(tmp_path / 'state'), '--config', str(config), 'install-user']) == 1
    assert not (tmp_path / 'state').exists()
    assert {p: (p.read_bytes(), p.stat().st_mode) for p in before} == before
    effects.assert_not_called()
    assert 'installed wheel' in capsys.readouterr().err


def test_installed_cli_persists_env_and_profiles_only(runtime, tmp_path):
    home = tmp_path / 'home'; home.mkdir()
    envfile = tmp_path / 'settings % env'
    envfile.write_text('ENV_DSL_VERSION=1\nENV_DSL_NAMESPACE=UNCRASH\nENV_DSL_ENVIRONMENT=BASE\n'
                       'UNCRASH_INTERVAL_SECONDS=305\nUNCRASH_RETENTION=7\n')
    envfile.chmod(0o600)
    config = tmp_path / 'config.json'; state = tmp_path / 'state % data'
    code = ('import json; from unittest.mock import patch; from uncrash import cli; '
            'calls=[]; '
            'context=patch("uncrash.cli.subprocess.run", side_effect=lambda argv, **kw: calls.append(argv)); '
            'context.start(); result=cli.main(' + repr(['--state', str(state), '--config', str(config),
                '--env-file', str(envfile), 'install-user']) + '); context.stop(); '
            'assert result==0; print(json.dumps(calls))')
    result = child(runtime, code, tmp_path, environment={**os.environ, 'HOME': str(home)})
    assert result.returncode == 0, result.stderr
    assert json.loads(config.read_text()) == {'profiles': []}
    assert config.stat().st_mode & 0o777 == 0o600
    unit = (home / '.config/systemd/user/uncrash.service').read_text()
    assert '"' + str(runtime) + '" "-E" "-P" "-m" "uncrash.cli"' in unit
    assert '"--env-file" "' + str(envfile).replace('%', '%%') + '"' in unit
    assert str(state).replace('%', '%%') in unit
    assert '"interval_seconds": 305' in result.stdout
    assert json.loads(result.stdout.splitlines()[-1]) == [
        ['systemctl', '--user', 'daemon-reload'],
        ['systemctl', '--user', 'enable', '--now', 'uncrash.service'],
    ]
    shadow = tmp_path / 'shadow'; (shadow / 'uncrash').mkdir(parents=True)
    (shadow / 'uncrash/__init__.py').write_text('raise AssertionError("unexpected source import")')
    command = shlex.split(next(line[len('ExecStart='):]
                              for line in unit.splitlines() if line.startswith('ExecStart=')).replace('%%', '%'))
    # Exercise the generated service import flags with a read-only subcommand.
    command[-1] = 'profiles'
    executed = subprocess.run(command, cwd=shadow, env={**os.environ, 'HOME': str(home),
                              'PYTHONPATH': str(shadow)}, capture_output=True, text=True, timeout=20)
    assert executed.returncode == 0, executed.stderr
    assert json.loads(executed.stdout)['changes_applied'] is False
