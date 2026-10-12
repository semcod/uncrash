from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading

from .inventory import desktop_inventory
from .contracts import parse_restore_action, process_export
from .native import discover, selected_config, save_config
from .runtime import Launcher, recover_at_startup, run_daemon
from .store import RecoveryError, Store, build_native, no_links, private_dir, profiles, write_file
from .window_control import close_one_window, require_process_consent, window_inventory
from .health import inspect_health
from .installation import service_interpreter
from .recovery import (export_bundle, import_bundle, transfer_bundle, jetbrains_state,
                       detected_gui_apps, close_gui_app, find_pycharm_executable, jetbrains_projects, restore_pycharm)



from .configuration import (FIELDS, SettingsError, activate_environment_file,
                            environment_settings as _environment_settings, runtime_settings, reset_environment_file)

ENV_SETTINGS = {name: (key, kind) for name, (key, kind, _) in FIELDS.items()}


def environment_settings(path, environ=None, *, include_defaults=True):
    try:
        return _environment_settings(path, environ, include_defaults=include_defaults)
    except SettingsError as exc:
        raise RecoveryError(str(exc)) from exc


def _main(argv=None):
    parser = argparse.ArgumentParser(description='Fast local snapshots with optional encryption and explicit application recovery')
    parser.add_argument('--state', type=Path)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--encrypt', action=argparse.BooleanOptionalAction, default=None)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('inventory')
    doctor = sub.add_parser('doctor', help='Read-only freeze risk inspection before adding application load')
    doctor.add_argument('--log-dir', type=Path)
    doctor.add_argument('--thread-dump', type=Path, help='Existing Java thread dump; does not attach to the JVM')
    doctor.add_argument('--project', type=Path)
    doctor.add_argument('--pid', type=int)
    doctor.add_argument('--start-ticks')
    doctor.add_argument('--max-age-seconds', type=int, default=None)
    doctor.add_argument('--preflight', action='store_true', help='Exit 0 for no risk observed, 1 warning, 2 critical, 3 unknown')
    diagnostic = sub.add_parser('diagnose', help='Read-only session origins and backup health')
    diagnostic.add_argument('--output', type=Path, help='New private report directory')
    native = sub.add_parser('profiles', help='Discover or explicitly select native durable data')
    native.add_argument('--select', action='append', default=[])
    native.add_argument('--apply', action='store_true')
    sub.add_parser('snapshot')
    sub.add_parser('list')
    sub.add_parser('daemon')
    sub.add_parser('stop-owned')
    restore = sub.add_parser('restore')
    restore.add_argument('snapshot', nargs='?', default='latest')
    restore.add_argument('--destination', type=Path, required=True)
    restore.add_argument('--replace', action='store_true')
    restore.add_argument('--display')
    preview_parser = sub.add_parser('preview', help='Preview windows and terminal tabs from a snapshot before restore')
    preview_parser.add_argument('snapshot', nargs='?', default='latest', help='Snapshot ID or "latest"')
    preview_parser.add_argument('--novnc', action='store_true', help='Start an isolated virtual desktop preview with noVNC')
    preview_parser.add_argument('--port', type=int, help='Custom WebSocket port for noVNC')
    preview_parser.add_argument('--screenshot', type=Path, help='Capture and save a screenshot PNG of the preview display')
    preview_parser.add_argument('--launch-tabs', action='store_true', help='Launch recorded terminal tabs in system terminal (gnome-terminal)')
    preview_parser.add_argument('--dry-run', action='store_true', help='Report planned tab launch without executing')
    preview_parser.add_argument('--json', action='store_true', help='Output in JSON format')
    startup = sub.add_parser('startup-restore')
    startup.add_argument('--display')
    sub.add_parser('install-user')
    sub.add_parser('build-native')
    sub.add_parser('jetbrains', help='Inspect JVM identities and persisted projects without closing windows')
    apps_parser = sub.add_parser('apps', help='List detected windowed/GUI applications or close a targeted app')
    apps_parser.add_argument('--close', nargs='?', const='__default__', help='Close an explicit whole-process PID; requires --start-ticks')
    apps_parser.add_argument('--start-ticks')
    apps_parser.add_argument('--force', action='store_true', help='Force kill if process does not exit promptly')
    apps_parser.add_argument('--entire-process', action='store_true', help='Explicitly allow closing ALL windows of the selected PID')
    apps_parser.add_argument('--json', action='store_true', help='Output in JSON format')
    close_app_parser = sub.add_parser('close-app', help='Close one explicit application process with PID/start identity')
    close_app_parser.add_argument('target', nargs='?', default=None, help='Explicit PID from apps --json; this closes the whole process')
    close_app_parser.add_argument('--start-ticks')
    close_app_parser.add_argument('--force', action='store_true', help='Force kill if process does not exit promptly')
    close_app_parser.add_argument('--entire-process', action='store_true', help='Explicitly allow closing ALL windows of the selected PID')
    pycharm_parser = sub.add_parser('pycharm', help='Inspect, close, or restore JetBrains PyCharm projects')
    pycharm_parser.add_argument('action', nargs='?', choices=['status', 'close', 'restore'], default=None, help='Action to perform: status, close, or restore')
    pycharm_parser.add_argument('--restore', '--restore-last', action='store_true', dest='restore', help='Reopen/restore the last closed PyCharm project')
    pycharm_parser.add_argument('--close', action='store_true', help='Close ALL windows of an explicit PyCharm PID; requires --entire-process')
    pycharm_parser.add_argument('--entire-process', action='store_true', help='Explicitly allow closing ALL windows of the selected PID')
    pycharm_parser.add_argument('--force', action='store_true', help='Force kill if process does not exit promptly')
    pycharm_parser.add_argument('--project', help='Specific project directory path')
    pycharm_parser.add_argument('--executable', help='Specific PyCharm executable binary path')
    pycharm_parser.add_argument('--dry-run', action='store_true', help='Report planned action without launching or terminating')
    pycharm_parser.add_argument('--start-ticks')
    pycharm_parser.add_argument('--pid', type=int, help='Target process PID for close operation')
    pycharm_parser.add_argument('--preflight', action='store_true', help='Require a clear risk check before restore; needs an explicit --project')
    pycharm_parser.add_argument('--log-dir', type=Path, help='IDE log directory for restore preflight; discovers bounded saved thread dumps')
    pycharm_parser.add_argument('--thread-dump', type=Path, help='Existing Java dump for restore preflight')
    pycharm_parser.add_argument('--max-age-seconds', type=int, default=None)
    window = sub.add_parser('window-close', help='Request one explicit X11 window close with PID/start fencing')
    window.add_argument('--xid', type=lambda v: int(v, 0), required=True)
    window.add_argument('--pid', type=int, required=True)
    window.add_argument('--start-ticks', required=True)
    window.add_argument('--title', help='Expected exact window title; refuse if it changed')
    window.add_argument('--wait-seconds', type=float, default=2, help='Verify closure for at most 0..10 seconds; never force quit')
    window.add_argument('--dry-run', action='store_true', help='Verify the explicit window without requesting a close')
    sub.add_parser('windows', help='Inspect live window identities; never infer the newest window from PID or focus order')
    bundle = sub.add_parser('bundle-export', help='Export one portable snapshot archive without its encryption key')
    bundle.add_argument('snapshot', nargs='?', default='latest')
    bundle.add_argument('--destination', type=Path, required=True)
    bundle = sub.add_parser('bundle-import', help='Import into a new separate store; no application launch')
    bundle.add_argument('source', type=Path)
    bundle.add_argument('--destination', type=Path, required=True)
    bundle = sub.add_parser('bundle-transfer', help='Verified SSH upload into the remote private Uncrash inbox')
    bundle.add_argument('source', type=Path)
    bundle.add_argument('--host', required=True)
    bundle.add_argument('--name')
    bundle.add_argument('--timeout', type=int, default=None)
    serve_parser = sub.add_parser('serve', help='Run REST API server conforming to wellmanifest/nl-api-llm')
    serve_parser.add_argument('--host', default=None, help='Host interface to bind')
    serve_parser.add_argument('--port', type=int, default=None, help='Port to listen on')
    mcp_parser = sub.add_parser('mcp', help='Run MCP server conforming to wellmanifest/skills')
    mcp_parser.add_argument('--transport', choices=['stdio', 'sse', 'streamable-http'], default=None, help='MCP transport')
    mcp_parser.add_argument('--host', default=None, help='Host for network transport')
    mcp_parser.add_argument('--port', type=int, default=None, help='Port for network transport')
    export = sub.add_parser('export')
    export.add_argument('snapshot', nargs='?', default='latest')
    action = sub.add_parser('action')
    action.add_argument('uri')
    args = parser.parse_args(argv)

    try:
        if args.env_file is not None:
            if not args.env_file.exists():
                raise RecoveryError('Requested environment file does not exist')
            activate_environment_file(args.env_file)
        if args.command in ('doctor', 'pycharm') and getattr(args, 'max_age_seconds', None) is None:
            args.max_age_seconds = runtime_settings()['health_max_age_seconds']
        if args.command == 'bundle-transfer' and args.timeout is None:
            args.timeout = runtime_settings()['transfer_timeout_seconds']
        if args.command == 'doctor':
            report = inspect_health(log_dir=args.log_dir, thread_dump=args.thread_dump,
                                    project=args.project, pid=args.pid, expected_start=args.start_ticks,
                                    max_age_seconds=args.max_age_seconds)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return report['preflight_exit_code'] if args.preflight else 0
        if args.command == 'inventory':
            print(json.dumps(desktop_inventory(), ensure_ascii=False, indent=2)); return 0
        if args.command == 'jetbrains':
            print(json.dumps(jetbrains_state(), ensure_ascii=False, indent=2)); return 0
        if args.command == 'pycharm':
            is_restore = args.restore or (getattr(args, 'action', None) == 'restore')
            is_close = args.close or (getattr(args, 'action', None) == 'close')
            if args.preflight and (not is_restore or is_close or not args.project):
                raise RecoveryError('Restore preflight requires restore and an explicit --project; cannot combine with close')
            if is_restore:
                if args.preflight:
                    report = inspect_health(log_dir=args.log_dir, thread_dump=args.thread_dump,
                                            project=args.project, pid=args.pid, expected_start=args.start_ticks,
                                            max_age_seconds=args.max_age_seconds)
                    if report['preflight_exit_code']:
                        print(json.dumps({'action': 'restore-pycharm', 'status': 'blocked_by_preflight',
                                          'launched': False, 'preflight': report}, ensure_ascii=False, indent=2))
                        return report['preflight_exit_code']
                    result = restore_pycharm(project=args.project, executable=args.executable, dry_run=args.dry_run)
                    print(json.dumps({'action': 'restore-pycharm', 'preflight': report,
                                      'restore': result}, ensure_ascii=False, indent=2))
                    return 0
                print(json.dumps(restore_pycharm(project=args.project, executable=args.executable, dry_run=args.dry_run), ensure_ascii=False, indent=2))
                return 0
            if is_close:
                if args.dry_run:
                    print(json.dumps({'action': 'close-process', 'pid': args.pid, 'start_ticks': args.start_ticks,
                                      'scope': 'ALL windows of the selected PID',
                                      'entire_process_consent': args.entire_process,
                                      'signals_sent': False})); return 0
                require_process_consent(args.entire_process)
                res = close_gui_app(pid=args.pid, name='pycharm', force=args.force, expected_start=args.start_ticks)
                print(json.dumps(res, ensure_ascii=False, indent=2))
                return 0
            jb = jetbrains_state()
            pj = jetbrains_projects(selector_filter='pycharm')
            exe = find_pycharm_executable()
            report = {
                'running_processes': jb['processes'],
                'root_ide_candidates': jb['root_ide_candidates'],
                'executable': exe,
                'last_opened_project': pj['last_opened'],
                'last_closed_project': pj['last_closed'],
                'open_projects': pj['open_projects'],
                'closed_projects': pj['closed_projects'],
                'all_recent_projects': pj['projects'][:10],
            }
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0

        if args.command == 'apps':
            if args.close:
                require_process_consent(args.entire_process)
                target_arg = None if args.close == '__default__' else args.close
                target_pid = int(target_arg) if target_arg and target_arg.isdigit() else None
                target_name = target_arg if target_arg and not target_arg.isdigit() else None
                res = close_gui_app(pid=target_pid, name=target_name, force=args.force, expected_start=args.start_ticks)
                print(json.dumps(res, ensure_ascii=False, indent=2))
                return 0
            gui_apps = detected_gui_apps()
            if args.json:
                print(json.dumps({'schema': 'uncrash.gui-apps/v1', 'applications': gui_apps}, ensure_ascii=False, indent=2))
            else:
                if not gui_apps:
                    print('No windowed applications detected.')
                else:
                    print(f'Detected {len(gui_apps)} running windowed application(s):')
                    for a in gui_apps:
                        proj = f" [projekty: {', '.join(a['projects'])}]" if a.get('projects') else ""
                        print(f"  • PID {a['pid']:<7} | {a['name']:<25} | {a['executable']}{proj}")
            return 0
        if args.command == 'close-app':
            require_process_consent(args.entire_process)
            target_pid = int(args.target) if args.target and args.target.isdigit() else None
            target_name = args.target if args.target and not args.target.isdigit() else None
            res = close_gui_app(pid=target_pid, name=target_name, force=args.force, expected_start=args.start_ticks)
            print(json.dumps(res, ensure_ascii=False, indent=2))
            return 0
        if args.command == 'window-close':
            result = close_one_window(args.xid, args.pid, args.start_ticks, title=args.title,
                                      wait_seconds=args.wait_seconds, dry_run=args.dry_run)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result['status'] in ('closed', 'dry-run') else 1
        if args.command == 'windows':
            print(json.dumps(window_inventory(), ensure_ascii=False, indent=2)); return 0
        if args.command == 'bundle-import':
            print(json.dumps(import_bundle(args.source, args.destination), ensure_ascii=False, indent=2)); return 0
        if args.command == 'bundle-transfer':
            print(json.dumps(transfer_bundle(args.source, args.host, args.name, args.timeout), ensure_ascii=False, indent=2)); return 0

        user_config_env = Path.home()/'.config/uncrash/.env'
        cwd_env = Path.cwd()/'.env'
        if args.env_file:
            env_path = args.env_file
        elif os.environ.get('UNCRASH_ENV_FILE'):
            env_path = Path(os.environ['UNCRASH_ENV_FILE']).expanduser()
        elif user_config_env.exists():
            env_path = user_config_env
        elif cwd_env.exists() and cwd_env.resolve() != (Path.home()/'.env').resolve():
            env_path = cwd_env
        else:
            env_path = user_config_env
        if args.env_file and not env_path.exists(): raise RecoveryError('Requested environment file does not exist')
        settings = environment_settings(env_path, include_defaults=False)
        file_setting_keys = set(environment_settings(env_path, {}, include_defaults=False))
        activate_environment_file(env_path)
        args.state = args.state or Path(settings.pop('state_dir', Path.home()/'.local/state/uncrash'))
        args.config = args.config or Path(settings.pop('config_file', Path.home()/'.config/uncrash/config.json'))
        stored_config = json.loads(args.config.read_text()) if args.config.exists() else {'profiles': []}
        config = {**runtime_settings(), **stored_config, **settings}
        if args.encrypt is not None: config['encrypt'] = args.encrypt
        profiles(config)
        if args.command == 'profiles':
            if not args.select:
                if args.apply: raise RecoveryError('Applying profiles requires explicit --select IDs')
                result = {'available': discover(), 'changes_applied': False}
            else:
                proposed = selected_config(config, args.select)
                if args.apply:
                    # Persist profile state, never the derived effective settings map.
                    persisted = {k: v for k, v in stored_config.items() if k not in file_setting_keys}
                    persisted['profiles'] = proposed['profiles']
                    save_config(args.config, persisted)
                result = {'config': proposed, 'changes_applied': args.apply,
                    'next': 'Restart only uncrash.service after checking byte budgets'}
            print(json.dumps(result, ensure_ascii=False, indent=2)); return 0
        if args.command == 'diagnose':
            from .diagnostics import diagnose, save_report
            result = diagnose(state=args.state, interval=config.get('interval_seconds', 300))
            if args.output: save_report(result, args.output)
            print(json.dumps(result, ensure_ascii=False, indent=2)); return 0
        if args.command == 'install-user':
            interpreter = service_interpreter()
        store = Store(args.state, config.get('origin'), encrypt=config.get('encrypt', False))
        if args.command == 'serve':
            args.host = args.host if args.host is not None else config['api_host']
            args.port = args.port if args.port is not None else config['api_port']
            import uvicorn
            from .api import create_fastapi_app
            app = create_fastapi_app(store=store, config=config)
            print(f"Uncrash Web Client running on http://{args.host}:{args.port}/")
            uvicorn.run(app, host=args.host, port=args.port)
            return 0
        if args.command == 'mcp':
            args.host = args.host if args.host is not None else config['mcp_host']
            args.port = args.port if args.port is not None else config['mcp_port']
            args.transport = args.transport if args.transport is not None else config['mcp_transport']
            from .api import create_mcp_server
            server = create_mcp_server(store=store, config=config)
            if args.transport == 'stdio':
                import asyncio
                asyncio.run(server.run_stdio_async())
            elif args.transport == 'sse':
                import uvicorn
                uvicorn.run(server.sse_app(), host=args.host, port=args.port)
            elif args.transport == 'streamable-http':
                import uvicorn
                uvicorn.run(server.streamable_http_app(), host=args.host, port=args.port)
            return 0
        if args.command == 'build-native':
            result = {'binary': str(build_native(args.state)), 'engine': 'rust'}
        elif args.command == 'snapshot':
            result = store.capture(config)
        elif args.command == 'bundle-export':
            result = export_bundle(store, args.snapshot, args.destination)
        elif args.command == 'list':
            result = store.list()
        elif args.command == 'preview':
            from .preview import preview_snapshot
            result = preview_snapshot(store, args.snapshot, config,
                                      novnc=args.novnc,
                                      port=args.port,
                                      screenshot=args.screenshot,
                                      launch_tabs=args.launch_tabs,
                                      dry_run=args.dry_run)
            if not args.json:
                print(f"=== Uncrash Snapshot Preview: {result['snapshot']} ===")
                print(f"Captured: {result.get('created_at', 'unknown')}")
                print(f"Profiles: {', '.join(result.get('profiles', []))}")
                tabs = result.get('terminal_tabs', [])
                print(f"\nRecorded Terminal Tabs ({len(tabs)}):")
                if not tabs:
                    print("  (no terminal tabs recorded)")
                for idx, t in enumerate(tabs, 1):
                    tty_str = f" [tty: {t['terminal']}]" if t.get('terminal') else ""
                    print(f"  [{idx}] {t['title']:<32} | cwd: {t['cwd']}{tty_str}")
                    print(f"      Resume command: {t['resume_command']}")
                projs = result.get('gui_projects', [])
                if projs:
                    print(f"\nJetBrains / GUI Projects ({len(projs)}):")
                    for p in projs:
                        status = " [active]" if p.get('is_last') else ""
                        print(f"  • [{p['state']}] {p['path']}{status}")
                if result.get('novnc'):
                    print(f"\nnoVNC Preview Display: {result['novnc']['display']}")
                    print(f"noVNC Web URL:         {result['novnc']['novnc_url']}")
                if result.get('screenshot'):
                    print(f"Screenshot Saved:      {result['screenshot']}")
                if result.get('launch_script'):
                    print(f"\nLaunch in system terminal:\n  {result['launch_script']}")
                if result.get('tabs_launch_result'):
                    print(f"\nTerminal Launch Status: {result['tabs_launch_result'].get('status')}")
                return 0
        elif args.command == 'restore':
            result = store.restore(args.snapshot, config, args.destination, replace=args.replace)
            if args.display:
                result['launched'] = Launcher(store).launch(config, result, args.display)
        elif args.command == 'startup-restore':
            result = recover_at_startup(store, config, args.display)
        elif args.command == 'stop-owned':
            result = Launcher(store).stop()
        elif args.command == 'export':
            result = process_export(store, args.snapshot)
        elif args.command == 'action':
            snapshot, destination = parse_restore_action(args.uri)
            result = store.restore(snapshot, config, destination)
        elif args.command == 'install-user':
            private_dir(args.config.parent)
            if not args.config.exists():
                write_file(args.config, json.dumps({'profiles': []}).encode())
            private_dir(Path.home()/'.config/systemd/user')
            def quote(value):
                return '"'+str(value).replace('%', '%%').replace('\\', '\\\\').replace('"', '\\"')+'"'
            command = ' '.join(quote(x) for x in [interpreter, '-E', '-P', '-m', 'uncrash.cli', '--state', args.state.absolute(), '--config', args.config.absolute(), *(['--env-file', env_path.absolute()] if env_path.exists() else []), 'daemon'])
            unit = Path.home()/'.config/systemd/user/uncrash.service'
            # Keep the same import isolation used by the installed-runtime probe.
            unit.write_text('[Unit]\nDescription=Uncrash recovery snapshots with optional encryption\n\n[Service]\nType=simple\nUMask=0077\nExecStart='+command+'\nRestart=always\nRestartSec=5\n\n[Install]\nWantedBy=default.target\n')
            subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
            subprocess.run(['systemctl', '--user', 'enable', '--now', 'uncrash.service'], check=True)
            result = {'service': 'uncrash.service', 'interval_seconds': config['interval_seconds'], 'profiles': len(config['profiles'])}
        else:
            stop = threading.Event()
            for sig in [signal.SIGTERM, signal.SIGINT]:
                signal.signal(sig, lambda *_: stop.set())
            run_daemon(store, config, stop=stop); return 0
        print(json.dumps(result, ensure_ascii=False, indent=2)); return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print('uncrash: '+(str(exc) if isinstance(exc, RecoveryError) else type(exc).__name__), file=sys.stderr)
        return 1


def main(argv=None):
    token = activate_environment_file(None)
    try:
        return _main(argv)
    finally:
        reset_environment_file(token)


def main_pycharm(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    return main(['pycharm', *argv])


if __name__ == '__main__':
    raise SystemExit(main())
