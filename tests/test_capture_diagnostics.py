import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

import pytest

from uncrash import store as module
from uncrash.events import error_code


@pytest.fixture(scope='module')
def worker(tmp_path_factory):
    return module.build_native(tmp_path_factory.mktemp('worker-diagnostics'))


@pytest.mark.parametrize('failure,reason,code', [
    ('removed', 'source-changed', 'UNCRASH-SOURCE-CHANGED'),
    ('grown', 'byte-budget', 'UNCRASH-CAPTURE-BUDGET'),
    ('symlink', 'unsafe-source', 'UNCRASH-NATIVE-FAILED'),
])
def test_real_worker_refusal_preserves_snapshot_and_private_reason(
        worker, tmp_path, monkeypatch, failure, reason, code):
    source = tmp_path / 'private-project'
    source.mkdir()
    file = source / 'private-state'
    file.write_bytes(b'x')
    store = module.Store(tmp_path / 'store')
    config = {'rust_binary': str(worker), 'max_file_bytes': 2,
              'profiles': [{'id': 'app', 'state_dir': str(source)}]}
    previous = store.capture(config)['snapshot']
    real_capture = module.rust_capture

    def change_after_planning(root, jobs, config, key):
        if failure == 'removed':
            file.unlink()
        elif failure == 'grown':
            file.write_bytes(b'x' * 16)
        else:
            other = tmp_path / 'outside-private-content'
            other.write_bytes(b'x')
            file.unlink()
            file.symlink_to(other)
        return real_capture(root, jobs, config, key)

    monkeypatch.setattr(module, 'rust_capture', change_after_planning)
    with pytest.raises(module.RecoveryError) as error:
        store.capture(config)
    assert error_code(error.value) == code
    receipt = store.root / 'worker-error.json'
    diagnostic = json.loads(receipt.read_text())
    assert diagnostic['reason'] == reason
    assert diagnostic['failed_index'] == 0
    assert str(source) not in str(error.value) + receipt.read_text()
    assert 'private-state' not in receipt.read_text()
    assert receipt.stat().st_mode & 0o777 == 0o600
    assert store.list() == [previous]
    assert not list(store.snapshots.glob('.pending-*'))


@pytest.mark.parametrize('stderr', [
    b'', b'old worker error including private paths', b'not-json',
    b'{"schema":"uncrash.worker-error/v1","index":true,"reason":"byte-budget"}',
    b'{"schema":"uncrash.worker-error/v1","index":1,"reason":"byte-budget"}',
    b'{"schema":"uncrash.worker-error/v1","index":0,"reason":"private-message"}',
    b'{"schema":"uncrash.worker-error/v1","index":0,"reason":[]}',
    b'{"schema":"uncrash.worker-error/v1","index":0,"reason":"byte-budget","path":"secret"}',
    b'x' * 1025,
])
def test_unbound_or_legacy_worker_detail_never_claims_budget(
        worker, tmp_path, monkeypatch, stderr):
    source = tmp_path / 'private-file'
    source.write_bytes(b'x')
    root = module.Store(tmp_path / 'store').root
    job = {'source': source, 'destination': tmp_path / 'out', 'limit': 10,
           'aad': b'', 'old': {}, 'cache': None}
    monkeypatch.setattr(module.subprocess, 'run', lambda argv, **kwargs:
                        subprocess.CompletedProcess(argv, 1, stdout=b'', stderr=stderr))
    with pytest.raises(module.RecoveryError) as error:
        module.rust_capture(root, [job], {'rust_binary': str(worker)}, None)
    assert error_code(error.value) == 'UNCRASH-NATIVE-FAILED'
    diagnostic = (root / 'worker-error.json').read_text()
    assert json.loads(diagnostic)['reason'] == 'worker-failed'
    assert 'secret' not in diagnostic and 'private-message' not in str(error.value)


def test_real_worker_reason_binds_first_failed_job_after_success(worker, tmp_path):
    root = module.Store(tmp_path / 'store').root
    source = tmp_path / 'saved'
    source.write_bytes(b'x')
    jobs = [{'source': path, 'destination': tmp_path / f'out-{i}', 'limit': 2,
             'aad': b'', 'old': {}, 'cache': None}
            for i, path in enumerate([source, tmp_path / 'disappeared'])]
    with pytest.raises(module.RecoveryError) as error:
        module.rust_capture(root, jobs, {'rust_binary': str(worker), 'rust_threads': 2}, None)
    assert error_code(error.value) == 'UNCRASH-SOURCE-CHANGED'
    diagnostic = json.loads((root / 'worker-error.json').read_text())
    assert diagnostic['failed_index'] == 1
    assert diagnostic['reason'] == 'source-changed'
    assert (tmp_path / 'out-0').read_bytes() == b'x'
