import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from uncrash import configuration as settings
from uncrash import cli, preview


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, '_SELECTED_FILE', tmp_path / '.env')


def env_file(tmp_path, records, *, canonical=False):
    header = 'ENV_DSL_VERSION=1\nENV_DSL_NAMESPACE=UNCRASH\nENV_DSL_ENVIRONMENT=BASE\n' if canonical else ''
    p = tmp_path / '.env'
    p.write_text(header + records + '\n')
    return p


def test_canonical_file_is_authoritative_over_ambient_values(tmp_path, monkeypatch):
    p = env_file(tmp_path, 'UNCRASH_API_PORT=15432\nUNCRASH_RETENTION_AGE_SECONDS=86400', canonical=True)
    monkeypatch.setenv('UNCRASH_API_PORT', '19000')
    parsed = settings.environment_settings(p)
    assert parsed['api_port'] == 15432 and parsed['retention_age_seconds'] == 86400


@pytest.mark.parametrize('record', [
    'UNCRASH_API_PORT=65536', 'UNCRASH_API_PORT=0', 'UNCRASH_API_PORT=true',
    'UNCRASH_PREVIEW_HOST=0.0.0.0', 'UNCRASH_PREVIEW_DISPLAY_START=500',
    'UNCRASH_PREVIEW_WIDTH=20000', 'UNCRASH_RETENTION_AGE_SECONDS=-1',
    'UNCRASH_RETENTION_CHECK_SECONDS=0', 'UNCRASH_API_HOST=$(touch_SENTINEL)',
    'UNCRASH_CLONEBOX_PATH=/tmp/eval(inert)', 'UNCRASH_PASSWORD=do-not-echo',
    'UNCRASH_API_PORT=10000\nUNCRASH_API_PORT=20000',
])
def test_invalid_or_unsafe_configuration_is_rejected_without_values_in_error(tmp_path, record):
    p = env_file(tmp_path, record, canonical=True)
    with pytest.raises(ValueError) as error:
        settings.environment_settings(p)
    assert 'do-not-echo' not in str(error.value) and not (tmp_path / 'SENTINEL').exists()


@pytest.mark.parametrize('mutation', [
    lambda x: x.replace('ENV_DSL_VERSION=1', ' ENV_DSL_VERSION=1'),
    lambda x: x.replace('ENV_DSL_NAMESPACE=UNCRASH', 'ENV_DSL_NAMESPACE=OTHER'),
    lambda x: x.replace('UNCRASH_API_PORT=15432', 'UNCRASH_API_PORT="15432"'),
    lambda x: x.replace('UNCRASH_API_PORT=15432', 'UNCRASH_API_PORT =15432'),
    lambda x: x.replace('\n', '\r\n'),
    lambda x: x.rstrip('\n'),
    lambda x: x.replace('BASE\n', 'LOCAL\n'),
])
def test_env_dsl_identity_encoding_and_layer_rules(tmp_path, mutation):
    p = env_file(tmp_path, 'UNCRASH_API_PORT=15432', canonical=True)
    p.write_bytes(mutation(p.read_text()).encode())
    with pytest.raises(ValueError):
        settings.environment_settings(p)


def test_explicit_deployment_layer_and_symlink_refusal(tmp_path):
    p = env_file(tmp_path, 'UNCRASH_API_PORT=15432', canonical=True)
    p.write_text(p.read_text().replace('ENV_DSL_ENVIRONMENT=BASE\n', 'ENV_DSL_ENVIRONMENT=LOCAL\nENV_DSL_EXTENDS=BASE\n'))
    assert settings.environment_settings(p, {})['api_port'] == 15432
    link = tmp_path / 'linked.env'
    link.symlink_to(p)
    with pytest.raises(ValueError):
        settings.environment_settings(link)


def test_backend_paths_dimensions_and_display_search_use_same_file(tmp_path):
    backend = tmp_path / 'fixture-backend'; backend.mkdir()
    assets = tmp_path / 'assets'; assets.mkdir()
    env_file(tmp_path, f'UNCRASH_CLONEBOX_PATH={backend}\nUNCRASH_NOVNC_ASSETS={assets}\nUNCRASH_PREVIEW_WIDTH=1024\nUNCRASH_PREVIEW_HEIGHT=640\nUNCRASH_PREVIEW_DISPLAY_START=411\nUNCRASH_PREVIEW_DISPLAY_END=413')
    engines = {r['id']: r for r in preview.get_virtualization_engines()}
    assert engines['clonebox']['pkg_path'] == str(backend) and engines['clonebox']['available']
    assert engines['clonebox-container']['pkg_path'] == str(backend)
    desktop = preview.VirtualPreviewDesktop()
    assert (desktop.width, desktop.height, desktop.novnc_dir) == (1024, 640, assets)
    assert preview._find_free_display() in (411, 412)


def test_rest_binding_comes_from_env_and_explicit_cli_override_wins(tmp_path, monkeypatch):
    p = env_file(tmp_path, 'UNCRASH_API_HOST=127.0.0.2\nUNCRASH_API_PORT=15432', canonical=True)
    config = tmp_path / 'config.json'; config.write_text(json.dumps({'profiles': [], 'api_port': 19000}))
    calls = []
    monkeypatch.setitem(sys.modules, 'uvicorn', SimpleNamespace(run=lambda app, **kwargs: calls.append(kwargs)))
    from uncrash import api
    monkeypatch.setattr(api, 'create_fastapi_app', lambda **kwargs: object())
    args = ['--env-file', str(p), '--config', str(config), '--state', str(tmp_path / 'store'), 'serve']
    assert cli.main(args) == 0
    assert calls[-1] == {'host': '127.0.0.2', 'port': 15432}
    assert cli.main(args + ['--port', '15500']) == 0
    assert calls[-1]['port'] == 15500


def test_mcp_network_binding_and_transport_come_from_env(tmp_path, monkeypatch):
    p = env_file(tmp_path, 'UNCRASH_MCP_HOST=127.0.0.3\nUNCRASH_MCP_PORT=15433\nUNCRASH_MCP_TRANSPORT=sse', canonical=True)
    config = tmp_path / 'config.json'; config.write_text('{"profiles": []}')
    calls = []
    monkeypatch.setitem(sys.modules, 'uvicorn', SimpleNamespace(run=lambda app, **kwargs: calls.append(kwargs)))
    from uncrash import api
    monkeypatch.setattr(api, 'create_mcp_server', lambda **kwargs: SimpleNamespace(sse_app=lambda: object()))
    assert cli.main(['--env-file', str(p), '--config', str(config), '--state', str(tmp_path / 'store'), 'mcp']) == 0
    assert calls == [{'host': '127.0.0.3', 'port': 15433}]
