"""Verify the installed interpreter before persisting a user service."""
from __future__ import annotations

import importlib.metadata
import json
import os
from pathlib import Path
import selectors
import site
import subprocess
import sys
import sysconfig
import time

from .store import RecoveryError

# Validation bounds, rather than user-configurable operational settings.
_PROBE_SECONDS = 10
_PROBE_BYTES = 4096
_REFUSAL = (
    'Service installation requires a non-editable installed Uncrash package '
    'in a Python environment outside linked worktrees. Install a wheel in a '
    'persistent environment, then run its uncrash command.'
)


def _in_linked_checkout(path: Path) -> bool:
    return any((parent / '.git').is_file() for parent in (path, *path.parents))


def _installed_identity() -> dict:
    """Used in the child interpreter with cwd and PYTHONPATH excluded."""
    from . import cli

    package = Path(__file__).resolve().parent
    prefix = Path(sys.prefix).resolve()
    if _in_linked_checkout(package) or _in_linked_checkout(prefix):
        raise ValueError('linked checkout')
    paths = sysconfig.get_paths()
    libraries = {Path(paths[key]).resolve() for key in ('purelib', 'platlib')}
    libraries.update(Path(path).resolve() for path in site.getsitepackages())
    if site.ENABLE_USER_SITE:
        libraries.add(Path(site.getusersitepackages()).resolve())
    if not any(package.is_relative_to(path) for path in libraries):
        raise ValueError('source-only import')
    distribution = importlib.metadata.distribution('uncrash')
    direct = distribution.read_text('direct_url.json')
    if direct is not None:
        if len(direct) > _PROBE_BYTES:
            raise ValueError('oversized install metadata')
        info = json.loads(direct)
        if not isinstance(info, dict) or info.get('dir_info', {}).get('editable'):
            raise ValueError('editable installation')
    files = distribution.files
    if not files:
        raise ValueError('missing installation record')
    recorded = {Path(distribution.locate_file(file)).resolve() for file in files}
    if not {Path(__file__).resolve(), Path(cli.__file__).resolve()} <= recorded:
        raise ValueError('package does not belong to the installed distribution')
    return {'package': str(package), 'interpreter': os.path.abspath(sys.executable)}


def _probe(command: list[str], environment: dict[str, str]) -> bytes:
    deadline = time.monotonic() + _PROBE_SECONDS
    child = subprocess.Popen(command, cwd='/', env=environment, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    output = bytearray()
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise RecoveryError(_REFUSAL)
                chunk = os.read(child.stdout.fileno(), _PROBE_BYTES + 1 - len(output))
                if not chunk:
                    selector.unregister(child.stdout)
                output.extend(chunk)
                if len(output) > _PROBE_BYTES:
                    raise RecoveryError(_REFUSAL)
        if child.wait(timeout=max(0, deadline - time.monotonic())):
            raise RecoveryError(_REFUSAL)
        return bytes(output)
    finally:
        child.stdout.close()
        if child.poll() is None:
            child.kill()
        child.wait(timeout=1)


def service_interpreter() -> str:
    """Return the verified interpreter, or refuse before installation effects."""
    interpreter = os.path.abspath(sys.executable)
    environment = {key: os.environ[key] for key in ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TZ')
                   if key in os.environ}
    command = [interpreter, '-E', '-P', '-c',
               'import json; from uncrash.installation import _installed_identity; '
               'print(json.dumps(_installed_identity()))']
    try:
        identity = json.loads(_probe(command, environment))
        if identity != {'package': str(Path(__file__).resolve().parent),
                        'interpreter': interpreter}:
            raise RecoveryError(_REFUSAL)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise RecoveryError(_REFUSAL) from exc
    return interpreter
