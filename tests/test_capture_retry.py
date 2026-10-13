import fcntl
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

import pytest

from uncrash import configuration, store as module
from uncrash.events import error_code


@pytest.fixture(scope='module')
def worker(tmp_path_factory):
    return module.build_native(tmp_path_factory.mktemp('retry-worker'))


@pytest.fixture
def fixture(tmp_path, worker):
    source = tmp_path / 'app'; source.mkdir()
    (source / 'a').write_bytes(b'old-a')
    (source / 'b').write_bytes(b'old-b')
    store = module.Store(tmp_path / 'store')
    config = {'rust_binary': str(worker), 'capture_attempts': 2,
              'capture_retry_timeout_seconds': 1,
              'profiles': [{'id': 'app', 'state_dir': str(source)}]}
    return source, store, config


def mutate_first_attempt(monkeypatch, source, *, repeat=False, after_failure=None):
    real = module.rust_capture
    calls = []

    def capture(root, jobs, config, key):
        calls.append(config)
        if len(calls) == 1 or repeat:
            (source / 'a').write_bytes(b'partial-first-attempt')
            (source / 'b').unlink()
            try:
                return real(root, jobs, config, key)
            finally:
                (source / 'a').write_bytes(b'fresh-a')
                (source / 'b').write_bytes(b'fresh-b')
                if after_failure:
                    after_failure()
        return real(root, jobs, config, key)

    monkeypatch.setattr(module, 'rust_capture', capture)
    return calls


@pytest.mark.parametrize('encrypted', [False, True])
def test_retry_replans_all_files_and_publishes_only_complete_fresh_attempt(
        fixture, monkeypatch, tmp_path, encrypted):
    source, store, config = fixture
    config['encrypt'] = encrypted
    previous = store.capture(config)['snapshot']
    calls = mutate_first_attempt(monkeypatch, source)
    result = store.capture(config)
    assert result['capture_attempts'] == len(calls) == 2
    assert calls[-1]['native_capture_timeout_seconds'] <= 1
    assert store.list() == sorted([previous, result['snapshot']])
    store.restore(result['snapshot'], config, tmp_path / 'restored')
    assert (tmp_path / 'restored/app/a').read_bytes() == b'fresh-a'
    assert (tmp_path / 'restored/app/b').read_bytes() == b'fresh-b'
    assert not list(store.snapshots.glob('.pending-*'))
    diagnostic = store.root / 'worker-error.json'
    assert json.loads(diagnostic.read_bytes())['reason'] == 'source-changed'
    assert diagnostic.stat().st_mode & 0o777 == 0o600
    assert str(source) not in diagnostic.read_text()


@pytest.mark.parametrize('attempts', [1, 2, 3])
def test_sustained_change_exhausts_attempts_and_retains_previous_snapshot(
        fixture, monkeypatch, attempts):
    source, store, config = fixture
    config['capture_attempts'] = attempts
    previous = store.capture(config)['snapshot']
    calls = mutate_first_attempt(monkeypatch, source, repeat=True)
    with pytest.raises(module.SourceChangedError) as exc:
        store.capture(config)
    assert error_code(exc.value) == 'UNCRASH-SOURCE-CHANGED'
    assert len(calls) == attempts and store.list() == [previous]
    assert not list(store.snapshots.glob('.pending-*'))


@pytest.mark.parametrize('failure', ['unsafe', 'budget', 'unknown', 'sqlite'])
def test_non_verified_source_change_never_retries(fixture, monkeypatch, tmp_path, failure):
    source, store, config = fixture
    previous = store.capture(config)['snapshot']
    real = module.rust_capture
    calls = []

    def fail(root, jobs, config, key):
        calls.append(1)
        if failure == 'unsafe':
            outside = tmp_path / 'outside'; outside.write_bytes(b'private')
            (source / 'b').unlink(); (source / 'b').symlink_to(outside)
        elif failure == 'budget':
            config = {**config, 'max_file_bytes': 1}
            jobs[0]['limit'] = 1
        else:
            message = 'SQLite consistency backup failed' if failure == 'sqlite' else 'Application file changed while captured; private unrelated message'
            raise module.RecoveryError(message)
        return real(root, jobs, config, key)

    monkeypatch.setattr(module, 'rust_capture', fail)
    with pytest.raises(module.RecoveryError):
        store.capture(config)
    assert len(calls) == 1 and store.list() == [previous]
    assert not list(store.snapshots.glob('.pending-*'))


def test_retry_deadline_bounds_lock_contention(fixture, monkeypatch):
    source, store, config = fixture
    previous = store.capture(config)['snapshot']
    fd = os.open(store.root / 'lock', os.O_RDWR)
    calls = mutate_first_attempt(monkeypatch, source)
    real = store._capture_once

    def held_after_cleanup(config, *, deadline=None):
        try:
            return real(config, deadline=deadline)
        except module.SourceChangedError:
            fcntl.flock(fd, fcntl.LOCK_EX)
            raise

    monkeypatch.setattr(store, '_capture_once', held_after_cleanup)
    start = time.monotonic()
    try:
        with pytest.raises(module.RecoveryError, match='retry deadline'):
            store.capture(config)
    finally:
        os.close(fd)
    assert time.monotonic() - start < 2.5
    assert len(calls) == 1 and store.list() == [previous]
    assert not list(store.snapshots.glob('.pending-*'))


def test_retry_native_process_uses_remaining_shared_deadline(fixture, monkeypatch, tmp_path):
    source, store, config = fixture
    previous = store.capture(config)['snapshot']
    sleeper = tmp_path / 'sleep-worker'
    sleeper.write_text('#!' + sys.executable + '\nimport time\ntime.sleep(10)\n')
    sleeper.chmod(0o700)
    calls = mutate_first_attempt(monkeypatch, source,
                                after_failure=lambda: config.update(rust_binary=str(sleeper)))
    start = time.monotonic()
    with pytest.raises(module.RecoveryError, match='worker timed out'):
        store.capture(config)
    assert time.monotonic() - start < 2.5
    assert len(calls) == 2 and calls[-1]['native_capture_timeout_seconds'] <= 1
    assert store.list() == [previous] and not list(store.snapshots.glob('.pending-*'))


def test_expired_retry_cannot_publish_complete_staging(fixture, monkeypatch):
    source, store, config = fixture
    previous = store.capture(config)['snapshot']
    calls = mutate_first_attempt(monkeypatch, source)
    clock = [100.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock[0])
    real = module.physical_bytes

    def delayed(paths):
        result = real(paths)
        if len(calls) == 2 and any(p.name.startswith('.pending-') for p in paths):
            clock[0] += 2
        return result

    monkeypatch.setattr(module, 'physical_bytes', delayed)
    with pytest.raises(module.RecoveryError, match='retry deadline'):
        store.capture(config)
    assert store.list() == [previous] and not list(store.snapshots.glob('.pending-*'))


def test_canonical_retry_settings_override_ambient_process_values(fixture, monkeypatch, tmp_path):
    source, store, config = fixture
    path = tmp_path / '.env'
    path.write_text('ENV_DSL_VERSION=1\nENV_DSL_NAMESPACE=UNCRASH\nENV_DSL_ENVIRONMENT=BASE\n'
                    'UNCRASH_CAPTURE_ATTEMPTS=2\nUNCRASH_CAPTURE_RETRY_TIMEOUT_SECONDS=1\n')
    monkeypatch.setenv('UNCRASH_CAPTURE_ATTEMPTS', '3')
    token = configuration.activate_environment_file(path)
    config.pop('capture_attempts'); config.pop('capture_retry_timeout_seconds')
    calls = mutate_first_attempt(monkeypatch, source, repeat=True)
    try:
        with pytest.raises(module.SourceChangedError):
            store.capture(config)
    finally:
        configuration._CONTEXT_FILE.reset(token)
    assert len(calls) == 2


def test_python_reader_retries_verified_mutation_with_fresh_content(fixture, monkeypatch, tmp_path):
    source, store, config = fixture
    config['snapshot_engine'] = 'python'
    previous = store.capture(config)['snapshot']
    real = module.os.fstat
    identity = (source / 'a').stat().st_ino
    reads = []

    def mutate_after_read(fd):
        info = real(fd)
        if info.st_ino == identity:
            reads.append(1)
            if len(reads) == 2:
                (source / 'a').write_bytes(b'fresh-a')
                (source / 'b').write_bytes(b'fresh-b')
                info = real(fd)
        return info

    monkeypatch.setattr(module.os, 'fstat', mutate_after_read)
    result = store.capture(config)
    assert result['capture_attempts'] == 2
    assert len(store.list()) == 2 and previous in store.list()
    store.restore(result['snapshot'], config, tmp_path / 'restored')
    assert (tmp_path / 'restored/app/a').read_bytes() == b'fresh-a'
    assert (tmp_path / 'restored/app/b').read_bytes() == b'fresh-b'
    assert not list(store.snapshots.glob('.pending-*'))


def test_expired_shared_deadline_refuses_sqlite_and_compiler_before_start(tmp_path, monkeypatch):
    monkeypatch.setattr(module.time, 'monotonic', lambda: 100.0)
    with pytest.raises(module.RecoveryError, match='retry deadline'):
        module.sqlite_snapshot(tmp_path / 'missing-db', 100, deadline=99.0)
    with pytest.raises(module.RecoveryError, match='retry deadline'):
        module.build_native(tmp_path / 'worker', deadline=99.0)
    assert not list((tmp_path / 'worker').rglob('.build-*'))


@pytest.mark.parametrize('name,value', [
    ('capture_attempts', 0), ('capture_attempts', 4), ('capture_attempts', True),
    ('capture_attempts', 1.5), ('capture_retry_timeout_seconds', 0),
    ('capture_retry_timeout_seconds', 601), ('capture_retry_timeout_seconds', True),
])
def test_invalid_retry_controls_are_rejected_before_capture(fixture, name, value):
    _, store, config = fixture
    config[name] = value
    with pytest.raises(configuration.SettingsError):
        store.capture(config)
    assert not store.list()
