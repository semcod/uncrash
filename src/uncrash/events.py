"""Private canonical, hash-chained wellmanifest.logs/event/v1 observations."""
from datetime import datetime, timezone
import errno
import fcntl
import hashlib
import json
import os

from .store import RecoveryError, no_links, private_dir


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def error_code(exc):
    # Emit only a fixed code, never arbitrary exception text or source paths.
    if isinstance(exc, OSError):
        return {errno.ENOSPC: 'UNCRASH-STORAGE-FULL', errno.EACCES: 'UNCRASH-SOURCE-UNREADABLE',
                errno.ENOENT: 'UNCRASH-SOURCE-CHANGED'}.get(exc.errno, 'UNCRASH-CAPTURE-FAILED')
    if isinstance(exc, RecoveryError):
        message = str(exc).lower()
        if 'sqlite' in message: return 'UNCRASH-SQLITE-BACKUP'
        if 'budget' in message or 'oversized' in message: return 'UNCRASH-CAPTURE-BUDGET'
        if 'changed' in message or 'replaced' in message: return 'UNCRASH-SOURCE-CHANGED'
        if 'rust' in message: return 'UNCRASH-NATIVE-FAILED'
    return 'UNCRASH-CAPTURE-FAILED'


def append_event(root, *, event_type, code=None, outcome='OBSERVED', evidence=(), input_data=None,
                 subject_ref='application:uncrash'):
    now = datetime.now(timezone.utc)
    stream = 'uncrash-' + now.strftime('%Y%m%d-%H')
    path = no_links(private_dir(root / 'logs') / (stream + '.jsonl'))
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_APPEND, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise RecoveryError('Diagnostic log must be private and owned')
        if info.st_size > 4 * 1024**2: raise RecoveryError('Hourly diagnostic log budget exceeded')
        previous = '0' * 64; sequence = 0
        with os.fdopen(os.dup(fd), 'rb') as reader:
            reader.seek(0)
            for raw in reader:
                row = json.loads(raw)
                sequence += 1
                if (raw != (canonical(row) + '\n').encode() or row.get('sequence') != sequence
                    or row.get('previousHash') != previous or row.get('stream') != stream
                    or row.get('eventHash') != digest({k: v for k, v in row.items() if k != 'eventHash'})):
                    raise RecoveryError('Diagnostic event chain is invalid; existing evidence preserved')
                previous = row['eventHash']
        event = {'schema': 'wellmanifest.logs/event/v1', 'eventId': f'event:{stream}:{sequence + 1}',
                 'stream': stream, 'sequence': sequence + 1, 'eventType': event_type,
                 'severity': 'ERROR' if code else 'INFO', 'mode': 'APPLY',
                 'occurredAt': now.isoformat(timespec='microseconds').replace('+00:00', 'Z'),
                 'correlationId': 'uncrash-diagnostics', 'causationId': None,
                 'producer': 'service:uncrash', 'source': 'uncrash.diagnostics', 'code': code,
                 'subjectRef': subject_ref, 'outcome': outcome, 'subjectState': None,
                 'evidence': list(evidence), 'inputHash': digest(input_data or {}), 'receiptRef': None,
                 'previousHash': previous, 'rawOutputIncluded': False, 'secretMaterialIncluded': False}
        event['eventHash'] = digest(event)
        payload = (canonical(event) + '\n').encode()
        while payload:
            written = os.write(fd, payload)
            if not written: raise OSError('Diagnostic append did not progress')
            payload = payload[written:]
        os.fsync(fd)
        return event
    finally:
        os.close(fd)
