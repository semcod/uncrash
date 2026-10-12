"""Typed non-secret deployment settings; values are data, never shell code."""
from __future__ import annotations

from contextvars import ContextVar
import ipaddress
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit


# Compatibility defaults for older installations without the expanded template.
# The public BASE document and the selected deployment .env override these.
FIELDS = {
    'UNCRASH_ENCRYPT': ('encrypt', 'bool', 'false'),
    'UNCRASH_COMPRESS': ('compress', 'bool', 'false'),
    'UNCRASH_SNAPSHOT_ENGINE': ('snapshot_engine', 'engine', 'rust'),
    'UNCRASH_RUST_THREADS': ('rust_threads', 'int', '4'),
    'UNCRASH_RUST_BINARY': ('rust_binary', 'optional_path', None),
    'UNCRASH_INTERVAL_SECONDS': ('interval_seconds', 'int', '300'),
    'UNCRASH_RETENTION': ('retention', 'int', '288'),
    'UNCRASH_RETENTION_AGE_SECONDS': ('retention_age_seconds', 'int', '86400'),
    'UNCRASH_RETENTION_CHECK_SECONDS': ('retention_check_seconds', 'int', '60'),
    'UNCRASH_MAX_FILE_BYTES': ('max_file_bytes', 'int', '536870912'),
    'UNCRASH_MAX_BYTES': ('max_bytes', 'int', '17179869184'),
    'UNCRASH_MAX_TOTAL_BYTES': ('max_total_bytes', 'int', '34359738368'),
    'UNCRASH_STARTUP_RESTORE': ('startup_restore', 'bool', 'false'),
    'UNCRASH_JETBRAINS_METADATA': ('jetbrains_metadata', 'bool', 'false'),
    'UNCRASH_STATE_DIR': ('state_dir', 'path', '~/.local/state/uncrash'),
    'UNCRASH_CONFIG_FILE': ('config_file', 'path', '~/.config/uncrash/config.json'),
    'UNCRASH_API_HOST': ('api_host', 'host', '127.0.0.1'),
    'UNCRASH_API_PORT': ('api_port', 'port', '8795'),
    'UNCRASH_MCP_HOST': ('mcp_host', 'host', '127.0.0.1'),
    'UNCRASH_MCP_PORT': ('mcp_port', 'port', '18795'),
    'UNCRASH_MCP_TRANSPORT': ('mcp_transport', 'transport', 'stdio'),
    'UNCRASH_PREVIEW_HOST': ('preview_host', 'loopback', '127.0.0.1'),
    'UNCRASH_PREVIEW_WIDTH': ('preview_width', 'int', '1280'),
    'UNCRASH_PREVIEW_HEIGHT': ('preview_height', 'int', '800'),
    'UNCRASH_PREVIEW_DISPLAY_START': ('preview_display_start', 'int', '150'),
    'UNCRASH_PREVIEW_DISPLAY_END': ('preview_display_end', 'int', '400'),
    'UNCRASH_NOVNC_ASSETS': ('novnc_assets', 'path', '/usr/share/novnc'),
    'UNCRASH_TWINERD_NATIVE_PATH': ('twinerd_native_path', 'path', '~/github/twinerd/twinerd/packages/twinerd-mcp'),
    'UNCRASH_TWINERD_KASM_PATH': ('twinerd_kasm_path', 'path', '~/github/twinerd/twinerd/packages/twinerd-kasm'),
    'UNCRASH_CLONEBOX_PATH': ('clonebox_path', 'path', '~/github/wronai/clonebox/src'),
    'UNCRASH_PELORUS_PATH': ('pelorus_path', 'path', '~/github/twinerd/twinerd/packages/twinerd-pelorus'),
    'UNCRASH_HEALTH_MAX_AGE_SECONDS': ('health_max_age_seconds', 'int', '600'),
    'UNCRASH_TRANSFER_TIMEOUT_SECONDS': ('transfer_timeout_seconds', 'int', '600'),
    'UNCRASH_NATIVE_BUILD_TIMEOUT_SECONDS': ('native_build_timeout_seconds', 'int', '120'),
    'UNCRASH_NATIVE_CAPTURE_TIMEOUT_SECONDS': ('native_capture_timeout_seconds', 'int', '600'),
    'UNCRASH_SQLITE_BACKUP_TIMEOUT_SECONDS': ('sqlite_backup_timeout_seconds', 'int', '10'),
    'UNCRASH_APX_PORT': ('apx_port', 'port', '18893'),
    'UNCRASH_APX_BACKEND_URL': ('apx_backend_url', 'loopback_http', 'http://127.0.0.1:18891/'),
    'UNCRASH_APX_STATE_DIR': ('apx_state_dir', 'path', '~/.local/state/uncrash-apx'),
    'UNCRASH_APX_SSH_HOST': ('apx_ssh_host', 'ssh_host', None),
    'UNCRASH_APX_PREVIEW_TIMEOUT_MILLISECONDS': ('apx_preview_timeout_milliseconds', 'int', '200'),
    'UNCRASH_APX_REQUEST_TIMEOUT_SECONDS': ('apx_request_timeout_seconds', 'int', '5'),
    'UNCRASH_APX_TRANSFER_TIMEOUT_SECONDS': ('apx_transfer_timeout_seconds', 'int', '15'),
    'UNCRASH_APX_TRANSFER_PROCESS_TIMEOUT_SECONDS': ('apx_transfer_process_timeout_seconds', 'int', '30'),
    'UNCRASH_LOG_MAX_HOURLY_BYTES': ('log_max_hourly_bytes', 'int', '4194304'),
}
HEADERS = ('ENV_DSL_VERSION', 'ENV_DSL_NAMESPACE', 'ENV_DSL_ENVIRONMENT')
_SELECTED_FILE = None
_CONTEXT_FILE = ContextVar('uncrash_environment_file', default=None)


class SettingsError(ValueError):
    pass


def _convert(name, value):
    key, kind, _ = FIELDS[name]
    if not isinstance(value, str) or not value or any(c in value for c in ('\x00', '$', '`')) or any(marker in value.lower() for marker in ('re.compile(', 'regexp.new(', 'pattern.compile(', 'regex.compile(', 'eval(', 'exec(', 'system(')):
        raise SettingsError('ENV-SECURITY-001: environment values must be inert literals')
    if kind == 'bool':
        if value.lower() not in ('true', 'false', '1', '0'):
            raise SettingsError('ENV-SEMANTIC-001: invalid environment boolean')
        result = value.lower() in ('true', '1')
    elif kind in ('int', 'port'):
        if not value.isascii() or not value.isdecimal() or int(value) <= 0:
            raise SettingsError('ENV-SEMANTIC-001: limits must be positive integers')
        result = int(value)
        if kind == 'port' and result > 65535:
            raise SettingsError('ENV-SEMANTIC-001: port must be 1..65535')
    elif kind == 'engine':
        if value not in ('rust', 'python'):
            raise SettingsError('Select rust or python snapshot engine')
        result = value
    elif kind == 'transport':
        if value not in ('stdio', 'sse', 'streamable-http'):
            raise SettingsError('ENV-SEMANTIC-001: unsupported MCP transport')
        result = value
    elif kind in ('path', 'optional_path'):
        from .store import no_links
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            raise SettingsError('Environment paths must be absolute or start with ~/')
        result = str(no_links(candidate))
    elif kind == 'ssh_host':
        if re.fullmatch(r'[a-zA-Z0-9_.-]+@[a-zA-Z0-9][a-zA-Z0-9_.-]*', value) is None:
            raise SettingsError('ENV-SEMANTIC-001: configure an explicit SSH user and host')
        result = value
    elif kind == 'loopback_http':
        try:
            url = urlsplit(value)
            valid = url.scheme == 'http' and url.hostname == '127.0.0.1' and not url.username and not url.password and url.port and not url.fragment
        except ValueError:
            valid = False
        if not valid:
            raise SettingsError('ENV-SECURITY-001: APX backend must be a loopback HTTP URL without credentials')
        result = value
    elif kind in ('host', 'loopback'):
        if len(value) > 253 or re.fullmatch(r'[A-Za-z0-9.-]+', value) is None:
            raise SettingsError('ENV-SEMANTIC-001: invalid host')
        if kind == 'loopback':
            try:
                address = ipaddress.ip_address(value)
                allowed = address.version == 4 and address.is_loopback
            except ValueError:
                allowed = False
            if not allowed:
                raise SettingsError('ENV-SECURITY-001: preview must bind an IPv4 loopback address')
        result = value
    else:
        raise SettingsError('ENV-SEMANTIC-001: unknown setting type')
    return key, result


def _validate(settings):
    if settings.get('apx_port', 18893) < 1024:
        raise SettingsError('ENV-SECURITY-001: APX must use a non-privileged port')
    if settings.get('apx_transfer_process_timeout_seconds', 30) <= settings.get('apx_transfer_timeout_seconds', 15):
        raise SettingsError('ENV-SEMANTIC-001: APX process deadline must exceed transfer deadline')
    if not 1 <= settings.get('rust_threads', 4) <= 16:
        raise SettingsError('Rust threads must be between 1 and 16')
    if not 5 <= settings.get('interval_seconds', 300) <= 86400:
        raise SettingsError('Snapshot interval must be 5..86400 seconds')
    if not 1 <= settings.get('retention', 288) <= 10000:
        raise SettingsError('ENV-SEMANTIC-001: retention must be 1..10000')
    if settings.get('preview_display_start', 150) >= settings.get('preview_display_end', 400):
        raise SettingsError('ENV-SEMANTIC-001: display search range is empty')
    if settings.get('preview_display_end', 400) > 65536:
        raise SettingsError('ENV-SEMANTIC-001: display search range is oversized')
    if any(settings.get(k, 1) > 16384 for k in ('preview_width', 'preview_height')):
        raise SettingsError('ENV-SEMANTIC-001: preview dimensions are oversized')
    if not 1 <= settings.get('health_max_age_seconds', 600) <= 86400:
        raise SettingsError('ENV-SEMANTIC-001: health evidence age must be 1..86400')


def environment_settings(path, environ=None, *, include_defaults=True):
    values = {}
    canonical = False
    if path is not None and Path(path).exists():
        from .store import no_links
        path = no_links(path)
        if not path.is_file() or path.stat().st_uid != os.getuid() or path.stat().st_size > 65536:
            raise SettingsError('ENV-SECURITY-001: environment file must be bounded, owned and regular')
        raw = path.read_bytes()
        try:
            text = raw.decode('utf-8')
        except UnicodeError as exc:
            raise SettingsError('ENV-SYNTAX-001: invalid UTF-8') from exc
        canonical = any(line.lstrip().startswith('ENV_DSL_') for line in text.splitlines())
        if canonical and (not raw.endswith(b'\n') or any(b != 10 and not 32 <= b <= 126 for b in raw)):
            raise SettingsError('ENV-SYNTAX-001: Env DSL requires ASCII and LF')
        records = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith('#'):
                continue
            if canonical and raw_line != line:
                raise SettingsError('ENV-SYNTAX-001: assignment whitespace is forbidden')
            if not canonical and line.startswith('export '):
                line = line[7:]
            name, separator, value = line.partition('=')
            if not canonical:
                name, value = name.strip(), value.strip()
            if not separator or name in values or re.fullmatch(r'[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*', name) is None:
                raise SettingsError('ENV-SYNTAX-001: unknown, duplicate or malformed setting')
            if canonical and (not value or any(c.isspace() or c in '\"\'' for c in value)):
                raise SettingsError('ENV-SYNTAX-001: Env DSL values cannot be quoted or contain spaces')
            if not canonical and value.startswith(('"', "'")):
                if len(value) < 2 or value[-1] != value[0]:
                    raise SettingsError('Invalid quoted environment value')
                value = value[1:-1]
            if name not in FIELDS and name not in (*HEADERS, 'ENV_DSL_EXTENDS'):
                raise SettingsError('ENV-SEMANTIC-001: unknown environment setting')
            values[name] = value
            records.append(name)
        if canonical:
            if tuple(records[:3]) != HEADERS or values[HEADERS[0]] != '1' or values[HEADERS[1]] != 'UNCRASH':
                raise SettingsError('ENV-SEMANTIC-001: invalid Uncrash Env DSL identity')
            environment = values[HEADERS[2]]
            if re.fullmatch(r'[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*', environment) is None:
                raise SettingsError('ENV-LAYER-001: invalid environment identity')
            if environment == 'BASE':
                if 'ENV_DSL_EXTENDS' in values:
                    raise SettingsError('ENV-LAYER-001: BASE cannot extend a layer')
            elif records[3:4] != ['ENV_DSL_EXTENDS'] or values.get('ENV_DSL_EXTENDS') != 'BASE':
                raise SettingsError('ENV-LAYER-001: deployment must explicitly extend BASE')
    # Explicit adapter input remains supported for legacy callers. Canonical files
    # never implicitly consult ambient process values for their constants.
    overrides = ({} if canonical else os.environ) if environ is None else environ
    values.update({k: overrides[k] for k in FIELDS if k in overrides})
    result = {'encrypt': False, 'snapshot_engine': 'rust', 'compress': False} if include_defaults else {}
    for name, value in values.items():
        if name in FIELDS:
            key, converted = _convert(name, value)
            result[key] = converted
    _validate(result)
    return result


def activate_environment_file(path):
    return _CONTEXT_FILE.set(Path(path) if path is not None else None)


def runtime_settings(config=None):
    """One deployment map; explicit SDK configuration is an intentional override."""
    result = dict(_convert(name, default) for name, (_, _, default) in FIELDS.items() if default is not None)
    template = Path(__file__).parents[2] / '.env.example'
    if not template.exists():
        template = Path(sys.prefix) / 'share/uncrash/.env.example'
    if template.exists():
        result.update(environment_settings(template, {}, include_defaults=False))
    selected = _CONTEXT_FILE.get() or _SELECTED_FILE
    if selected is None:
        explicit = os.environ.get('UNCRASH_ENV_FILE')
        local = Path.cwd() / '.env'
        selected = Path(explicit).expanduser() if explicit else local if local.exists() and local != Path.home() / '.env' else Path.home() / '.config/uncrash/.env'
    if selected.exists():
        result.update(environment_settings(selected, include_defaults=False))
    if config is not None:
        result.update(config)
    _validate(result)
    # Validate the preview binding even for SDK configuration, never expose VNC.
    _convert('UNCRASH_PREVIEW_HOST', result['preview_host'])
    return result


def reset_environment_file(token):
    _CONTEXT_FILE.reset(token)
