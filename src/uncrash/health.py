"""Bounded, read-only freeze risk inspection. Findings are evidence, not a liveness test."""
from __future__ import annotations

from datetime import datetime
import itertools
import math
import os
from pathlib import Path
import re
import stat
import time
import xml.etree.ElementTree as ET

from .store import RecoveryError, no_links


LOG_BYTES = 1024 * 1024
DUMP_BYTES = 16 * 1024 * 1024
GENERATED_ROOTS = ('.subactor/cache', '.subactor/sessions', '.subactor/snapshots',
                   '.subactor/recovery', '.worktrees', '.pytest_cache')


def _read(path, limit, *, tail=False, owned=True):
    """Reject links/devices/FIFOs before reading; recheck the opened descriptor."""
    path = no_links(Path(path).absolute())
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or (owned and info.st_uid != os.getuid()):
            raise RecoveryError('Evidence must be an owned regular file')
        if info.st_size > limit and not tail:
            raise RecoveryError('Evidence exceeds byte quota')
        truncated = info.st_size > limit
        if truncated:
            os.lseek(fd, info.st_size - limit, os.SEEK_SET)
        with os.fdopen(fd, 'rb', closefd=False) as source:
            raw = source.read(limit + 1)
        if len(raw) > limit:
            raise RecoveryError('Evidence exceeds byte quota')
        text = raw.decode('utf-8', errors='replace')
        if truncated:
            text = text.partition('\n')[2]
        return text, info, truncated
    finally:
        os.close(fd)


def _age(timestamp, now, maximum):
    age = now - timestamp
    return ('unknown' if age < -5 else 'fresh' if age <= maximum else 'stale'), round(age, 1)


def analyze_threads(text):
    # Coroutine creation stacks repeat Java stack frames; never count those as threads.
    text = re.split(r'(?im)^\s*(?:Coroutine dump|Coroutines dump)\b', text, maxsplit=1)[0]
    blocks = re.split(r'(?m)^(?="[^"\n]+"\s)', text)[1:]
    result = {'java_threads': 0, 'docker_exit_waits': 0, 'ijent_filesystem_waits': 0,
              'terminal_close_waits': 0}
    if len(blocks) > 10000:
        raise RecoveryError('Thread count exceeds quota')
    for block in blocks:
        if 'java.lang.Thread.State:' not in block:
            continue
        result['java_threads'] += 1
        if 'DockerAgentContainerImpl' in block and 'waitForExit' in block:
            result['docker_exit_waits'] += 1
        if 'Ijent' in block and any(s in block for s in ('readAttributes', 'NativeIconProvider', 'JFileChooser')):
            result['ijent_filesystem_waits'] += 1
        if 'TerminalTabCloseListener' in block and 'runCloseCheckBlocking' in block:
            result['terminal_close_waits'] += 1
    return result


def _resources(proc):
    result = {'status': 'unavailable', 'pressure': {}}
    try:
        raw, _, _ = _read(proc / 'meminfo', 65536, owned=False)
        values = {key: int(value) for key, value in re.findall(r'^(\w+):\s+(\d+) kB$', raw, re.M)}
        total, available = values['MemTotal'], values['MemAvailable']
        if total <= 0 or not 0 <= available <= total:
            raise ValueError('Invalid memory counters')
        result.update(available_percent=round(100 * available / total, 2), status='available')
        if 'SwapTotal' in values and 'SwapFree' in values:
            if not 0 <= values['SwapFree'] <= values['SwapTotal']:
                raise ValueError('Invalid swap counters')
            result['swap_used_kib'] = values['SwapTotal'] - values['SwapFree']
    except (OSError, RecoveryError, ValueError, KeyError):
        result['status'] = 'unavailable'
    for kind in ('memory', 'io', 'cpu'):
        try:
            raw, _, _ = _read(proc / 'pressure' / kind, 4096, owned=False)
            rows = {}
            for line in raw.splitlines():
                fields = line.split()
                if not fields or fields[0] not in ('some', 'full'):
                    continue
                counters = dict(field.split('=', 1) for field in fields[1:])
                avg = float(counters['avg10'])
                if not math.isfinite(avg) or not 0 <= avg <= 100:
                    raise ValueError('Invalid pressure counter')
                rows[fields[0]] = avg
            if 'some' not in rows or (kind != 'cpu' and 'full' not in rows):
                raise ValueError('Incomplete pressure counters')
            result['pressure'][kind] = rows
        except (OSError, RecoveryError, ValueError, KeyError):
            result['pressure'][kind] = None
    return result


def _project_audit(project):
    result = {'status': 'unavailable', 'generated_roots': []}
    if project is None:
        return result
    try:
        root = no_links(Path(project).absolute())
        if not root.is_dir():
            return result
        idea = no_links(root / '.idea')
        def module_candidates(folder):
            with os.scandir(folder) as entries:
                names = list(itertools.islice(entries, 129))
            if len(names) > 128:
                raise RecoveryError('Directory entry count exceeds quota')
            return [folder / entry.name for entry in names if entry.name.endswith('.iml')]
        def xml(text):
            if '<!DOCTYPE' in text or '<!ENTITY' in text:
                raise RecoveryError('XML entity declarations are unsupported')
            return ET.fromstring(text)
        candidates = module_candidates(root)
        if idea.is_dir():
            candidates += module_candidates(idea)
        modules = idea / 'modules.xml'
        if modules.exists():
            raw, _, _ = _read(modules, 65536)
            for module in xml(raw).iter('module'):
                value = module.get('filepath', '').replace('$PROJECT_DIR$', str(root))
                if not value:
                    continue
                candidate = Path(value)
                if not candidate.is_absolute():
                    candidate = root / candidate
                candidate = Path(os.path.abspath(candidate))
                if not candidate.is_relative_to(root):
                    raise RecoveryError('Module outside inspected project')
                candidates.append(candidate)
                if len(candidates) > 64:
                    raise RecoveryError('Module count exceeds quota')
        candidates = list(dict.fromkeys(candidates))
        if len(candidates) > 64:
            raise RecoveryError('Module count exceeds quota')
        scopes, covers_root, unresolved = [], False, False
        for module in candidates:
            raw, _, _ = _read(module, 65536)
            def url_path(url):
                if not url.startswith('file://'):
                    return None
                value = url[7:].replace('$MODULE_DIR$', str(module.parent)).replace('$PROJECT_DIR$', str(root))
                if '$' in value:
                    return None
                return Path(os.path.abspath(value))
            for content in xml(raw).iter('content'):
                content_path = url_path(content.get('url', ''))
                paths = [url_path(node.get('url', '')) for node in content.findall('excludeFolder')]
                if content_path is None or any(path is None for path in paths):
                    unresolved = True
                    continue
                scopes.append((content_path, paths))
                if content_path == root:
                    covers_root = True
        for relative in GENERATED_ROOTS:
            folder = no_links(root / relative)
            if folder.is_dir():
                overlapping = [(content, paths) for content, paths in scopes
                               if folder.is_relative_to(content) or content.is_relative_to(folder)]
                excluded = covers_root and not unresolved and bool(overlapping) and all(
                    any((content if content.is_relative_to(folder) else folder).is_relative_to(path)
                        for path in paths) for content, paths in overlapping)
                result['generated_roots'].append({'root': relative, 'ide_exclusion':
                    'excluded' if excluded else 'not_excluded' if covers_root and not unresolved else 'unknown'})
        result['status'] = 'available' if covers_root and not unresolved else 'unknown'
    except (OSError, RecoveryError, ValueError, ET.ParseError):
        result['status'] = 'unavailable'
    return result


def _identity(proc, pid, expected_start):
    try:
        path = proc / str(pid)
        if path.stat().st_uid != os.getuid():
            return None
        raw, _, _ = _read(path / 'stat', 65536, owned=False)
        start = raw[raw.rindex(')') + 2:].split()[19]
        return start if start == str(expected_start) else None
    except (OSError, RecoveryError, ValueError, IndexError):
        return None


def inspect_health(*, log_dir=None, thread_dump=None, project=None, pid=None,
                   expected_start=None, max_age_seconds=600, now=None, proc_root='/proc'):
    if isinstance(max_age_seconds, bool) or not isinstance(max_age_seconds, int) or not 1 <= max_age_seconds <= 86400:
        raise RecoveryError('Evidence freshness must be 1..86400 seconds')
    if (pid is None) != (expected_start is None) or (pid is not None and (type(pid) is not int or pid <= 0)):
        raise RecoveryError('Process inspection requires a positive PID and expected_start together')
    now = time.time() if now is None else now
    proc = Path(proc_root)
    before = _identity(proc, pid, expected_start) if pid is not None else None
    findings = []
    def finding(code, severity, recommendation, **evidence):
        findings.append({'code': code, 'severity': severity, 'evidence': evidence,
                         'recommendation': recommendation})
    log = {'status': 'unavailable', 'io_exhaustion_events': 0}
    if log_dir is not None:
        try:
            raw, _, limited = _read(Path(log_dir) / 'idea.log', LOG_BYTES, tail=True)
            times, errors, malformed = [], [], False
            for line in raw.splitlines():
                match = re.match(r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3})', line)
                exhaustion = 'Thread pool exhaustion' in line and 'Dispatchers.IO' in line
                try:
                    timestamp = datetime.strptime(match[1], '%Y-%m-%d %H:%M:%S,%f').timestamp() if match else None
                except ValueError:
                    timestamp = None
                if timestamp is not None:
                    times.append(timestamp)
                if exhaustion:
                    if timestamp is None:
                        malformed = True
                    else:
                        errors.append(timestamp)
            freshness, age = _age(max(times), now, max_age_seconds) if times else ('unknown', None)
            log = {'status': 'unknown' if malformed or limited or '\ufffd' in raw else freshness, 'age_seconds': age,
                   'tail_limited': limited, 'io_exhaustion_events': len(errors)}
            if errors:
                event_status, event_age = _age(max(errors), now, max_age_seconds)
                finding('ide_io_exhaustion', 'critical' if event_status == 'fresh' else 'info',
                        'Avoid opening more projects or starting more containers; inspect Docker/IJent waits before recovery.',
                        freshness=event_status, age_seconds=event_age, events=len(errors))
        except (OSError, RecoveryError):
            pass
    dump = {'status': 'unavailable'}
    if thread_dump is not None:
        try:
            raw, info, _ = _read(thread_dump, DUMP_BYTES)
            counts = analyze_threads(raw)
            freshness, age = _age(info.st_mtime, now, max_age_seconds)
            dump = {'status': freshness if counts['java_threads'] and '\ufffd' not in raw else 'unknown', 'age_seconds': age, **counts}
            active = dump['status'] == 'fresh'
            # This is a conservative concentration heuristic, not a claimed JVM pool size.
            if counts['docker_exit_waits'] >= 32 and counts['ijent_filesystem_waits']:
                finding('docker_ijent_wait_concentration', 'critical' if active else 'info',
                        'Inspect IDE Docker integrations and IJent filesystem access; do not increase the IO thread limit blindly.',
                        freshness=dump['status'], **counts)
            elif counts['docker_exit_waits'] or counts['ijent_filesystem_waits']:
                finding('ide_external_io_waits', 'warning' if active else 'info',
                        'Check Docker and remote filesystem responsiveness before increasing IDE workload.',
                        freshness=dump['status'], **counts)
            if counts['terminal_close_waits']:
                finding('terminal_close_blocked', 'warning' if active else 'info',
                        'A terminal close check is waiting; inspect its dependencies before requesting more closes.',
                        freshness=dump['status'], threads=counts['terminal_close_waits'])
        except (OSError, RecoveryError):
            pass
    resources = _resources(proc)
    available = resources.get('available_percent')
    if available is not None and available < 10:
        finding('low_available_memory', 'critical' if available < 5 else 'warning',
                'Reduce concurrent workload before launching another IDE project.', available_percent=available)
    for kind, threshold in (('memory', 10), ('io', 20), ('cpu', 80)):
        pressure = resources['pressure'][kind]
        value = pressure.get('some' if kind == 'cpu' else 'full', 0) if pressure else 0
        if value >= threshold:
            finding(kind + '_pressure', 'critical' if kind == 'memory' or value >= 50 and kind == 'io' else 'warning',
                    'Reduce concurrent workload and inspect resource consumers before adding load.', avg10_percent=value)
    audit = _project_audit(project)
    roots = [item['root'] for item in audit['generated_roots'] if item['ide_exclusion'] != 'excluded']
    if roots:
        finding('generated_indexing_roots', 'warning',
                'Review IDE exclusions for generated cache/worktree roots; Git ignore alone does not prove IDE exclusion.', roots=roots)
    identity = 'not_requested' if pid is None else 'verified' if before and _identity(proc, pid, expected_start) == before else 'unknown'
    # A supplied file is never claimed to belong to a PID solely because the PID is alive.
    complete = (log['status'] == 'fresh' and dump['status'] == 'fresh' and
                resources['status'] == 'available' and all(resources['pressure'].values()) and
                (project is None or audit['status'] == 'available') and identity != 'unknown')
    severity = 'critical' if any(f['severity'] == 'critical' for f in findings) else 'warning' if any(f['severity'] == 'warning' for f in findings) else 'no_risk_observed' if complete else 'unknown'
    findings.sort(key=lambda f: {'critical': 0, 'warning': 1, 'info': 2}[f['severity']])
    return {'schema': 'uncrash.health/v1', 'read_only': True, 'status': severity,
            'preflight_exit_code': {'no_risk_observed': 0, 'warning': 1, 'critical': 2, 'unknown': 3}[severity],
            'scope': 'supplied evidence; no proof of application responsiveness or PID binding for log/dump',
            'process_identity': identity, 'log': log, 'thread_dump': dump, 'resources': resources,
            'project': audit, 'findings': findings}
