from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import threading
import time
import uuid

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .store import RecoveryError, no_links, private_dir, profiles, sync_dir, write_file


def start_ticks(pid):
    return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]


def pidfd(pid):
    if hasattr(os, 'pidfd_open'):
        return os.pidfd_open(pid)
    libc = ctypes.CDLL(None, use_errno=True)
    fn = libc.pidfd_open
    fn.argtypes = [ctypes.c_int, ctypes.c_uint]; fn.restype = ctypes.c_int
    result = fn(pid, 0)
    if result < 0:
        code = ctypes.get_errno(); raise OSError(code, os.strerror(code))
    return result


class Launcher:
    def __init__(self, store):
        self.store = store

    def records(self):
        plain = no_links(self.store.root/'owned-processes.json')
        if plain.exists(): return json.loads(plain.read_bytes())
        path = no_links(self.store.root/'owned-processes.enc')
        if not path.exists():
            return []
        return json.loads(self.store.decrypt(AESGCM(self.store.key()), 'owned-processes', 'records', path.read_bytes()))

    def save(self, records):
        data = json.dumps(records).encode()
        suffix = '.enc' if self.store.encryption else '.json'
        if self.store.encryption: data = self.store.encrypt(AESGCM(self.store.key()), 'owned-processes', 'records', data)
        temporary = self.store.root/('.processes-'+uuid.uuid4().hex)
        write_file(temporary, data)
        os.replace(temporary, self.store.root/('owned-processes'+suffix))
        alternate = self.store.root/('owned-processes'+('.json' if self.store.encryption else '.enc'))
        if alternate.exists(): alternate.unlink()
        sync_dir(self.store.root)

    def launch(self, config, receipt, display):
        if not re.fullmatch(r':[0-9]+(?:\.[0-9]+)?', display or ''):
            raise RecoveryError('Select an explicit X11 test display')
        if not receipt.get('completed'):
            raise RecoveryError('Cannot launch from an incomplete restore')
        selected = {p['id']: p for p in profiles(config)}
        with self.store.lock():
            existing = self.records()
            for record in existing:
                try:
                    if start_ticks(record['pid']) == record['start_ticks']:
                        raise RecoveryError('Owned applications are already running; stop them first')
                except FileNotFoundError:
                    pass
            launched = []
            try:
                for app in receipt['restored']:
                    argv = selected[app['id']]['argv']
                    if not argv:
                        continue
                    home = no_links(app['state_dir'])
                    env = {k: os.environ[k] for k in ['PATH', 'LANG', 'LC_ALL', 'TZ'] if k in os.environ}
                    env.update({'HOME': str(home), 'DISPLAY': display, 'GDK_BACKEND': 'x11',
                        'XDG_CONFIG_HOME': str(home/'.config'), 'XDG_CACHE_HOME': str(home/'.cache'),
                        'XDG_DATA_HOME': str(home/'.local/share'), 'UNCRASH_STATE_DIR': str(home)})
                    cmd = [s.replace('{state_dir}', str(home)).replace('{display}', display) for s in argv]
                    proc = subprocess.Popen(cmd, cwd=home, env=env, stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                    record = {'id': app['id'], 'pid': proc.pid, 'start_ticks': start_ticks(proc.pid)}
                    launched.append(record); self.save(launched)
            except BaseException:
                self.save(launched)
                raise
            return launched

    def stop(self):
        remaining, stopped = [], []
        with self.store.lock():
            for record in self.records():
                try:
                    fd = pidfd(record['pid'])
                except ProcessLookupError:
                    continue
                try:
                    try:
                        current = start_ticks(record['pid'])
                    except FileNotFoundError:
                        continue
                    if current != record['start_ticks']:
                        raise RecoveryError('Process identity changed; refusing to signal it')
                    try:
                        signal.pidfd_send_signal(fd, signal.SIGTERM)
                    except ProcessLookupError:
                        continue
                    if select.select([fd], [], [], 8)[0]:
                        stopped.append(record['id'])
                    else:
                        remaining.append(record)
                finally:
                    os.close(fd)
            self.save(remaining)
        if remaining:
            raise RecoveryError('An owned application did not stop; no forced global termination was attempted')
        return stopped


def recover_at_startup(store, config, display=None):
    if not config.get('startup_restore'):
        return {'status': 'disabled'}
    destination = config.get('recovery_destination')
    if not destination:
        raise RecoveryError('Startup restore requires a dedicated recovery destination')
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    marker = store.root/'recovered-boot'
    if marker.exists() and marker.read_text().strip() == boot:
        return {'status': 'already-recovered-this-boot'}
    failures = 0
    for sid in reversed(store.list()):
        target = Path(destination)/(boot+'-'+sid)
        if target.exists():
            # A prior partial restore is retained for inspection, not overwritten.
            target = target.with_name(target.name+'-'+uuid.uuid4().hex[:8])
        try:
            receipt = store.restore(sid, config, target)
        except (RecoveryError, OSError, ValueError):
            failures += 1; continue
        if display:
            receipt['launched'] = Launcher(store).launch(config, receipt, display)
        temporary = store.root/('.boot-'+uuid.uuid4().hex)
        write_file(temporary, boot.encode()); os.replace(temporary, marker); sync_dir(store.root)
        return {'status': 'restored', 'invalid_snapshots_skipped': failures, 'receipt': receipt}
    return {'status': 'no-valid-snapshot', 'invalid_snapshots_skipped': failures}


def run_daemon(store, config, *, stop=None, display=None):
    stop = stop or threading.Event()
    recover_at_startup(store, config, display or config.get('recovery_display'))
    interval = int(config.get('interval_seconds', 300))
    if not 5 <= interval <= 86400: raise RecoveryError('Snapshot interval must be 5..86400 seconds')
    while not stop.is_set():
        started = time.monotonic()
        try:
            result = store.capture(config)
            print(json.dumps({'event': 'snapshot', **result}), flush=True)
            event_type, code, outcome = 'uncrash.snapshot_completed', None, 'SUCCEEDED'
            subject = 'snapshot:' + result['snapshot']
        except (OSError, ValueError) as exc:
            # Do not print app paths, decrypted content, command lines or keys.
            from .events import error_code
            code = error_code(exc)
            event_type, outcome = 'error_raised', 'FAILED'
            subject = 'application:uncrash'
            print(json.dumps({'event': 'capture-failed', 'code': code,
                              'action': 'retry-at-next-snapshot-interval'}), flush=True)
        try:
            from .events import append_event
            append_event(store.root, event_type=event_type, code=code, outcome=outcome,
                         subject_ref=subject, input_data={'interval_seconds': interval})
        except (OSError, ValueError):
            print(json.dumps({'event': 'diagnostic-log-failed', 'code': 'UNCRASH-LOG-INVALID'}), flush=True)
        stop.wait(max(0, interval-(time.monotonic()-started)))
