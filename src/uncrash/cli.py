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
from .recovery import (export_bundle, import_bundle, transfer_bundle, jetbrains_state, request_window_close,
                       detected_gui_apps, close_gui_app, find_pycharm_executable, jetbrains_projects, restore_pycharm)



ENV_SETTINGS = {
    'UNCRASH_JETBRAINS_METADATA': ('jetbrains_metadata', 'bool'),
    'UNCRASH_ENCRYPT': ('encrypt', 'bool'), 'UNCRASH_COMPRESS': ('compress', 'bool'),
    'UNCRASH_SNAPSHOT_ENGINE': ('snapshot_engine', 'engine'), 'UNCRASH_RUST_THREADS': ('rust_threads', 'int'),
    'UNCRASH_RUST_BINARY': ('rust_binary', 'path'), 'UNCRASH_INTERVAL_SECONDS': ('interval_seconds', 'int'),
    'UNCRASH_RETENTION': ('retention', 'int'), 'UNCRASH_MAX_FILE_BYTES': ('max_file_bytes', 'int'),
    'UNCRASH_MAX_BYTES': ('max_bytes', 'int'), 'UNCRASH_MAX_TOTAL_BYTES': ('max_total_bytes', 'int'),
    'UNCRASH_STARTUP_RESTORE': ('startup_restore', 'bool'),
    'UNCRASH_STATE_DIR': ('state_dir', 'path'), 'UNCRASH_CONFIG_FILE': ('config_file', 'path'),
}


def environment_settings(path, environ=None, *, include_defaults=True):
    environ = os.environ if environ is None else environ
    values = {}
    if path is not None and Path(path).exists():
        path = no_links(path)
        if not path.is_file() or path.stat().st_uid != os.getuid():
            raise RecoveryError('Environment file must be an owned regular file')
        if path.stat().st_size > 65536: raise RecoveryError('Environment file is oversized')
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith('#'): continue
            if line.startswith('export '): line = line[7:]
            name, separator, value = line.partition('=')
            name = name.strip(); value = value.strip()
            if not separator or name not in ENV_SETTINGS or name in values:
                raise RecoveryError('Environment file has an unknown, duplicate or malformed setting')
            if value.startswith(('"', "'")):
                if len(value) < 2 or value[-1] != value[0]: raise RecoveryError('Invalid quoted environment value')
                value = value[1:-1]
            if '\x00' in value or '$' in value or '`' in value:
                raise RecoveryError('Environment values must be literals without shell expansion')
            values[name] = value
    values.update({k: environ[k] for k in ENV_SETTINGS if k in environ})
    settings = {'encrypt': False, 'snapshot_engine': 'rust', 'compress': False} if include_defaults else {}
    for name, value in values.items():
        key, kind = ENV_SETTINGS[name]
        if kind == 'bool':
            if value.lower() not in ['true', 'false', '1', '0']: raise RecoveryError('Invalid environment boolean')
            settings[key] = value.lower() in ['true', '1']
        elif kind == 'int':
            if not value.isascii() or not value.isdecimal() or int(value) <= 0:
                raise RecoveryError('Environment limits must be positive integers')
            settings[key] = int(value)
        elif kind == 'engine':
            if value not in ['rust', 'python']: raise RecoveryError('Select rust or python snapshot engine')
            settings[key] = value
        else:
            candidate = Path(value).expanduser()
            if not candidate.is_absolute(): raise RecoveryError('Environment paths must be absolute or start with ~/')
            settings[key] = str(no_links(candidate))
    if not 1 <= settings.get('rust_threads', 4) <= 16: raise RecoveryError('Rust threads must be between 1 and 16')
    if not 5 <= settings.get('interval_seconds', 300) <= 86400: raise RecoveryError('Snapshot interval must be 5..86400 seconds')
    return settings


def main(argv=None):
    parser = argparse.ArgumentParser(description='Fast local snapshots with optional encryption and explicit application recovery')
    parser.add_argument('--state', type=Path)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--encrypt', action=argparse.BooleanOptionalAction, default=None)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('inventory')
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
    startup = sub.add_parser('startup-restore')
    startup.add_argument('--display')
    sub.add_parser('install-user')
    sub.add_parser('build-native')
    sub.add_parser('jetbrains', help='Inspect JVM identities and persisted projects without closing windows')
    apps_parser = sub.add_parser('apps', help='List detected windowed/GUI applications or close a targeted app')
    apps_parser.add_argument('--close', nargs='?', const='__default__', help='Close an explicit whole-process PID; requires --start-ticks')
    apps_parser.add_argument('--start-ticks')
    apps_parser.add_argument('--force', action='store_true', help='Force kill if process does not exit promptly')
    apps_parser.add_argument('--json', action='store_true', help='Output in JSON format')
    close_app_parser = sub.add_parser('close-app', help='Close one explicit application process with PID/start identity')
    close_app_parser.add_argument('target', nargs='?', default=None, help='Explicit PID from apps --json; this closes the whole process')
    close_app_parser.add_argument('--start-ticks')
    close_app_parser.add_argument('--force', action='store_true', help='Force kill if process does not exit promptly')
    pycharm_parser = sub.add_parser('pycharm', help='Inspect, close, or restore JetBrains PyCharm projects')
    pycharm_parser.add_argument('action', nargs='?', choices=['status', 'close', 'restore'], default=None, help='Action to perform: status, close, or restore')
    pycharm_parser.add_argument('--restore', '--restore-last', action='store_true', dest='restore', help='Reopen/restore the last closed PyCharm project')
    pycharm_parser.add_argument('--close', action='store_true', help='Request graceful close of running PyCharm process')
    pycharm_parser.add_argument('--force', action='store_true', help='Force kill if process does not exit promptly')
    pycharm_parser.add_argument('--project', help='Specific project directory path')
    pycharm_parser.add_argument('--executable', help='Specific PyCharm executable binary path')
    pycharm_parser.add_argument('--dry-run', action='store_true', help='Report planned action without launching or terminating')
    pycharm_parser.add_argument('--start-ticks')
    pycharm_parser.add_argument('--pid', type=int, help='Target process PID for close operation')
    window = sub.add_parser('window-close', help='Request one explicit X11 window close with PID/start fencing')
    window.add_argument('--xid', type=lambda v: int(v, 0), required=True)
    window.add_argument('--pid', type=int, required=True)
    window.add_argument('--start-ticks', required=True)
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
    bundle.add_argument('--timeout', type=int, default=600)
    serve_parser = sub.add_parser('serve', help='Run REST API server conforming to wellmanifest/nl-api-llm')
    serve_parser.add_argument('--host', default='127.0.0.1', help='Host interface to bind')
    serve_parser.add_argument('--port', type=int, default=8795, help='Port to listen on')
    mcp_parser = sub.add_parser('mcp', help='Run MCP server conforming to wellmanifest/skills')
    mcp_parser.add_argument('--transport', choices=['stdio', 'sse', 'streamable-http'], default='stdio', help='MCP transport')
    mcp_parser.add_argument('--host', default='127.0.0.1', help='Host for network transport')
    mcp_parser.add_argument('--port', type=int, default=18795, help='Port for network transport')
    export = sub.add_parser('export')
    export.add_argument('snapshot', nargs='?', default='latest')
    action = sub.add_parser('action')
    action.add_argument('uri')
    args = parser.parse_args(argv)

    try:
        if args.command == 'inventory':
            print(json.dumps(desktop_inventory(), ensure_ascii=False, indent=2)); return 0
        if args.command == 'jetbrains':
            print(json.dumps(jetbrains_state(), ensure_ascii=False, indent=2)); return 0
        if args.command == 'pycharm':
            is_restore = args.restore or (getattr(args, 'action', None) == 'restore')
            is_close = args.close or (getattr(args, 'action', None) == 'close')
            if is_restore:
                print(json.dumps(restore_pycharm(project=args.project, executable=args.executable, dry_run=args.dry_run), ensure_ascii=False, indent=2))
                return 0
            if is_close:
                if args.dry_run:
                    print(json.dumps({'action': 'close-process', 'pid': args.pid, 'start_ticks': args.start_ticks, 'signals_sent': False})); return 0
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
            target_pid = int(args.target) if args.target and args.target.isdigit() else None
            target_name = args.target if args.target and not args.target.isdigit() else None
            res = close_gui_app(pid=target_pid, name=target_name, force=args.force, expected_start=args.start_ticks)
            print(json.dumps(res, ensure_ascii=False, indent=2))
            return 0
        if args.command == 'window-close':
            print(json.dumps(request_window_close(args.xid, args.pid, args.start_ticks))); return 0
        if args.command == 'bundle-import':
            print(json.dumps(import_bundle(args.source, args.destination), ensure_ascii=False, indent=2)); return 0
        if args.command == 'bundle-transfer':
            print(json.dumps(transfer_bundle(args.source, args.host, args.name, args.timeout), ensure_ascii=False, indent=2)); return 0
        if args.command == 'serve':
            import uvicorn
            from .api import create_fastapi_app
            app = create_fastapi_app()
            uvicorn.run(app, host=args.host, port=args.port)
            return 0
        if args.command == 'mcp':
            from .api import create_mcp_server
            server = create_mcp_server()
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
        args.state = args.state or Path(settings.pop('state_dir', Path.home()/'.local/state/uncrash'))
        args.config = args.config or Path(settings.pop('config_file', Path.home()/'.config/uncrash/config.json'))
        config = json.loads(args.config.read_text()) if args.config.exists() else {'profiles': []}
        config = {'encrypt': False, 'snapshot_engine': 'rust', 'compress': False, **config, **settings}
        if args.encrypt is not None: config['encrypt'] = args.encrypt
        profiles(config)
        if args.command == 'profiles':
            if not args.select:
                if args.apply: raise RecoveryError('Applying profiles requires explicit --select IDs')
                result = {'available': discover(), 'changes_applied': False}
            else:
                proposed = selected_config(config, args.select)
                if args.apply: save_config(args.config, proposed)
                result = {'config': proposed, 'changes_applied': args.apply,
                    'next': 'Restart only uncrash.service after checking byte budgets'}
            print(json.dumps(result, ensure_ascii=False, indent=2)); return 0
        if args.command == 'diagnose':
            from .diagnostics import diagnose, save_report
            result = diagnose(state=args.state, interval=config.get('interval_seconds', 300))
            if args.output: save_report(result, args.output)
            print(json.dumps(result, ensure_ascii=False, indent=2)); return 0
        store = Store(args.state, config.get('origin'), encrypt=config.get('encrypt', False))
        if args.command == 'build-native':
            result = {'binary': str(build_native(args.state)), 'engine': 'rust'}
        elif args.command == 'snapshot':
            result = store.capture(config)
        elif args.command == 'bundle-export':
            result = export_bundle(store, args.snapshot, args.destination)
        elif args.command == 'list':
            result = store.list()
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
                write_file(args.config, json.dumps({'profiles': [], 'retention': 288, 'startup_restore': False}).encode())
            private_dir(Path.home()/'.config/systemd/user')
            def quote(value):
                return '"'+str(value).replace('%', '%%').replace('\\', '\\\\').replace('"', '\\"')+'"'
            command = ' '.join(quote(x) for x in [sys.executable, '-m', 'uncrash.cli', '--state', args.state.absolute(), '--config', args.config.absolute(), *(['--env-file', env_path.absolute()] if env_path.exists() else []), 'daemon'])
            unit = Path.home()/'.config/systemd/user/uncrash.service'
            # Use the installed package interpreter, not a source-only PYTHONPATH.
            unit.write_text('[Unit]\nDescription=Uncrash recovery snapshots with optional encryption\n\n[Service]\nType=simple\nUMask=0077\nExecStart='+command+'\nRestart=always\nRestartSec=5\n\n[Install]\nWantedBy=default.target\n')
            subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
            subprocess.run(['systemctl', '--user', 'enable', '--now', 'uncrash.service'], check=True)
            result = {'service': 'uncrash.service', 'interval_seconds': config.get('interval_seconds', 300), 'profiles': len(config['profiles'])}
        else:
            stop = threading.Event()
            for sig in [signal.SIGTERM, signal.SIGINT]:
                signal.signal(sig, lambda *_: stop.set())
            run_daemon(store, config, stop=stop); return 0
        print(json.dumps(result, ensure_ascii=False, indent=2)); return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print('uncrash: '+(str(exc) if isinstance(exc, RecoveryError) else type(exc).__name__), file=sys.stderr)
        return 1


def main_pycharm(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    return main(['pycharm', *argv])


if __name__ == '__main__':
    raise SystemExit(main())
