"""Explicit window operations. Never focus a desktop or signal a process."""
from __future__ import annotations

import os
from pathlib import Path
import time

from .store import RecoveryError


class _InventoryChanged(RecoveryError):
    """A client disappeared while the window manager refreshed its list."""


def require_process_consent(entire_process):
    if entire_process is not True:
        raise RecoveryError(
            'A process may own several windows. Use window-close for one window; '
            '--entire-process explicitly permits closing ALL windows of the selected PID. '
            '--force does not grant this permission; no process signal sent.'
        )


def _process_start(pid):
    path = Path('/proc') / str(pid)
    if path.stat().st_uid != os.getuid():
        raise RecoveryError('Window process is not owned by the current user')
    return (path / 'stat').read_text().rsplit(')', 1)[1].split()[19]


class _X11Windows:
    def __init__(self):
        if os.environ.get('XDG_SESSION_TYPE', '').lower() == 'wayland':
            raise RecoveryError(
                'Native Wayland window identity/control is unavailable. '
                'No focus keystroke, force quit or process signal sent.'
            )
        try:
            from Xlib import X, Xatom, display, error, protocol
        except ImportError as exc:
            raise RecoveryError('X11 window control requires python-xlib') from exc
        self.X, self.Xatom, self.error, self.protocol = X, Xatom, error, protocol
        try:
            self.connection = display.Display()
        except (OSError, error.DisplayError) as exc:
            raise RecoveryError('Unable to connect to the X11 window manager') from exc

    def close(self):
        self.connection.close()

    def _property(self, window, name, kind):
        try:
            return window.get_full_property(self.connection.intern_atom(name), kind)
        except (OSError, self.error.ConnectionClosedError) as exc:
            raise RecoveryError('X11 window inventory connection closed') from exc

    def _describe(self, window):
        prop = self._property(window, '_NET_WM_PID', self.Xatom.CARDINAL)
        pid = int(prop.value[0]) if prop is not None and len(prop.value) == 1 else None
        title = self._property(window, '_NET_WM_NAME', self.connection.intern_atom('UTF8_STRING'))
        name = title.value.decode('utf-8', errors='replace') if title is not None else window.get_wm_name()
        try:
            start = _process_start(pid) if pid else None
        except (OSError, IndexError, RecoveryError):
            start = None
        return {'xid': window.id, 'pid': pid, 'start_ticks': start,
                'title': name or '', 'wm_class': list(window.get_wm_class() or ())}

    def read(self):
        prop = self._property(self.connection.screen().root, '_NET_CLIENT_LIST', self.Xatom.WINDOW)
        if prop is None:
            raise RecoveryError('The window manager provides no verified X11 client list')
        result = []
        for xid in prop.value:
            try:
                result.append(self._describe(self.connection.create_resource_object('window', int(xid))))
            except self.error.BadWindow:
                raise _InventoryChanged('Window inventory changed; observe it again') from None
        return result

    def request_close(self, expected):
        window = self.connection.create_resource_object('window', expected['xid'])
        if self._describe(window) != expected:
            raise RecoveryError('Window identity changed before the close request')
        delete = self.connection.intern_atom('WM_DELETE_WINDOW')
        protocols = self._property(window, 'WM_PROTOCOLS', self.Xatom.ATOM)
        if protocols is None or delete not in protocols.value:
            raise RecoveryError('The selected window has no graceful-close protocol')
        errors = []
        window.send_event(self.protocol.event.ClientMessage(
            window=window, client_type=self.connection.intern_atom('WM_PROTOCOLS'),
            data=(32, [delete, self.X.CurrentTime, 0, 0, 0])),
            event_mask=self.X.NoEventMask, propagate=False,
            onerror=lambda *args: errors.append(args))
        self.connection.sync()
        if errors:
            raise RecoveryError('X11 rejected the window-close request')


def window_inventory():
    backend = None
    try:
        backend = _X11Windows()
        windows = backend.read()
        return {'schema': 'uncrash.windows/v1', 'backend': 'x11',
                'window_count_verified': True, 'windows': windows,
                'creation_order_verified': False, 'process_signals_sent': False}
    except (OSError, RecoveryError) as exc:
        return {'schema': 'uncrash.windows/v1', 'backend': 'unavailable',
                'window_count_verified': False, 'windows': [],
                'creation_order_verified': False, 'reason': str(exc),
                'process_signals_sent': False}
    finally:
        if backend is not None:
            backend.close()


def close_one_window(xid, pid, start_ticks, *, title=None, wait_seconds=2.0, dry_run=False):
    """Request WM_DELETE_WINDOW and distinguish a request from verified closure."""
    if (type(xid) is not int or xid <= 0 or type(pid) is not int or pid <= 1
            or not str(start_ticks).isascii() or not str(start_ticks).isdecimal()):
        raise RecoveryError('Provide an explicit XID, PID and process start identity')
    if not 0 <= wait_seconds <= 10:
        raise RecoveryError('Window verification timeout must be 0..10 seconds')
    backend = _X11Windows()
    try:
        before = backend.read()
        matches = [w for w in before if w['xid'] == xid]
        if len(matches) != 1:
            raise RecoveryError('Explicit window is missing or ambiguous; no close requested')
        target = matches[0]
        if target['pid'] != pid or target['start_ticks'] != str(start_ticks):
            raise RecoveryError('Window process identity changed; no close requested')
        if not any('pycharm' in c.lower() for c in target['wm_class']):
            raise RecoveryError('Explicit target is not a PyCharm window')
        if title is not None and title != target['title']:
            raise RecoveryError('Window title changed; no close requested')
        peers = [w for w in before if w['pid'] == pid and w['xid'] != xid]
        result = {'schema': 'uncrash.window-close/v1', 'window': target,
                  'peer_windows_before': peers, 'process_signals_sent': False,
                  'close_requested': False, 'closure_verified': False,
                  'other_windows_preserved': None, 'status': 'dry-run'}
        if dry_run:
            return result
        backend.request_close(target)
        result.update(close_requested=True, status='close-requested')
        deadline = time.monotonic() + wait_seconds
        while True:
            try:
                after = backend.read()
                same_process = _process_start(pid) == str(start_ticks)
            except _InventoryChanged:
                if time.monotonic() >= deadline:
                    result.update(status='verification-unavailable', other_windows_preserved=None)
                    return result
                time.sleep(min(.05, max(0, deadline - time.monotonic())))
                continue
            except (OSError, RecoveryError):
                result['status'] = 'verification-unavailable'
                return result
            remaining = [w for w in after if w['pid'] == pid]
            result['peer_windows_after'] = [w for w in remaining if w['xid'] != xid]
            # Compare identities, not titles: an unrelated editor may change its title.
            identity = lambda w: (w['xid'], w['pid'], w['start_ticks'])
            result['other_windows_preserved'] = same_process and all(
                identity(p) in {identity(w) for w in remaining} for p in peers)
            if not same_process or not result['other_windows_preserved']:
                result['status'] = 'peer-or-process-changed'
                return result
            if not any(w['xid'] == xid for w in after):
                result.update(status='closed', closure_verified=True)
                return result
            if time.monotonic() >= deadline:
                return result
            time.sleep(min(.1, max(0, deadline - time.monotonic())))
    finally:
        backend.close()
