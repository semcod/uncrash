"""Live IDE identities and portable, verified file-state recovery; never close an IDE."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tarfile
import threading
import uuid
import xml.etree.ElementTree as ET

from .store import RecoveryError, Store, no_links, private_dir, sync_dir, write_file


MAX_FILE = 512 * 1024 * 1024 + 28
MAX_BYTES = 16 * 1024**3
MAX_FILES = 20003
SCHEMA = 'uncrash.portable-file-state/v1'
PAYLOAD = re.compile(r'(?:[a-f0-9]{64}\.(?:blob|enc)|manifest\.(?:json|sha256|enc))')
SID = re.compile(r'\d{8}T\d{12}-[a-f0-9]{12}')


def _signature(s):
    return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns


def _file(path):
    fd = os.open(no_links(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    s = os.fstat(fd)
    if not stat.S_ISREG(s.st_mode):
        os.close(fd)
        raise RecoveryError('Recovery input must be a regular file')
    return os.fdopen(fd, 'rb')


def _digest(path):
    h = hashlib.sha256()
    with _file(path) as source:
        before = os.fstat(source.fileno())
        for block in iter(lambda: source.read(1024 * 1024), b''):
            h.update(block)
        if _signature(before) != _signature(os.fstat(source.fileno())):
            raise RecoveryError('Recovery input changed during reading')
    return h.hexdigest(), before.st_size


def _metadata(raw):
    if len(raw) > 4 * 1024**2:
        raise RecoveryError('Oversized bundle metadata')
    value = json.loads(raw)
    if not isinstance(value, dict): raise RecoveryError('Bundle metadata must be an object')
    if value.get('schema') != SCHEMA or not SID.fullmatch(str(value.get('snapshot', ''))):
        raise RecoveryError('Invalid recovery bundle identity')
    if not isinstance(value.get('origin'), str) or not 1 <= len(value['origin']) <= 255:
        raise RecoveryError('Invalid recovery origin')
    files = value.get('files')
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
        raise RecoveryError('Invalid bundle file count')
    names = set(); total = 0
    for row in files:
        if not isinstance(row, dict) or not PAYLOAD.fullmatch(str(row.get('name', ''))) or row['name'] in names:
            raise RecoveryError('Invalid or duplicate bundle file')
        if type(row.get('size')) is not int or not 0 <= row['size'] <= MAX_FILE:
            raise RecoveryError('Bundle file exceeds byte budget')
        if not re.fullmatch(r'[a-f0-9]{64}', str(row.get('sha256', ''))):
            raise RecoveryError('Invalid bundle content digest')
        names.add(row['name']); total += row['size']
    if total > MAX_BYTES + 28 * MAX_FILES:
        raise RecoveryError('Bundle exceeds byte budget')
    encrypted = value.get('encryption') == 'aes-256-gcm'
    manifests = {'manifest.enc'} if encrypted else {'manifest.json', 'manifest.sha256'}
    if value.get('encryption') not in ('none', 'aes-256-gcm') or names & {'manifest.enc', 'manifest.json', 'manifest.sha256'} != manifests:
        raise RecoveryError('Bundle manifest format mismatch')
    suffix = '.enc' if encrypted else '.blob'
    if any(n not in manifests and not n.endswith(suffix) for n in names):
        raise RecoveryError('Bundle blob format mismatch')
    identities = value.get('profiles')
    if not isinstance(identities, list) or len(identities) > 1000 or any(
            not isinstance(i, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', i) for i in identities) or len(set(identities)) != len(identities):
        raise RecoveryError('Invalid bundle application identities')
    if type(value.get('logical_bytes')) is not int or not 0 <= value['logical_bytes'] <= MAX_BYTES:
        raise RecoveryError('Invalid bundle logical byte budget')
    return value


class _HashedReader:
    def __init__(self, stream):
        self.stream = stream; self.hash = hashlib.sha256()

    def read(self, size):
        data = self.stream.read(size); self.hash.update(data); return data


def export_bundle(store, snapshot, destination):
    destination = no_links(destination)
    if destination.exists():
        raise RecoveryError('Select a new bundle destination; existing files are preserved')
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = destination.with_name('.bundle-' + uuid.uuid4().hex)
    try:
        with store.lock():
            sid, root, cipher, manifest = store.load(snapshot)
            names = {'manifest.enc'} if cipher else {'manifest.json', 'manifest.sha256'}
            for app in manifest['profiles']:
                for row in app['files']:
                    if not PAYLOAD.fullmatch(str(row['blob'])):
                        raise RecoveryError('Invalid snapshot blob path')
                    names.add(row['blob'])
            files = []
            for name in sorted(names):
                h, size = _digest(root / name)
                files.append({'name': name, 'size': size, 'sha256': h})
            metadata = {'schema': SCHEMA, 'snapshot': sid, 'origin': store.origin,
                'encryption': 'aes-256-gcm' if cipher else 'none', 'files': files,
                'profiles': [a['id'] for a in manifest['profiles']],
                'logical_bytes': sum(f['size'] for a in manifest['profiles'] for f in a['files']),
                'fidelity': 'durable-files; no live RAM, PTY, sockets or automatic app launch',
                'key_included': False}
            raw = json.dumps(metadata, sort_keys=True).encode(); _metadata(raw)
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as output:
                with tarfile.open(fileobj=output, mode='w', format=tarfile.USTAR_FORMAT) as archive:
                    info = tarfile.TarInfo('bundle.json'); info.mode = 0o600; info.size = len(raw)
                    archive.addfile(info, io.BytesIO(raw))
                    for row in files:
                        with _file(root / row['name']) as source:
                            before = os.fstat(source.fileno()); reader = _HashedReader(source)
                            if before.st_size != row['size']: raise RecoveryError('Snapshot changed during export')
                            info = tarfile.TarInfo('payload/' + row['name']); info.mode = 0o600; info.size = row['size']
                            archive.addfile(info, reader)
                            if reader.hash.hexdigest() != row['sha256'] or _signature(before) != _signature(os.fstat(source.fileno())):
                                raise RecoveryError('Snapshot changed during export')
                output.flush(); os.fsync(output.fileno())
        os.link(temporary, destination, follow_symlinks=False); temporary.unlink(); sync_dir(destination.parent)
        h, size = _digest(destination)
        return {'bundle': str(destination), 'sha256': h, 'bytes': size, 'snapshot': sid,
            'key_included': False, 'fidelity': metadata['fidelity']}
    finally:
        if temporary.exists(): temporary.unlink()


def import_bundle(source, destination):
    destination = no_links(destination)
    if destination.exists() or destination in (Path('/'), Path.home()):
        raise RecoveryError('Import requires a new separate state directory')
    created = False
    with _file(source) as stream:
        before = os.fstat(stream.fileno())
        if before.st_size > MAX_BYTES + 64 * 1024**2:
            raise RecoveryError('Archive exceeds byte budget')
        try:
            with tarfile.open(fileobj=stream, mode='r:') as archive:
                first = archive.next()
                if first is None or first.name != 'bundle.json' or not first.isfile() or first.size > 4 * 1024**2:
                    raise RecoveryError('Bundle metadata must be the first regular archive member')
                metadata = _metadata(archive.extractfile(first).read())
                destination.mkdir(parents=True, mode=0o700, exist_ok=False); created = True
                store = Store(destination, metadata['origin']); sid = metadata['snapshot']
                stage = private_dir(store.snapshots / ('.pending-' + sid))
                expected = {x['name']: x for x in metadata['files']}; seen = set()
                while True:
                    member = archive.next()
                    if member is None: break
                    if not member.isfile() or not member.name.startswith('payload/'):
                        raise RecoveryError('Only declared regular bundle files may be imported')
                    name = member.name[len('payload/'):]
                    if name not in expected or name in seen or member.size != expected[name]['size']:
                        raise RecoveryError('Unknown, duplicate or oversized archive member')
                    reader = archive.extractfile(member); h = hashlib.sha256()
                    fd = os.open(stage / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                    with os.fdopen(fd, 'wb') as output:
                        for block in iter(lambda: reader.read(1024 * 1024), b''):
                            h.update(block); output.write(block)
                        output.flush(); os.fsync(output.fileno())
                    if h.hexdigest() != expected[name]['sha256']:
                        raise RecoveryError('Bundle content digest mismatch')
                    seen.add(name)
                if seen != set(expected) or _signature(before) != _signature(os.fstat(stream.fileno())):
                    raise RecoveryError('Bundle is incomplete or changed during import')
                sync_dir(stage); os.rename(stage, store.snapshots / sid); sync_dir(store.snapshots)
                if metadata['encryption'] == 'none':
                    _, _, _, saved = store.load(sid)
                    if [a['id'] for a in saved['profiles']] != metadata['profiles']:
                        raise RecoveryError('Bundle application metadata mismatch')
                config = {'origin': metadata['origin'], 'encrypt': False, 'snapshot_engine': 'rust',
                    'max_file_bytes': 512 * 1024**2, 'max_bytes': MAX_BYTES,
                    'profiles': [{'id': i, 'state_dir': str(destination / 'applications' / i), 'argv': []} for i in metadata['profiles']]}
                write_file(destination / 'recovery-config.json', json.dumps(config, indent=2).encode()); sync_dir(destination)
            return {'snapshot': sid, 'state': str(destination), 'config': str(destination / 'recovery-config.json'),
                'transport_hashes_verified': len(seen), 'requires_separate_key': metadata['encryption'] != 'none',
                'apps_launched': False, 'fidelity': 'durable-files; restore into a separate destination before launch'}
        except BaseException:
            if created: shutil.rmtree(destination)
            raise


# The SSH peer needs only Python's standard library. It receives an opaque archive,
# hashes it, and publishes one new private file inside a dedicated inbox.
SSH_RECEIVER = '''import hashlib,json,os,re,sys,uuid
from pathlib import Path
header=sys.stdin.buffer.readline(4097)
if len(header)>4096 or not header.endswith(b'\\n'):raise ValueError('invalid header')
m=json.loads(header);name=m['name'];size=m['size'];expected=m['sha256']
if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,95}\\.tar',name):raise ValueError('invalid archive name')
if type(size) is not int or not 0<=size<=16*1024**3+64*1024**2:raise ValueError('oversized archive')
if not re.fullmatch(r'[a-f0-9]{64}',expected):raise ValueError('invalid digest')
root=Path.home()/'.local/state/uncrash-inbox'
for p in (root,*root.parents):
 if p.is_symlink():raise ValueError('symlinked inbox')
root.mkdir(parents=True,exist_ok=True,mode=0o700)
if root.stat().st_uid!=os.getuid():raise ValueError('inbox owner')
os.chmod(root,0o700);target=root/name
if target.exists():raise ValueError('destination already exists')
temporary=root/('.incoming-'+uuid.uuid4().hex);h=hashlib.sha256();remaining=size
try:
 fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'wb') as out:
  while remaining:
   block=sys.stdin.buffer.read(min(1024*1024,remaining))
   if not block:raise ValueError('incomplete transfer')
   h.update(block);out.write(block);remaining-=len(block)
  if sys.stdin.buffer.read(1):raise ValueError('trailing transfer data')
  out.flush();os.fsync(out.fileno())
 if h.hexdigest()!=expected:raise ValueError('digest mismatch')
 os.link(temporary,target,follow_symlinks=False);temporary.unlink()
 fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY);os.fsync(fd);os.close(fd)
 print(json.dumps({'archive':str(target),'sha256':expected,'bytes':size,'apps_launched':False}))
finally:
 if temporary.exists():temporary.unlink()
'''


def transfer_bundle(source, host, name=None, timeout=600):
    import shlex
    if not re.fullmatch(r'[a-zA-Z0-9_.-]+@[a-zA-Z0-9][a-zA-Z0-9_.-]*', host):
        raise RecoveryError('Specify an explicit user@host; SSH options are not accepted as a host')
    name = name or ('uncrash-' + uuid.uuid4().hex + '.tar')
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,95}\.tar', name):
        raise RecoveryError('Invalid remote bundle name')
    if not 1 <= timeout <= 3600: raise RecoveryError('Transfer timeout must be 1..3600 seconds')
    h, size = _digest(source)
    if size > MAX_BYTES + 64 * 1024**2: raise RecoveryError('Archive exceeds byte budget')
    argv = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
        '-o', 'ConnectTimeout=5', '-o', 'ClearAllForwardings=yes', '-o', 'ForwardAgent=no',
        '-o', 'PermitLocalCommand=no', '-o', 'ControlMaster=no', '-o', 'ControlPath=none',
        host, 'python3 -c ' + shlex.quote(SSH_RECEIVER)]
    with _file(source) as stream:
        before = os.fstat(stream.fileno())
        with subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
            timer = threading.Timer(timeout, process.kill); timer.start()
            try:
                process.stdin.write(json.dumps({'name': name, 'size': size, 'sha256': h}).encode() + b'\n')
                for block in iter(lambda: stream.read(1024 * 1024), b''): process.stdin.write(block)
                process.stdin.close()
                response = process.stdout.read(65537); code = process.wait()
                if code or len(response) > 65536 or _signature(before) != _signature(os.fstat(stream.fileno())):
                    raise RecoveryError('SSH transfer failed; original bundle preserved')
                receipt = json.loads(response)
                if receipt.get('sha256') != h or receipt.get('bytes') != size:
                    raise RecoveryError('SSH receiver digest response mismatch')
                return {'host': host, **receipt, 'fidelity': 'verified archive transfer; no app or RAM restoration'}
            finally:
                timer.cancel()


def jetbrains_projects(home=None, selector_filter=None):
    home = no_links(home or Path.home())
    all_projects = []
    last_opened_map = {}
    config_root = home / '.config/JetBrains'
    if config_root.is_dir():
        for selector in sorted(config_root.glob('*/options/recentProjects.xml')):
            dir_name = selector.parent.parent.name
            if selector_filter and selector_filter.lower() not in dir_name.lower():
                continue
            try:
                with _file(selector) as stream: raw = stream.read(2 * 1024**2 + 1)
                if len(raw) > 2 * 1024**2 or b'<!DOCTYPE' in raw or b'<!ENTITY' in raw: continue
                root = ET.fromstring(raw)
                last_opt = root.find(".//option[@name='lastOpenedProject']")
                if last_opt is not None and last_opt.get('value'):
                    last_opened_map[dir_name] = last_opt.get('value').replace('$USER_HOME$', str(home))
                for entry in root.findall('.//entry'):
                    key = entry.get('key', '')
                    if not key: continue
                    path = key.replace('$USER_HOME$', str(home))
                    meta = entry.find('.//RecentProjectMetaInfo')
                    is_opened = meta.get('opened') == 'true' if meta is not None else False
                    act_opt = entry.find(".//option[@name='activationTimestamp']")
                    open_opt = entry.find(".//option[@name='projectOpenTimestamp']")
                    act_ts = int(act_opt.get('value', 0)) if act_opt is not None and act_opt.get('value', '').isdigit() else 0
                    open_ts = int(open_opt.get('value', 0)) if open_opt is not None and open_opt.get('value', '').isdigit() else 0
                    frame_title = meta.get('frameTitle') if meta is not None else None
                    all_projects.append({
                        'path': path, 'selector': dir_name, 'opened': is_opened,
                        'activation_timestamp': act_ts, 'project_open_timestamp': open_ts,
                        'frame_title': frame_title,
                    })
            except (OSError, ET.ParseError, RecoveryError): continue

    by_path = {}
    for proj in all_projects:
        p = proj['path']
        if p not in by_path or proj['activation_timestamp'] > by_path[p]['activation_timestamp']:
            by_path[p] = proj

    sorted_projects = sorted(by_path.values(), key=lambda x: max(x['activation_timestamp'], x['project_open_timestamp']), reverse=True)
    open_projects = [p for p in sorted_projects if p['opened']]
    closed_projects = [p for p in sorted_projects if not p['opened']]
    last_opened = next(iter(last_opened_map.values()), None) or (sorted_projects[0]['path'] if sorted_projects else None)
    last_closed = closed_projects[0]['path'] if closed_projects else None

    return {
        'projects': sorted_projects,
        'open_projects': [p['path'] for p in open_projects],
        'closed_projects': [p['path'] for p in closed_projects],
        'last_opened': last_opened,
        'last_closed': last_closed,
        'open_count': len(open_projects),
        'closed_count': len(closed_projects),
    }


def find_pycharm_executable(home=None, proc_root=Path('/proc')):
    home = no_links(home or Path.home())
    if proc_root.exists():
        for p in proc_root.iterdir():
            if not p.name.isdigit(): continue
            try:
                exe = os.readlink(p / 'exe')
                if 'pycharm' in exe.lower():
                    return exe
            except (OSError, ValueError): continue
    which_exe = shutil.which('pycharm')
    if which_exe:
        return which_exe
    for c in [
        Path('/snap/pycharm-professional/current/bin/pycharm'),
        Path('/snap/pycharm-community/current/bin/pycharm'),
        Path('/var/lib/snapd/snap/bin/pycharm-professional'),
        Path('/var/lib/snapd/snap/bin/pycharm-community'),
    ]:
        if c.is_file(): return str(c)
    toolbox = home / '.local/share/JetBrains/Toolbox/apps'
    if toolbox.is_dir():
        for p in sorted(toolbox.glob('*/bin/pycharm')):
            if p.is_file(): return str(p)
    return None


def restore_pycharm(project=None, executable=None, home=None, dry_run=False):
    home = no_links(home or Path.home())
    state = jetbrains_projects(home=home, selector_filter='pycharm')
    target_project = project or state['last_closed'] or state['last_opened']
    if not target_project:
        raise RecoveryError('No recent PyCharm projects found in ~/.config/JetBrains')
    resolved_exe = executable or find_pycharm_executable(home=home)
    if not resolved_exe:
        raise RecoveryError('PyCharm executable not found (checked running processes, PATH, Snap, and Toolbox)')
    result = {
        'status': 'planned' if dry_run else 'launched',
        'project': target_project,
        'executable': resolved_exe,
        'dry_run': dry_run,
    }
    if not dry_run:
        proc = subprocess.Popen(
            [resolved_exe, str(target_project)],
            cwd=str(home),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        result['pid'] = proc.pid
    return result


def jetbrains_state(home=None, proc_root=Path('/proc')):

    home = no_links(home or Path.home()); processes = []; all_processes = {}
    for p in proc_root.iterdir():
        if not p.name.isdigit(): continue
        try:
            if p.stat().st_uid != os.getuid(): continue
            s = (p / 'stat').read_text().rsplit(')', 1)[1].split()
            all_processes[int(p.name)] = {'pid': int(p.name), 'ppid': int(s[1]), 'start_ticks': s[19], 'name': (p/'comm').read_text().strip()}
            executable = os.readlink(p / 'exe')
            argv = (p / 'cmdline').read_bytes().split(b'\0')
            if not any(x in executable.lower() for x in ('pycharm', 'idea', 'webstorm', 'goland', 'clion', 'rider')) and not any(
                    a.startswith(b'-Didea.paths.selector=') or a == b'com.intellij.idea.Main' for a in argv): continue
            maps = (p / 'maps').read_text()
            processes.append({'pid': int(p.name), 'ppid': int(s[1]), 'start_ticks': s[19],
                'state': s[0], 'jvm': 'libjvm.so' in maps, 'executable': executable})
        except (OSError, IndexError): continue
    by_pid = {p['pid']: p for p in processes}
    for row in processes:
        ancestor = row['ppid']; seen = set(); nested = False
        while ancestor in all_processes and ancestor not in seen:
            seen.add(ancestor)
            if ancestor in by_pid and by_pid[ancestor]['jvm']: nested = True; break
            ancestor = all_processes[ancestor]['ppid']
        # Forked launch helpers may retain libjvm mappings without being IDE instances.
        row['root_ide_candidate'] = row['jvm'] and not nested
    owned = {p['pid'] for p in processes if p['root_ide_candidate']}
    while True:
        expanded = owned | {pid for pid,p in all_processes.items() if p['ppid'] in owned}
        if expanded == owned: break
        owned = expanded
    descendants = []
    for pid in sorted(owned):
        row = dict(all_processes[pid])
        try:
            row['cwd'] = os.readlink(proc_root / str(pid) / 'cwd')
            terminal = os.readlink(proc_root / str(pid) / 'fd/0')
            row['terminal'] = terminal if terminal.startswith('/dev/pts/') else None
        except OSError: pass
        descendants.append(row)
    pj_info = jetbrains_projects(home=home)
    projects = []
    for selector in sorted((home / '.config/JetBrains').glob('*/options/recentProjects.xml')):
        try:
            with _file(selector) as stream: raw = stream.read(2 * 1024**2 + 1)
            if len(raw) > 2 * 1024**2 or b'<!DOCTYPE' in raw or b'<!ENTITY' in raw: continue
            for entry in ET.fromstring(raw).iter('entry'):
                meta = next(entry.iter('RecentProjectMetaInfo'), None)
                if meta is not None and meta.get('opened') == 'true':
                    projects.append({'selector': selector.parent.parent.name,
                        'path': entry.get('key', '').replace('$USER_HOME$', str(home)),
                        'source': 'persisted recentProjects; may lag live windows'})
        except (OSError, ET.ParseError, RecoveryError): continue
    return {'schema': 'uncrash.jetbrains-live-state/v1', 'processes': processes,
        'projects': projects, 'descendants': descendants, 'root_ide_candidates': sum(p['root_ide_candidate'] for p in processes),
        'libjvm_mapped_processes': sum(p['jvm'] for p in processes),
        'last_opened_project': pj_info['last_opened'],
        'last_closed_project': pj_info['last_closed'],
        'open_projects': pj_info['open_projects'],
        'closed_projects': pj_info['closed_projects'],
        'window_count_verified': False, 'signals_sent': False,
        'fidelity': 'process identities and persisted project paths; no live editor buffer or PTY output read'}



def request_window_close(xid, expected_pid, expected_start):
    if os.environ.get('XDG_SESSION_TYPE', '').lower() == 'wayland':
        raise RecoveryError('Wayland target identity cannot be verified; no focus keystroke or process signal sent')
    if not isinstance(xid, int) or xid <= 0 or expected_pid <= 0 or not str(expected_start).isdigit():
        raise RecoveryError('Provide an explicit window ID, PID and process start identity')
    try:
        from Xlib import X, Xatom, display, protocol
    except ImportError as exc:
        raise RecoveryError('X11 window control requires python-xlib; no window closed') from exc
    connection = display.Display()
    try:
        window = connection.create_resource_object('window', xid)
        if not any('pycharm' in x.lower() for x in (window.get_wm_class() or ())):
            raise RecoveryError('The explicit target is not a PyCharm window')
        pids = window.get_full_property(connection.intern_atom('_NET_WM_PID'), Xatom.CARDINAL)
        if pids is None or int(pids.value[0]) != expected_pid:
            raise RecoveryError('Window process identity changed; no close requested')
        current = Path('/proc/' + str(expected_pid) + '/stat').read_text().rsplit(')', 1)[1].split()[19]
        if current != str(expected_start): raise RecoveryError('PID was reused; no close requested')
        delete = connection.intern_atom('WM_DELETE_WINDOW')
        supported = window.get_full_property(connection.intern_atom('WM_PROTOCOLS'), Xatom.ATOM)
        if supported is None or delete not in supported.value:
            raise RecoveryError('Window has no graceful-close protocol')
        window.send_event(protocol.event.ClientMessage(window=window,
            client_type=connection.intern_atom('WM_PROTOCOLS'), data=(32, [delete, X.CurrentTime, 0, 0, 0])),
            event_mask=X.NoEventMask, propagate=False)
        connection.flush()
        return {'window': xid, 'pid': expected_pid, 'close_requested': True, 'process_signals_sent': False}
    finally:
        connection.close()


def detected_gui_apps(home=None, proc_root=Path('/proc')):
    from .inventory import desktop_inventory
    home = no_links(home or Path.home())

    launchers = desktop_inventory()
    desktop_by_exe = {}
    desktop_by_comm = {}
    for d in launchers:
        if d.get('executable') and not d.get('hidden') and not d.get('id', '').startswith('cli-'):
            exe = d['executable']
            desktop_by_exe[exe] = d
            desktop_by_comm[os.path.basename(exe).lower()] = d
            if '/snap/' in exe:
                desktop_by_comm[exe.split('/')[-1].lower()] = d

    # Jetbrains open projects
    jb_projects = []
    for p in (home / '.config/JetBrains').glob('*/options/recentProjects.xml'):
        try:
            tree = ET.parse(p)
            for entry in tree.iter('entry'):
                meta = next(entry.iter('RecentProjectMetaInfo'), None)
                if meta is not None and meta.get('opened') == 'true':
                    jb_projects.append({
                        'ide': p.parent.parent.name,
                        'path': entry.get('key', '').replace('$USER_HOME$', str(home))
                    })
        except Exception:
            pass

    # Read systemd scopes for desktop apps
    scope_pids = set()
    try:
        scopes_raw = subprocess.check_output(['systemctl', '--user', 'list-units', '--type=scope', '-l', '--no-legend', '--no-pager'], stderr=subprocess.DEVNULL).decode()
        for line in scopes_raw.splitlines():
            parts = line.strip().split()
            if parts and (parts[0].startswith('app-') or parts[0].startswith('vte-spawn-')):
                m = re.search(r'-(\d+)\.scope$', parts[0])
                if m:
                    scope_pids.add(int(m.group(1)))
    except Exception:
        pass

    candidates = []
    for pid_dir in sorted(proc_root.iterdir(), key=lambda p: int(p.name) if p.name.isdigit() else 99999999):
        if not pid_dir.name.isdigit():
            continue
        pid = int(pid_dir.name)
        try:
            if pid_dir.stat().st_uid != os.getuid():
                continue
            try:
                exe = os.readlink(pid_dir / 'exe')
            except OSError:
                continue

            comm = (pid_dir / 'comm').read_text().strip()
            cmdline = (pid_dir / 'cmdline').read_bytes().split(b'\0')
            cmdline_str = [c.decode('utf-8', 'replace') for c in cmdline if c]

            if any(arg.startswith(('--type=', 'stdioMcpServer', '--gapplication-service')) for arg in cmdline_str):
                continue

            stat = (pid_dir / 'stat').read_text().rsplit(')', 1)[1].split()
            ppid = int(stat[1])
            start_ticks = stat[19]

            matched = desktop_by_exe.get(exe) or desktop_by_comm.get(comm.lower())
            is_jb = any(x in exe.lower() for x in ('pycharm', 'idea', 'webstorm', 'goland', 'clion'))
            is_scope = pid in scope_pids

            ignore_comm = {
                'gnome-keyring-d', 'cat', 'ssh', 'snap', 'dbus-monitor', 'gsd-disk-utilit',
                'evolution-alarm', 'pipewire', 'wireplumber', 'systemd', 'bash', 'sh'
            }
            if comm in ignore_comm or exe.endswith('/gnome-shell'):
                continue

            if matched or is_jb or is_scope:
                app_name = matched['name'] if matched else ('PyCharm Professional' if is_jb else comm)
                projects = [p['path'] for p in jb_projects] if is_jb else []

                candidates.append({
                    'pid': pid,
                    'ppid': ppid,
                    'name': app_name,
                    'executable': exe,
                    'comm': comm,
                    'start_ticks': start_ticks,
                    'projects': projects,
                    'details': ', '.join(projects) if projects else (' '.join(cmdline_str[:2]))
                })
        except (OSError, IndexError):
            continue

    cand_pids = {c['pid'] for c in candidates}
    top_level = [c for c in candidates if c['ppid'] not in cand_pids]
    return top_level


def close_gui_app(pid=None, name=None, force=False, expected_start=None):
    """Terminate one explicitly identified application process, never select a window."""
    import select
    import signal
    from .runtime import pidfd, start_ticks

    if type(pid) is not int or pid <= 1 or not str(expected_start or '').isdecimal():
        raise RecoveryError('Process close requires an explicit PID and --start-ticks from apps --json; use window-close for one window')
    target = next((a for a in detected_gui_apps() if a['pid'] == pid), None)
    if target is None or str(target['start_ticks']) != str(expected_start):
        raise RecoveryError('Application identity changed or is not a detected GUI process')
    if name and name.lower() not in (target['name'] + ' ' + target['comm']).lower():
        raise RecoveryError('Application name does not match the selected process')
    if not hasattr(signal, 'pidfd_send_signal'):
        raise RecoveryError('This platform cannot safely signal a pinned process identity')
    descriptor = pidfd(pid)
    try:
        if Path(f'/proc/{pid}').stat().st_uid != os.getuid() or start_ticks(pid) != str(expected_start):
            raise RecoveryError('Application identity changed before signalling')
        poller = select.poll(); poller.register(descriptor, select.POLLIN)
        signal.pidfd_send_signal(descriptor, signal.SIGTERM)
        sent = ['SIGTERM']; stopped = bool(poller.poll(1500))
        if not stopped and force:
            signal.pidfd_send_signal(descriptor, signal.SIGKILL)
            sent.append('SIGKILL'); stopped = bool(poller.poll(1000))
        return {'status': 'closed' if stopped else 'still-running', 'pid': pid,
                'name': target['name'], 'start_ticks': str(expected_start),
                'method': sent[-1], 'signals_sent': sent, 'stopped': stopped,
                'scope': 'entire-application-process; may contain multiple windows'}
    finally:
        os.close(descriptor)

