import copy
import asyncio
import os
import shutil
import subprocess
import threading
import time

import pytest

from uncrash import cli, window_control as control
from uncrash.store import RecoveryError


def window(xid, *, title='fixture', pid=123, start='456'):
    return {'xid': xid, 'pid': pid, 'start_ticks': start,
            'title': title, 'wm_class': ['pycharm', 'jetbrains-pycharm']}


@pytest.fixture
def backend(monkeypatch):
    class Backend:
        windows = [window(i) for i in range(1, 5)]
        requests = []
        disposed = False
        on_close = None

        def read(self):
            return copy.deepcopy(self.windows)

        def request_close(self, target):
            self.requests.append(target['xid'])
            if self.on_close:
                self.on_close(self)

        def close(self):
            self.disposed = True

    value = Backend()
    monkeypatch.setattr(control, '_X11Windows', lambda: value)
    monkeypatch.setattr(control, '_process_start', lambda pid: '456')
    return value


PROCESS_CLOSE_COMMANDS = [
    ['close-app', '123', '--start-ticks', '456'],
    ['apps', '--close', '123', '--start-ticks', '456'],
    ['pycharm', 'close', '--pid', '123', '--start-ticks', '456'],
    ['pycharm', '--close', '--pid', '123', '--start-ticks', '456'],
]


@pytest.mark.parametrize('command', PROCESS_CLOSE_COMMANDS)
@pytest.mark.parametrize('force', [[], ['--force']])
def test_cli_missing_consent_never_reaches_signal_function(monkeypatch, capsys, command, force):
    def forbidden(**kwargs):
        pytest.fail('Whole-process close reached without consent')
    monkeypatch.setattr(cli, 'close_gui_app', forbidden)
    assert cli.main(command + force) == 1
    assert '--entire-process' in capsys.readouterr().err


@pytest.mark.parametrize('command', PROCESS_CLOSE_COMMANDS)
def test_explicit_process_consent_preserves_existing_pid_fencing(monkeypatch, command):
    calls = []
    monkeypatch.setattr(cli, 'close_gui_app', lambda **kw: calls.append(kw) or {'status': 'fixture'})
    assert cli.main(command + ['--entire-process']) == 0
    assert len(calls) == 1
    assert calls[0]['pid'] == 123 and calls[0]['expected_start'] == '456'


def test_only_explicit_window_is_removed_from_four_shared_pid_windows(backend):
    backend.on_close = lambda b: setattr(b, 'windows', b.windows[:-1])
    result = control.close_one_window(4, 123, '456', title='fixture', wait_seconds=0)
    assert backend.requests == [4]
    assert result['status'] == 'closed' and result['closure_verified']
    assert result['other_windows_preserved']
    assert len(result['peer_windows_after']) == 3
    assert result['process_signals_sent'] is False and backend.disposed


def test_hung_window_stays_requested_without_force_fallback(backend):
    result = control.close_one_window(4, 123, '456', wait_seconds=0)
    assert result['status'] == 'close-requested'
    assert result['close_requested'] and not result['closure_verified']
    assert backend.requests == [4] and len(backend.windows) == 4


@pytest.mark.parametrize('persistent', [False, True])
def test_close_observation_retries_only_transient_inventory_within_deadline(backend, monkeypatch, persistent):
    read = backend.read
    failures = []

    def racing_read():
        if backend.requests and (persistent or not failures):
            failures.append(True)
            raise control._InventoryChanged('Window inventory changed; observe it again')
        return read()

    monkeypatch.setattr(backend, 'read', racing_read)
    backend.on_close = lambda b: setattr(b, 'windows', b.windows[:-1])
    result = control.close_one_window(4, 123, '456', wait_seconds=0 if persistent else 1)
    assert failures == [True] and backend.requests == [4]
    assert result['process_signals_sent'] is False
    if persistent:
        assert result['status'] == 'verification-unavailable'
        assert not result['closure_verified'] and result['other_windows_preserved'] is None
    else:
        assert result['status'] == 'closed' and result['other_windows_preserved']


@pytest.mark.parametrize('kwargs', [
    {'xid': 9}, {'pid': 999}, {'start_ticks': '789'}, {'title': 'different'},
])
def test_missing_or_stale_identity_has_no_effect(backend, kwargs):
    args = {'xid': 4, 'pid': 123, 'start_ticks': '456', 'wait_seconds': 0, **kwargs}
    with pytest.raises(RecoveryError):
        control.close_one_window(**args)
    assert backend.requests == [] and backend.disposed


def test_malformed_identity_does_not_even_open_desktop(monkeypatch):
    def forbidden():
        pytest.fail('Malformed identity reached the desktop backend')
    monkeypatch.setattr(control, '_X11Windows', forbidden)
    with pytest.raises(RecoveryError):
        control.close_one_window(4, 123, 'reused')


def test_unrelated_app_window_is_refused(backend):
    backend.windows[-1]['wm_class'] = ['terminal']
    with pytest.raises(RecoveryError, match='not a PyCharm'):
        control.close_one_window(4, 123, '456')
    assert not backend.requests


def test_dry_run_checks_identity_but_never_requests_close(backend):
    result = control.close_one_window(4, 123, '456', dry_run=True)
    assert result['status'] == 'dry-run' and not result['close_requested']
    assert backend.requests == []


def test_peer_loss_does_not_report_success(backend):
    backend.on_close = lambda b: setattr(b, 'windows', b.windows[:2])
    result = control.close_one_window(4, 123, '456', wait_seconds=0)
    assert result['status'] == 'peer-or-process-changed'
    assert not result['closure_verified'] and not result['other_windows_preserved']


def test_pid_reuse_after_close_request_does_not_report_success(backend, monkeypatch):
    monkeypatch.setattr(control, '_process_start', lambda pid: 'new-process')
    result = control.close_one_window(4, 123, '456', wait_seconds=0)
    assert result['status'] == 'peer-or-process-changed' and not result['closure_verified']


def test_target_vanishes_with_unverifiable_peer_inventory(backend):
    def disappear(b):
        def unavailable():
            raise RecoveryError('Compositor disconnected')
        b.read = unavailable
    backend.on_close = disappear
    result = control.close_one_window(4, 123, '456', wait_seconds=0)
    assert result['status'] == 'verification-unavailable'
    assert result['close_requested'] and not result['closure_verified']


def test_wayland_is_unknown_not_zero_and_no_signal_is_sent(monkeypatch):
    monkeypatch.setenv('XDG_SESSION_TYPE', 'wayland')
    report = control.window_inventory()
    assert not report['window_count_verified']
    assert report['backend'] == 'unavailable' and 'Wayland' in report['reason']
    with pytest.raises(RecoveryError, match='Wayland'):
        control.close_one_window(4, 123, '456')


def test_window_cli_returns_failure_for_only_requested_close(backend):
    assert cli.main(['window-close', '--xid', '4', '--pid', '123',
                     '--start-ticks', '456', '--wait-seconds', '0']) == 1
    assert backend.requests == [4]


@pytest.mark.parametrize('force', [False, True])
def test_rest_requires_whole_process_consent(monkeypatch, tmp_path, force):
    from fastapi.testclient import TestClient
    from uncrash import api
    from uncrash.store import Store
    calls = []
    monkeypatch.setattr(api, 'close_gui_app', lambda **kw: calls.append(kw) or {'status': 'fixture'})
    client = TestClient(api.create_fastapi_app(Store(tmp_path / 'store'), {'profiles': []}))
    body = {'pid': 123, 'expected_start': '456', 'force': force}
    result = client.post('/api/v1/apps/close', json=body)
    assert result.status_code == 400 and '--entire-process' in result.json()['detail']
    assert calls == []
    result = client.post('/api/v1/apps/close', json={**body, 'entire_process': True})
    assert result.status_code == 200
    assert len(calls) == 1 and calls[0]['expected_start'] == '456'


@pytest.mark.parametrize('force', [False, True])
def test_mcp_requires_consent_independently_of_force(monkeypatch, tmp_path, force):
    from uncrash import api
    from uncrash.store import Store
    calls = []
    monkeypatch.setattr(api, 'close_gui_app', lambda **kw: calls.append(kw) or {'status': 'fixture'})
    server = api.create_mcp_server(Store(tmp_path / 'store'), {'profiles': []})
    async def exercise():
        tools = await server.list_tools()
        tool = next(t for t in tools if t.name == 'uncrash_close_gui_app')
        schema = getattr(tool, 'inputSchema', None) or tool.input_schema
        assert schema['properties']['entire_process']['default'] is False
        body = {'pid': 123, 'expected_start': '456', 'force': force}
        try:
            refused = await server.call_tool('uncrash_close_gui_app', body)
        except Exception as exc:
            assert 'ALL windows' in str(exc)
        else:
            assert 'ALL windows' in str(refused.content)
        assert not calls
        await server.call_tool('uncrash_close_gui_app', {**body, 'entire_process': True})
        assert len(calls) == 1 and calls[0]['pid'] == 123
    asyncio.run(exercise())


NON_BOOLEAN_FLAGS = [0, 1, 0.0, 1.0, 'true', 'false', 'yes', 'no', None, [], {}]


@pytest.mark.parametrize('field', ['entire_process', 'force'])
@pytest.mark.parametrize('value', NON_BOOLEAN_FLAGS)
def test_rest_rejects_coerced_process_close_flags(monkeypatch, tmp_path, field, value):
    from fastapi.testclient import TestClient
    from uncrash import api
    from uncrash.store import Store
    calls = []
    monkeypatch.setattr(api, 'close_gui_app', lambda **kw: calls.append(kw) or {'status': 'fixture'})
    client = TestClient(api.create_fastapi_app(Store(tmp_path / 'store'), {'profiles': []}))
    body = {'pid': 123, 'expected_start': '456', 'entire_process': True, 'force': True, field: value}
    result = client.post('/api/v1/apps/close', json=body)
    assert result.status_code == 422
    assert any(error['loc'][-1] == field for error in result.json()['detail'])
    assert calls == []


@pytest.mark.parametrize('field', ['entire_process', 'force'])
@pytest.mark.parametrize('value', NON_BOOLEAN_FLAGS)
def test_mcp_rejects_coerced_process_close_flags(monkeypatch, tmp_path, field, value):
    from uncrash import api
    from uncrash.store import Store
    calls = []
    monkeypatch.setattr(api, 'close_gui_app', lambda **kw: calls.append(kw) or {'status': 'fixture'})
    server = api.create_mcp_server(Store(tmp_path / 'store'), {'profiles': []})
    async def exercise():
        body = {'pid': 123, 'expected_start': '456', 'entire_process': True, 'force': True, field: value}
        try:
            result = await server.call_tool('uncrash_close_gui_app', body)
        except Exception as exc:
            error = str(exc)
        else:
            error = str(result.content)
        assert calls == []
        assert field in error and ('bool' in error.lower() or 'validation' in error.lower())
    asyncio.run(exercise())


def test_real_x11_four_windows_one_process_close_one(monkeypatch, tmp_path):
    try:
        import Xlib
        from Xlib import X, Xatom, display
    except ImportError:
        return
    import shlex
    import sys
    if not shutil.which('Xvfb') or not shutil.which('openbox'):
        return
    read_fd, write_fd = os.pipe()
    xvfb = subprocess.Popen(['Xvfb', '-displayfd', str(write_fd), '-screen', '0', '1024x768x24', '-nolisten', 'tcp'],
                            pass_fds=(write_fd,), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.close(write_fd)
    wm = connection = None
    stop = threading.Event()
    worker = None
    try:
        import select
        assert select.select([read_fd], [], [], 5)[0], 'Owned Xvfb did not start'
        name = ':' + os.read(read_fd, 64).decode().strip()
        monkeypatch.setenv('DISPLAY', name)
        monkeypatch.setenv('XDG_SESSION_TYPE', 'x11')
        ready = tmp_path / 'openbox-ready'
        startup = shlex.join([sys.executable, '-I', '-B', '-c',
                              'from pathlib import Path; import sys; Path(sys.argv[1]).write_text("ready")',
                              str(ready)])
        wm = subprocess.Popen(['openbox', '--sm-disable', '--startup', startup],
                              env={**os.environ, 'DISPLAY': name, 'HOME': str(tmp_path)},
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        connection = display.Display(name)
        root = connection.screen().root
        end = time.monotonic() + 5
        # Supporting-window/redirect properties precede Openbox's event listener.
        # Its startup command runs only after that listener and client scan exist.
        while (not ready.is_file()
               or root.get_full_property(connection.intern_atom('_NET_SUPPORTING_WM_CHECK'), Xatom.WINDOW) is None
               or not root.get_attributes().all_event_masks & X.SubstructureRedirectMask):
            assert wm.poll() is None, 'Owned window manager exited during startup'
            assert time.monotonic() < end, 'Owned window manager did not start'
            time.sleep(.05)
        windows = []
        for i in range(4):
            w = root.create_window(20+i*50, 20+i*40, 200, 150, 0, X.CopyFromParent)
            w.set_wm_class('pycharm', 'jetbrains-pycharm')
            w.set_wm_name('Synthetic PyCharm ' + str(i))
            w.change_property(connection.intern_atom('_NET_WM_PID'), Xatom.CARDINAL, 32, [os.getpid()])
            w.set_wm_protocols([connection.intern_atom('WM_DELETE_WINDOW')])
            w.map()
            windows.append(w)
        connection.sync()
        end = time.monotonic() + 5
        while len(control.window_inventory()['windows']) != 4:
            assert wm.poll() is None, 'Owned window manager exited before registering clients'
            assert time.monotonic() < end, control.window_inventory()
            time.sleep(.05)
        received = []
        def serve():
            while not stop.is_set():
                if connection.pending_events():
                    event = connection.next_event()
                    if event.type == X.ClientMessage and event.client_type == connection.intern_atom('WM_PROTOCOLS'):
                        received.append(event.window.id)
                        event.window.destroy()
                        connection.sync()
                else:
                    time.sleep(.01)
        worker = threading.Thread(target=serve)
        worker.start()
        result = control.close_one_window(windows[-1].id, os.getpid(), control._process_start(os.getpid()), wait_seconds=3)
        assert result['status'] == 'closed' and result['other_windows_preserved']
        assert received == [windows[-1].id]
        assert {w['xid'] for w in control.window_inventory()['windows']} == {w.id for w in windows[:-1]}
    finally:
        os.close(read_fd)
        stop.set()
        if worker:
            worker.join(2)
        if connection:
            connection.close()
        for process in (wm, xvfb):
            if process is not None:
                process.terminate()
                process.wait(timeout=5)
