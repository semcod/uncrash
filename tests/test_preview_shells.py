"""Execute synthetic preview plans without real agents, terminals or desktops."""
import os
import shlex
import subprocess

import pytest

from uncrash.preview import extract_preview_metadata, launch_terminal_tabs, VirtualPreviewDesktop


def fake_agent(tmp_path, provider):
    directory = tmp_path / 'bin'
    directory.mkdir(exist_ok=True)
    marker = tmp_path / 'agent-invoked'
    executable = directory / provider
    executable.write_text('#!/bin/sh\nprintf invoked > ' + shlex.quote(str(marker)) + '\n')
    executable.chmod(0o700)
    return {'PATH': str(directory) + os.pathsep + os.defpath}, marker


@pytest.mark.parametrize('provider', ['codex', 'agy', 'claude'])
@pytest.mark.parametrize('binding', [None, 'unresolved', 'verified'])
def test_recorded_process_does_not_select_or_start_an_agent(tmp_path, monkeypatch, provider, binding):
    import uncrash.inventory
    monkeypatch.setattr(uncrash.inventory, 'get_gpu_status', lambda: {})
    cwd = tmp_path / 'recorded project'
    cwd.mkdir()
    record = {'provider': provider, 'name': provider, 'role': 'client',
              'cwd': str(cwd), 'terminal': '/dev/pts/1',
              'conversation_id': '018fa418-652e-4f20-9fd0-311d075f83a0',
              'conversation_binding': binding}
    metadata = extract_preview_metadata({'session_hosts': {'processes': [record]}})
    tab = metadata['terminal_tabs'][0]
    assert tab['provider'] == provider and tab['cwd'] == str(cwd)
    planned = launch_terminal_tabs(metadata['terminal_tabs'], dry_run=True)['command']
    env, marker = fake_agent(tmp_path, provider)
    result = subprocess.run(planned[-3:], cwd=cwd, env=env, input='', text=True,
                            capture_output=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert not marker.exists(), 'Preview invoked an agent without independently verified session identity'


@pytest.mark.parametrize('provider', ['codex', 'agy', 'claude'])
def test_cached_launch_fields_cannot_restore_a_provider_command(tmp_path, provider):
    cwd = tmp_path / 'recorded project'
    cwd.mkdir()
    env, marker = fake_agent(tmp_path, provider)
    tab = {'title': provider, 'cwd': str(cwd), 'provider': provider,
           'resume_command': provider, 'shell_script': provider,
           'gnome_terminal_args': ['--tab', '--working-directory=' + str(cwd),
                                   '--', 'bash', '-c', provider]}
    planned = launch_terminal_tabs([tab], dry_run=True)['command']
    result = subprocess.run(planned[-3:], cwd=cwd, env=env, input='', text=True,
                            capture_output=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert not marker.exists(), 'Stored launch fields were executed instead of opening a plain shell'
    assert '--working-directory=' + str(cwd) in planned


@pytest.mark.parametrize('case', ['quoted-path', 'quoted-title', 'substitution-title', 'stored-command'])
def test_native_tab_script_treats_snapshot_text_as_data(tmp_path, monkeypatch, case):
    import uncrash.preview as preview
    marker = tmp_path / 'injected-command'
    name = "project's $(printf quoted)" if case == 'quoted-path' else 'project'
    cwd = tmp_path / name
    cwd.mkdir()
    title = 'recorded tab'
    if case == 'quoted-title':
        title = "'; touch " + shlex.quote(str(marker)) + '; #'
    elif case == 'substitution-title':
        title = '$(touch ' + shlex.quote(str(marker)) + ')'
    command = 'touch ' + shlex.quote(str(marker)) if case == 'stored-command' else 'exec bash'
    tab = {'title': title, 'provider': 'codex', 'cwd': str(cwd), 'resume_command': command}
    captured = []

    class Process:
        def poll(self):
            return None

    def capture(argv, **kwargs):
        captured.append(argv)
        return Process()

    # Only collect the actual Xterm invocation; no display or network process is started.
    with monkeypatch.context() as m:
        m.setattr(preview, '_find_free_display', lambda: 201)
        m.setattr(preview, '_find_free_port', lambda: 8021)
        m.setattr(preview.shutil, 'which', lambda name: '/usr/bin/' + name
                     if name in ('Xtigervnc', 'websockify', 'xterm') else None)
        m.setattr(preview.subprocess, 'Popen', capture)
        m.setattr(preview.time, 'sleep', lambda seconds: None)
        VirtualPreviewDesktop(tmp_path).start(terminal_tabs=[tab], interactive=True)
    terminals = [a for a in captured if a[0] == 'xterm']
    assert len(terminals) == 1
    script = terminals[0][-1]
    directory = tmp_path / 'shell-bin'
    directory.mkdir()
    shell = directory / 'bash'
    shell.write_text('#!/bin/sh\npwd\n')
    shell.chmod(0o700)
    result = subprocess.run(['/bin/bash', '-c', script], cwd=tmp_path,
                            env={'PATH': str(directory) + os.pathsep + os.defpath},
                            input='', text=True, capture_output=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert not marker.exists(), 'Recorded preview text or command executed shell code'
    assert result.stdout.splitlines()[-1] == str(cwd)
    assert title in result.stdout
