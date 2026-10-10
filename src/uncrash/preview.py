"""Preview recorded windows and terminal tabs from snapshots before restore with noVNC."""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .store import RecoveryError, no_links, Store


def _find_free_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def _temp_dir() -> Path:
    candidates = [
        Path(os.environ.get('TMPDIR', '/tmp')),
        Path('/tmp'),
        Path.home() / '.cache/tmp',
        Path.home() / '.local/state/uncrash/.tmp'
    ]
    for c in candidates:
        try:
            c.mkdir(parents=True, exist_ok=True)
            test_file = c / f'.write-test-{os.getpid()}'
            test_file.write_text('ok')
            test_file.unlink(missing_ok=True)
            return c
        except OSError:
            continue
    fallback = Path.home() / '.cache/tmp'
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def _find_free_display(start: int = 150, end: int = 400) -> int:
    for n in range(start, end):
        if not Path(f'/tmp/.X11-unix/X{n}').exists() and not Path(f'/tmp/.X{n}-lock').exists():
            return n
    raise RecoveryError('No available X11 display slot found for virtual preview')


def extract_preview_metadata(manifest: Dict[str, Any], snapshot_id: Optional[str] = None) -> Dict[str, Any]:
    """Extract terminal tabs, GUI applications, and project roots from a snapshot manifest."""
    sid = snapshot_id or manifest.get('id', 'unknown')
    created_at = manifest.get('created_at')
    profiles = [p.get('id') for p in manifest.get('profiles', []) if isinstance(p, dict)]

    # 1. Extract interactive terminal tabs from session_hosts and jetbrains
    session_hosts = manifest.get('session_hosts', {})
    processes = session_hosts.get('processes', []) if isinstance(session_hosts, dict) else []

    terminal_tabs = []
    seen_tabs = set()

    for p in processes:
        if not isinstance(p, dict):
            continue
        provider = p.get('provider')
        role = p.get('role', 'unknown')
        terminal = p.get('terminal')
        cwd = p.get('cwd') or str(Path.home())
        name = p.get('name', 'terminal')

        # Only pick interactive client terminals or recognized provider sessions
        is_client = role in ('client', 'unknown') and (terminal or provider in ('codex', 'agy', 'claude'))
        if not is_client:
            continue

        tab_key = (provider or name, cwd, terminal)
        if tab_key in seen_tabs:
            continue
        seen_tabs.add(tab_key)

        app_name = provider or name
        dir_name = Path(cwd).name or cwd
        title = f"{app_name} ({dir_name})"

        if provider == 'codex':
            resume_cmd = "codex resume --last"
        elif provider == 'agy':
            resume_cmd = "agy --continue"
        elif provider == 'claude':
            resume_cmd = "claude"
        else:
            resume_cmd = "exec bash"

        # Safe bash wrapper that runs resume command and stays in shell
        shell_script = f"cd {shlex.quote(cwd)} && {resume_cmd}; exec bash"

        terminal_tabs.append({
            'title': title,
            'provider': provider,
            'name': name,
            'role': role,
            'cwd': cwd,
            'terminal': terminal,
            'pid': p.get('pid'),
            'resume_command': resume_cmd,
            'shell_script': shell_script,
            'gnome_terminal_args': [
                '--tab',
                f'--title={title}',
                f'--working-directory={cwd}',
                '--',
                'bash',
                '-c',
                f'{resume_cmd}; exec bash'
            ]
        })

    # Also check JetBrains descendants with open terminals
    jb = manifest.get('jetbrains', {})
    if isinstance(jb, dict):
        descendants = jb.get('descendants', [])
        for d in descendants:
            if not isinstance(d, dict):
                continue
            term = d.get('terminal')
            cwd = d.get('cwd')
            if term and cwd:
                tab_key = ('jetbrains-terminal', cwd, term)
                if tab_key not in seen_tabs:
                    seen_tabs.add(tab_key)
                    dir_name = Path(cwd).name or cwd
                    title = f"terminal ({dir_name})"
                    terminal_tabs.append({
                        'title': title,
                        'provider': None,
                        'name': d.get('name', 'bash'),
                        'role': 'client',
                        'cwd': cwd,
                        'terminal': term,
                        'pid': d.get('pid'),
                        'resume_command': 'exec bash',
                        'shell_script': f"cd {shlex.quote(cwd)}; exec bash",
                        'gnome_terminal_args': [
                            '--tab',
                            f'--title={title}',
                            f'--working-directory={cwd}',
                            '--',
                            'bash'
                        ]
                    })

    # Construct the full gnome-terminal launch invocation
    system_terminal_command = ['gnome-terminal']
    for tab in terminal_tabs:
        system_terminal_command.extend(tab['gnome_terminal_args'])

    # Build one-liner launch script
    if terminal_tabs:
        launch_script = 'gnome-terminal ' + ' '.join(
            f'--tab --title={shlex.quote(t["title"])} --working-directory={shlex.quote(t["cwd"])} -- bash -c {shlex.quote(t["shell_script"])}'
            for t in terminal_tabs
        )
    else:
        launch_script = ""

    # 2. Extract JetBrains & GUI projects
    gui_projects = []
    if isinstance(jb, dict):
        open_projects = jb.get('open_projects') or []
        last_opened = jb.get('last_opened_project')
        last_closed = jb.get('last_closed_project')
        closed_projects = jb.get('closed_projects') or []
        for p in open_projects:
            gui_projects.append({'path': p, 'state': 'open', 'is_last': (p == last_opened)})
        for p in closed_projects:
            if p not in open_projects:
                gui_projects.append({'path': p, 'state': 'closed', 'is_last': (p == last_closed)})

    return {
        'schema': 'uncrash.snapshot-preview/v1',
        'snapshot': sid,
        'created_at': created_at,
        'profiles': profiles,
        'terminal_tabs': terminal_tabs,
        'terminal_tabs_count': len(terminal_tabs),
        'system_terminal_command': system_terminal_command,
        'launch_script': launch_script,
        'gui_projects': gui_projects,
        'gui_projects_count': len(gui_projects)
    }


def launch_terminal_tabs(terminal_tabs: List[Dict[str, Any]], *, dry_run: bool = False) -> Dict[str, Any]:
    """Launch recorded terminal tabs in the system terminal (gnome-terminal)."""
    if not terminal_tabs:
        return {'status': 'empty', 'message': 'No terminal tabs found in snapshot metadata'}

    cmd = ['gnome-terminal']
    for tab in terminal_tabs:
        cmd.extend(tab['gnome_terminal_args'])

    if dry_run:
        return {
            'status': 'planned',
            'dry_run': True,
            'command': cmd,
            'tabs_count': len(terminal_tabs)
        }

    gnome_term = shutil.which('gnome-terminal')
    if not gnome_term:
        raise RecoveryError('gnome-terminal not found; run the generated launch_script in your terminal emulator')

    proc = subprocess.Popen(cmd, start_new_session=True)
    return {
        'status': 'launched',
        'pid': proc.pid,
        'tabs_count': len(terminal_tabs),
        'command': cmd
    }


class VirtualPreviewDesktop:
    """Manages an isolated virtual X11 display with TigerVNC and noVNC."""

    def __init__(self, novnc_dir: Optional[Path] = None, *, width: int = 1280, height: int = 800):
        default_novnc = Path(os.environ.get('UNCRASH_NOVNC_ASSETS', '/usr/share/novnc'))
        self.novnc_dir = Path(novnc_dir or default_novnc).resolve()
        self.width = width
        self.height = height
        self.display: Optional[int] = None
        self.rfb_port: Optional[int] = None
        self.ws_port: Optional[int] = None
        self.processes: List[subprocess.Popen] = []

    def start(self,
              summary_text: Optional[str] = None,
              terminal_tabs: Optional[List[Dict[str, Any]]] = None,
              port: Optional[int] = None,
              interactive: bool = False) -> Dict[str, Any]:
        """Start Xtigervnc, window manager, websockify and preview windows."""
        vnc_bin = shutil.which('Xtigervnc') or shutil.which('Xvfb')
        if not vnc_bin:
            raise RecoveryError('Xtigervnc or Xvfb executable not found for virtual desktop preview')

        websockify_bin = shutil.which('websockify') or shutil.which('twinerd-bridge')
        if not websockify_bin:
            raise RecoveryError('websockify or twinerd-bridge not found for noVNC preview')

        self.display = _find_free_display()
        self.rfb_port = _find_free_port()
        self.ws_port = port or _find_free_port()

        env = {key: os.environ[key] for key in ('PATH', 'LANG', 'LC_ALL', 'TZ', 'HOME') if key in os.environ}
        display_str = f':{self.display}'
        env['DISPLAY'] = display_str

        # 1. Start Xtigervnc
        vnc_cmd = [
            vnc_bin, display_str,
            '-geometry', f'{self.width}x{self.height}',
            '-depth', '24',
            '-rfbport', str(self.rfb_port),
            '-localhost',
            '-SecurityTypes', 'None',
            '-AlwaysShared',
            '-ac',
            '-s', '0'
        ]
        p_vnc = subprocess.Popen(vnc_cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.processes.append(p_vnc)

        # Wait briefly for VNC server to accept connections
        time.sleep(0.5)

        # 2. Set root desktop background color
        if shutil.which('xsetroot'):
            subprocess.run(['xsetroot', '-solid', '#1e1e2e'], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # 3. Start Openbox window manager if present
        if shutil.which('openbox'):
            p_wm = subprocess.Popen(['openbox', '--sm-disable'], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.processes.append(p_wm)
            time.sleep(0.4)

        # 4. Start websockify / twinerd-bridge
        if 'twinerd-bridge' in str(websockify_bin):
            ws_cmd = [websockify_bin, '--listen', f'127.0.0.1:{self.ws_port}', '--target', f'127.0.0.1:{self.rfb_port}', '--web', str(self.novnc_dir)]
        else:
            ws_cmd = [websockify_bin, '--web', str(self.novnc_dir), str(self.ws_port), f'127.0.0.1:{self.rfb_port}']
        p_ws = subprocess.Popen(ws_cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.processes.append(p_ws)

        # 5. Launch windows
        if shutil.which('xterm'):
            if interactive:
                # Interactive workspace mode: launch actual interactive shells for each tab
                tabs = terminal_tabs if terminal_tabs else [{'title': 'Interactive Shell', 'provider': 'shell', 'cwd': str(Path.home()), 'resume_command': 'bash'}]
                total = min(len(tabs), 6)
                cols = 2 if total <= 4 else 3
                w_geom = 70 if cols == 2 else 56
                h_geom = 22 if total <= 2 else 18
                for idx, tab in enumerate(tabs[:6]):
                    prov = (tab.get('provider') or 'shell').upper()
                    cwd = tab.get('cwd') or str(Path.home())
                    resume_cmd = tab.get('resume_command') or 'echo Ready'
                    col = idx % cols
                    row = idx // cols
                    pos_x = 30 + (col * (1200 // cols))
                    pos_y = 40 + (row * 370)
                    fg = '#89b4fa' if prov == 'AGY' else '#a6e3a1' if prov == 'CODEX' else '#fab387' if prov == 'CLAUDE' else '#cdd6f4'
                    sh_cmd = (
                        f"cd '{cwd}' && "
                        f"echo '=== Uncrash Workspace [{prov}]: {tab.get('title')} ===' && "
                        f"echo 'Katalog roboczy: {cwd}' && "
                        f"echo 'Wznowienie:      {resume_cmd}' && "
                        f"echo '===================================================' && "
                        f"{resume_cmd}; exec bash"
                    )
                    tab_cmd = [
                        'xterm',
                        '-T', f"[{prov}] {tab.get('title')}",
                        '-geometry', f'{w_geom}x{h_geom}+{pos_x}+{pos_y}',
                        '-bg', '#181825',
                        '-fg', fg,
                        '-e', 'bash', '-c', sh_cmd
                    ]
                    p_tab = subprocess.Popen(tab_cmd, env=env)
                    self.processes.append(p_tab)
            else:
                # Preview mode: static/held windows with commands and summary overview
                tabs_to_show = (terminal_tabs or [])[:2]
                for idx, tab in enumerate(tabs_to_show):
                    prov = (tab.get('provider') or 'shell').upper()
                    tab_file = _temp_dir() / f'.uncrash-tab-{self.display}-{idx}.txt'
                    tab_file.write_text(
                        f"[{prov}] {tab.get('title')}\n"
                        f"Working Dir: {tab.get('cwd')}\n"
                        f"Command:     {tab.get('resume_command')}\n"
                        f"Terminal:    {tab.get('terminal', 'none')}\n"
                        f"{'=' * 50}\n"
                        f"$ cd {tab.get('cwd')}\n"
                        f"$ {tab.get('resume_command')}\n"
                    )
                    pos_x = 480 + (idx * 60)
                    pos_y = 60 + (idx * 160)
                    tab_cmd = [
                        'xterm',
                        '-T', f"{prov}: {tab.get('title')}",
                        '-geometry', f'65x16+{pos_x}+{pos_y}',
                        '-bg', '#181825',
                        '-fg', '#89b4fa' if prov == 'AGY' else '#a6e3a1' if prov == 'CODEX' else '#cdd6f4',
                        '-hold',
                        '-e', 'cat', str(tab_file)
                    ]
                    p_tab = subprocess.Popen(tab_cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    self.processes.append(p_tab)

                if summary_text:
                    summary_file = _temp_dir() / f'.uncrash-preview-{self.display}.txt'
                    summary_file.write_text(summary_text)
                    term_cmd = [
                        'xterm',
                        '-T', 'Uncrash Snapshot Overview',
                        '-geometry', '80x30+40+40',
                        '-bg', '#11111b',
                        '-fg', '#cdd6f4',
                        '-hold',
                        '-e', 'cat', str(summary_file)
                    ]
                    p_term = subprocess.Popen(term_cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    self.processes.append(p_term)

        # Allow windows to map and decorate
        time.sleep(0.8)

        novnc_url = f'http://127.0.0.1:{self.ws_port}/vnc.html?autoconnect=true&resize=scale'
        return {
            'display': display_str,
            'rfb_port': self.rfb_port,
            'ws_port': self.ws_port,
            'novnc_url': novnc_url,
            'status': 'running'
        }

    def capture_screenshot(self, destination: Path) -> Path:
        """Capture the virtual display framebuffer to a PNG image."""
        if not self.display:
            raise RecoveryError('Virtual display not started')
        destination = Path(destination).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.unlink(missing_ok=True)

        env = {**os.environ, 'DISPLAY': f':{self.display}'}
        time.sleep(0.8)  # allow windows to complete map and render

        # Try ffmpeg x11grab first (most accurate on virtual X11 framebuffers)
        if shutil.which('ffmpeg'):
            ff_cmd = [
                'ffmpeg', '-y', '-f', 'x11grab', '-draw_mouse', '0',
                '-i', f':{self.display}.0',
                '-frames:v', '1', str(destination)
            ]
            subprocess.run(ff_cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if destination.exists() and destination.stat().st_size > 3500:
                return destination

        # Fallback to scrot with overwrite
        scrot_bin = shutil.which('scrot')
        if scrot_bin:
            destination.unlink(missing_ok=True)
            subprocess.run([scrot_bin, '--overwrite', '--display', f':{self.display}', str(destination)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if destination.exists() and destination.stat().st_size > 3500:
                return destination

        # Fallback to xwd + convert or xwd + ffmpeg
        xwd_bin = shutil.which('xwd')
        if xwd_bin:
            temp_xwd = destination.with_suffix('.xwd')
            subprocess.run([xwd_bin, '-display', f':{self.display}', '-root', '-out', str(temp_xwd)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if shutil.which('convert'):
                subprocess.run(['convert', str(temp_xwd), str(destination)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif shutil.which('ffmpeg'):
                subprocess.run(['ffmpeg', '-y', '-i', str(temp_xwd), str(destination)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            temp_xwd.unlink(missing_ok=True)
            if destination.exists() and destination.stat().st_size > 3500:
                return destination

        if destination.exists():
            return destination
        raise RecoveryError('Failed to capture non-empty screenshot from virtual display')

    def stop(self) -> None:
        """Terminate all background desktop processes and clean up."""
        for p in reversed(self.processes):
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait(timeout=1)
        self.processes.clear()


@dataclass
class WorkspaceSession:
    """Active instance of an isolated multi-tab noVNC workspace."""
    workspace_id: str
    snapshot_id: str
    name: str
    display: str
    rfb_port: int
    ws_port: int
    novnc_url: str
    tabs_count: int
    created_at: str
    desktop: VirtualPreviewDesktop
    terminal_tabs: List[Dict[str, Any]]

    def is_alive(self) -> bool:
        return any(p.poll() is None for p in self.desktop.processes)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'workspace_id': self.workspace_id,
            'snapshot_id': self.snapshot_id,
            'name': self.name,
            'display': self.display,
            'rfb_port': self.rfb_port,
            'ws_port': self.ws_port,
            'novnc_url': self.novnc_url,
            'tabs_count': self.tabs_count,
            'created_at': self.created_at,
            'status': 'running' if self.is_alive() else 'stopped',
            'terminal_tabs': self.terminal_tabs
        }


class WorkspaceManager:
    """Manages isolated noVNC workspaces for snapshots via Twinerd / TigerVNC."""

    def __init__(self):
        self.workspaces: Dict[str, WorkspaceSession] = {}
        self._lock = threading.RLock()

    def list_workspaces(self) -> List[Dict[str, Any]]:
        with self._lock:
            dead = [wid for wid, ws in self.workspaces.items() if not ws.is_alive()]
            for wid in dead:
                self.workspaces.pop(wid, None)
            return [ws.to_dict() for ws in self.workspaces.values()]

    def get_workspace(self, workspace_id: str) -> Optional[WorkspaceSession]:
        with self._lock:
            ws = self.workspaces.get(workspace_id)
            if ws and ws.is_alive():
                return ws
            if ws and not ws.is_alive():
                self.workspaces.pop(workspace_id, None)
            return None

    def create_or_get_workspace(self,
                                snapshot_id: str,
                                terminal_tabs: List[Dict[str, Any]],
                                workspace_id: Optional[str] = None,
                                name: Optional[str] = None,
                                force_new: bool = False,
                                port: Optional[int] = None) -> WorkspaceSession:
        with self._lock:
            if workspace_id:
                wid = workspace_id
            elif force_new:
                wid = f"ws-{snapshot_id}-{int(time.time()) % 100000:05d}"
            else:
                wid = f"ws-{snapshot_id}"

            if not force_new and wid in self.workspaces and self.workspaces[wid].is_alive():
                return self.workspaces[wid]

            desktop = VirtualPreviewDesktop()
            info = desktop.start(terminal_tabs=terminal_tabs, port=port, interactive=True)
            ws_name = name or f"Workspace ({snapshot_id[:16]})"
            session = WorkspaceSession(
                workspace_id=wid,
                snapshot_id=snapshot_id,
                name=ws_name,
                display=info['display'],
                rfb_port=info['rfb_port'],
                ws_port=info['ws_port'],
                novnc_url=info['novnc_url'],
                tabs_count=len(terminal_tabs),
                created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                desktop=desktop,
                terminal_tabs=terminal_tabs
            )
            self.workspaces[wid] = session
            return session

    def close_workspace(self, workspace_id: str) -> bool:
        with self._lock:
            ws = self.workspaces.pop(workspace_id, None)
            if ws:
                ws.desktop.stop()
                return True
            return False


workspace_manager = WorkspaceManager()


def preview_snapshot(store: Store,
                     snapshot: str = 'latest',
                     config: Optional[Dict[str, Any]] = None,
                     *,
                     novnc: bool = False,
                     port: Optional[int] = None,
                     screenshot: Optional[Path] = None,
                     launch_tabs: bool = False,
                     dry_run: bool = False) -> Dict[str, Any]:
    """Inspect snapshot metadata, generate tab launch configurations, and optionally display via noVNC."""
    sid, path, cipher, manifest = store.load(snapshot)
    metadata = extract_preview_metadata(manifest, sid)

    if launch_tabs:
        metadata['tabs_launch_result'] = launch_terminal_tabs(metadata['terminal_tabs'], dry_run=dry_run)

    if novnc or screenshot:
        summary_lines = [
            "=" * 70,
            f" UNCRASH SNAPSHOT PREVIEW: {sid}",
            f" Captured at: {metadata.get('created_at', 'unknown')}",
            "=" * 70,
            "",
            f"Profiles backed up: {', '.join(metadata['profiles'])}",
            "",
            f"Recorded Terminal Tabs ({metadata['terminal_tabs_count']}):",
        ]
        for idx, tab in enumerate(metadata['terminal_tabs'], 1):
            summary_lines.append(f"  [{idx}] {tab['title']}")
            summary_lines.append(f"      Working Dir: {tab['cwd']}")
            summary_lines.append(f"      Command:     {tab['resume_command']}")
            if tab.get('terminal'):
                summary_lines.append(f"      TTY:         {tab['terminal']}")
            summary_lines.append("")

        if metadata['gui_projects']:
            summary_lines.append(f"JetBrains / GUI Projects ({metadata['gui_projects_count']}):")
            for proj in metadata['gui_projects']:
                status = " (active)" if proj.get('is_last') else ""
                summary_lines.append(f"  • [{proj['state']}] {proj['path']}{status}")
            summary_lines.append("")

        summary_lines.append("=" * 70)
        summary_lines.append("To launch all tabs in your terminal:")
        summary_lines.append(metadata.get('launch_script', ''))
        summary_lines.append("=" * 70)
        summary_text = "\n".join(summary_lines)

        desktop = VirtualPreviewDesktop()
        try:
            desktop_info = desktop.start(summary_text=summary_text, terminal_tabs=metadata.get('terminal_tabs', []), port=port)
            metadata['novnc'] = desktop_info
            if screenshot:
                shot_path = desktop.capture_screenshot(screenshot)
                metadata['screenshot'] = str(shot_path)
            # If novnc requested without screenshot-only, keep running in background or return
            if not novnc and screenshot:
                desktop.stop()
        except Exception as exc:
            desktop.stop()
            metadata['novnc_error'] = str(exc)

    return metadata
