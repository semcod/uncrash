import asyncio
import json
import pytest
from uncrash.api import create_fastapi_app, create_mcp_server, OPERATIONS_REGISTRY

def test_registry_standards():
    assert len(OPERATIONS_REGISTRY) >= 4
    for op in OPERATIONS_REGISTRY:
        assert "id" in op
        assert "name" in op
        assert "protocols" in op
        assert set(["cli", "rest", "mcp"]).issubset(set(op["protocols"]))

def test_fastapi_endpoints():
    from fastapi.testclient import TestClient
    app = create_fastapi_app()
    client = TestClient(app)

    res = client.get("/api/v1/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    assert "wellmanifest/nl-api-llm" in res.json()["standards"]

    reg = client.get("/api/v1/registry")
    assert reg.status_code == 200
    assert reg.json()["standard"] == "wellmanifest/nl-api-llm"
    assert len(reg.json()["operations"]) >= 4

    apps_res = client.get("/api/v1/apps")
    assert apps_res.status_code == 200
    assert "applications" in apps_res.json()

def test_mcp_server_tools():
    server = create_mcp_server()
    async def run_mcp_checks():
        tools = await server.list_tools()
        tool_names = [t.name for t in tools]
        assert "uncrash_list_gui_apps" in tool_names
        assert "uncrash_close_gui_app" in tool_names
        assert "uncrash_get_jetbrains_state" in tool_names
        assert "uncrash_get_desktop_inventory" in tool_names

        call_res = await server.call_tool("uncrash_list_gui_apps", {})
        assert len(call_res.content) > 0
        parsed = json.loads(call_res.content[0].text)
        assert "applications" in parsed

        inv_res = await server.call_tool("uncrash_get_desktop_inventory", {})
        assert len(inv_res.content) > 0
        parsed_inv = json.loads(inv_res.content[0].text)
        assert "launchers" in parsed_inv

    asyncio.run(run_mcp_checks())


def test_web_dashboard_and_snapshot_endpoints(tmp_path):
    from fastapi.testclient import TestClient
    from uncrash.store import Store

    store = Store(tmp_path / 'store', 'test-origin')
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'test.txt').write_text('content')
    config = {'origin': 'test-origin', 'profiles': [{'id': 'app', 'state_dir': str(source), 'argv': []}]}
    sid = store.capture(config)['snapshot']

    app = create_fastapi_app(store=store, config=config)
    client = TestClient(app)

    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "uncrash" in res.text.lower()

    snaps_res = client.get("/api/v1/snapshots")
    assert snaps_res.status_code == 200
    data = snaps_res.json()
    assert data["schema"] == "uncrash.snapshots-list/v1"
    assert data["count"] >= 1
    assert any(s["id"] == sid for s in data["snapshots"])

    snap_res = client.get(f"/api/v1/snapshots/{sid}")
    assert snap_res.status_code == 200
    snap_data = snap_res.json()
    assert snap_data["snapshot"] == sid
    assert "terminal_tabs" in snap_data

    launch_res = client.post(f"/api/v1/snapshots/{sid}/launch-tabs?dry_run=true")
    assert launch_res.status_code == 200

