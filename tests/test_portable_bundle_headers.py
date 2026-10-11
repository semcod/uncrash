"""Reject extension-driven allocation before interpreting portable TAR records."""
import hashlib
import io
import json
import tarfile

import pytest

from uncrash import recovery
from uncrash.store import RecoveryError, Store


class GuardedInput:
    def __init__(self, stream, reads):
        self.stream = stream
        self.reads = reads

    def read(self, size=-1):
        self.reads.append(size)
        # Prevent a regression from actually allocating the adversarial size.
        assert 0 <= size <= 4 * 1024**2, f"Unbounded archive read: {size}"
        return self.stream.read(size)

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.stream.close()


def guard_reads(monkeypatch):
    original = recovery._file
    reads = []
    monkeypatch.setattr(
        recovery, '_file', lambda path: GuardedInput(original(path), reads))
    return reads


def header(kind, size):
    member = tarfile.TarInfo('extension')
    member.type = kind
    member.size = size
    return member.tobuf(format=tarfile.GNU_FORMAT)


def metadata_prefix():
    files = []
    for name, data in [('manifest.json', b'{}'), ('manifest.sha256', b'0' * 64)]:
        files.append({'name': name, 'size': len(data),
                      'sha256': hashlib.sha256(data).hexdigest()})
    metadata = {'schema': recovery.SCHEMA,
                'snapshot': '20260101T000000000000-0123456789ab',
                'origin': 'fixture', 'encryption': 'none',
                'files': files, 'profiles': [], 'logical_bytes': 0}
    raw = json.dumps(metadata).encode()
    member = tarfile.TarInfo('bundle.json')
    member.size = len(raw)
    return member.tobuf() + raw + b'\0' * (-len(raw) % 512)


@pytest.mark.parametrize('kind', [tarfile.XHDTYPE, tarfile.GNUTYPE_LONGNAME])
@pytest.mark.parametrize('after_metadata', [False, True])
def test_extension_size_cannot_drive_a_large_read(
        tmp_path, monkeypatch, kind, after_metadata):
    raw = (metadata_prefix() if after_metadata else b'') + header(kind, 1024**3)
    source = tmp_path / 'tiny-attack.tar'
    source.write_bytes(raw)
    destination = tmp_path / 'imported'
    unrelated = tmp_path / 'keep'
    unrelated.write_bytes(b'preserve')
    reads = guard_reads(monkeypatch)

    with pytest.raises(RecoveryError, match='regular'):
        recovery.import_bundle(source, destination)

    assert max(reads) <= 4 * 1024**2
    assert source.read_bytes() == raw
    assert not destination.exists()
    assert unrelated.read_bytes() == b'preserve'


@pytest.mark.parametrize('kind', [
    tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.GNUTYPE_LONGNAME,
    tarfile.GNUTYPE_LONGLINK, tarfile.GNUTYPE_SPARSE,
    tarfile.CONTTYPE, tarfile.DIRTYPE, tarfile.SYMTYPE, tarfile.LNKTYPE,
])
def test_non_plain_records_are_rejected_before_body_processing(
        tmp_path, monkeypatch, kind):
    source = tmp_path / 'unsupported.tar'
    source.write_bytes(header(kind, 0))
    reads = guard_reads(monkeypatch)
    with pytest.raises(RecoveryError, match='regular'):
        recovery.import_bundle(source, tmp_path / 'imported')
    assert reads == [512]
    assert not (tmp_path / 'imported').exists()


@pytest.mark.parametrize('size', [-1, recovery.MAX_FILE + 1])
def test_raw_regular_header_size_is_bounded(tmp_path, monkeypatch, size):
    source = tmp_path / 'oversized.tar'
    source.write_bytes(header(tarfile.REGTYPE, size))
    reads = guard_reads(monkeypatch)
    with pytest.raises(RecoveryError, match='byte budget'):
        recovery.import_bundle(source, tmp_path / 'imported')
    assert reads == [512]
    assert not (tmp_path / 'imported').exists()


def test_plain_null_type_regular_records_still_restore(tmp_path):
    app = tmp_path / 'app'
    app.mkdir()
    (app / 'state.txt').write_text('saved state')
    store = Store(tmp_path / 'original')
    sid = store.capture({'profiles': [{'id': 'ide', 'state_dir': str(app)}]})['snapshot']
    source = tmp_path / 'source.tar'
    recovery.export_bundle(store, sid, source)
    compatible = tmp_path / 'null-type.tar'
    with tarfile.open(source) as original, tarfile.open(
            compatible, 'w', format=tarfile.USTAR_FORMAT) as output:
        for member in original:
            data = original.extractfile(member).read()
            member.type = tarfile.AREGTYPE
            output.addfile(member, io.BytesIO(data))

    destination = tmp_path / 'imported'
    result = recovery.import_bundle(compatible, destination)
    config = json.loads((destination / 'recovery-config.json').read_text())
    Store(destination, config['origin']).restore(sid, config, tmp_path / 'restored')
    assert result['apps_launched'] is False
    assert (tmp_path / 'restored/ide/state.txt').read_text() == 'saved state'
