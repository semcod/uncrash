"""Universal multi-protocol API conforming to wellmanifest/nl-api-llm and wellmanifest/skills.

Dispatches operations across Shell CLI, REST HTTP (FastAPI) and MCP (Model Context Protocol).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .recovery import detected_gui_apps, close_gui_app, jetbrains_state
from .inventory import desktop_inventory
from .web_ui import DASHBOARD_HTML


# Universal API Registry conforming to wellmanifest/nl-api-llm
OPERATIONS_REGISTRY = [
    {
        "id": "uncrash.apps.list",
        "name": "list_gui_apps",
        "description": "List all active, user-opened windowed GUI applications with process IDs, names and open projects.",
        "protocols": ["cli", "rest", "mcp"],
        "schema": "uncrash.gui-apps/v1",
        "parameters": {}
    },
    {
        "id": "uncrash.apps.close",
        "name": "close_gui_app",
        "description": "Safely terminate a user-opened windowed application by PID or name (using SIGTERM with SIGKILL fallback).",
        "protocols": ["cli", "rest", "mcp"],
        "schema": "uncrash.action-result/v1",
        "parameters": {
            "pid": {"type": "integer", "description": "Process ID of the application", "required": False},
            "name": {"type": "string", "description": "Application name or substring (e.g. 'pycharm', 'chrome')", "required": False},
            "force": {"type": "boolean", "description": "Force immediate termination (SIGKILL) if unresponsive", "default": False}
        }
    },
    {
        "id": "uncrash.jetbrains.state",
        "name": "get_jetbrains_state",
        "description": "Inspect running JetBrains IDE JVM processes, open projects and persisted metadata without modifying state.",
        "protocols": ["cli", "rest", "mcp"],
        "schema": "uncrash.jetbrains-live-state/v1",
        "parameters": {}
    },
    {
        "id": "uncrash.system.inventory",
        "name": "get_desktop_inventory",
        "description": "Discover available desktop application launchers (.desktop files) and CLI commands.",
        "protocols": ["cli", "rest", "mcp"],
        "schema": "uncrash.desktop-inventory/v1",
        "parameters": {}
    },
    {
        "id": "uncrash.snapshots.list",
        "name": "list_snapshots",
        "description": "List all local crash recovery snapshots with summary metrics, timestamp and tab counts.",
        "protocols": ["cli", "rest", "mcp"],
        "schema": "uncrash.snapshots-list/v1",
        "parameters": {}
    },
    {
        "id": "uncrash.snapshots.preview",
        "name": "preview_snapshot",
        "description": "Inspect recorded terminal tabs, GUI applications and launch commands for a specific snapshot.",
        "protocols": ["cli", "rest", "mcp"],
        "schema": "uncrash.snapshot-preview/v1",
        "parameters": {
            "snapshot_id": {"type": "string", "description": "Snapshot ID or 'latest'", "default": "latest"}
        }
    },
    {
        "id": "uncrash.snapshots.launch_tabs",
        "name": "launch_terminal_tabs",
        "description": "Launch recorded terminal tabs from a snapshot in the system terminal (gnome-terminal).",
        "protocols": ["cli", "rest", "mcp"],
        "schema": "uncrash.tabs-launch/v1",
        "parameters": {
            "snapshot_id": {"type": "string", "description": "Snapshot ID or 'latest'", "default": "latest"},
            "dry_run": {"type": "boolean", "description": "Report planned command without launching", "default": False}
        }
    },
    {
        "id": "uncrash.workspaces.list",
        "name": "list_workspaces",
        "description": "List active isolated noVNC virtual desktop workspaces running snapshot sessions via Twinerd.",
        "protocols": ["cli", "rest", "mcp"],
        "schema": "uncrash.workspaces-list/v1",
        "parameters": {}
    },
    {
        "id": "uncrash.virtualization.engines",
        "name": "list_virtualization_engines",
        "description": "List all supported virtualization and workspace engines (Twinerd, Kasm, CloneBox VM, CloneBox Container, Pelorus Twin).",
        "protocols": ["cli", "rest", "mcp"],
        "schema": "uncrash.virtualization-engines/v1",
        "parameters": {}
    },
    {
        "id": "uncrash.workspaces.create",
        "name": "create_snapshot_workspace",
        "description": "Launch a dedicated noVNC workspace running all recorded terminal tabs for a specific snapshot.",
        "protocols": ["cli", "rest", "mcp"],
        "schema": "uncrash.workspace-session/v1",
        "parameters": {
            "snapshot_id": {"type": "string", "description": "Snapshot ID to restore/preview in workspace"},
            "workspace_id": {"type": "string", "description": "Optional custom workspace identifier", "required": False},
            "force_new": {"type": "boolean", "description": "Force creating a new workspace rather than reusing existing", "default": False},
            "engine": {"type": "string", "description": "Virtualization engine: 'native' (Twinerd/TigerVNC), 'kasm' (twinerd-kasm), 'clonebox' (CloneBox VM), 'clonebox-container' (CloneBox Container), or 'pelorus' (Pelorus Twin)", "default": "native"}
        }
    },
    {
        "id": "uncrash.workspaces.close",
        "name": "close_workspace",
        "description": "Close an active noVNC virtual desktop workspace and stop all its processes.",
        "protocols": ["cli", "rest", "mcp"],
        "schema": "uncrash.workspace-close/v1",
        "parameters": {
            "workspace_id": {"type": "string", "description": "Workspace ID to close"}
        }
    },
    {
        "id": "uncrash.system.gpu",
        "name": "get_gpu_status",
        "description": "Inspect host GPU hardware (NVIDIA GeForce/RTX/CUDA, VRAM, temperature, driver) and GPU tools.",
        "protocols": ["cli", "rest", "mcp"],
        "schema": "uncrash.gpu-status/v1",
        "parameters": {}
    },
    {
        "id": "uncrash.system.applications",
        "name": "get_installed_applications",
        "description": "Discover and classify all installed PC applications (NVIDIA, AI agents, IDEs, browsers, terminals, virtualization) with recovery profiles.",
        "protocols": ["cli", "rest", "mcp"],
        "schema": "uncrash.application-matrix/v1",
        "parameters": {}
    }
]


def _resolve_default_store(store=None, config=None):
    if store is not None:
        return store, config or {'profiles': []}
    state_dir = Path.home() / '.local/state/uncrash'
    config_file = Path.home() / '.config/uncrash/config.json'
    resolved_config = config or {}
    if config_file.exists():
        try:
            resolved_config = {**json.loads(config_file.read_text()), **resolved_config}
        except Exception:
            pass
    from .store import Store
    resolved_store = Store(state_dir, resolved_config.get('origin'), encrypt=resolved_config.get('encrypt', False))
    return resolved_store, resolved_config


def create_fastapi_app(store=None, config=None):
    """Create FastAPI REST application with integrated Web Client dashboard."""
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse, FileResponse
    from pydantic import BaseModel

    app = FastAPI(
        title="Uncrash Multi-Protocol API & Dashboard",
        version="0.1.2",
        description="Unified REST and MCP API with Web Dashboard conforming to wellmanifest/nl-api-llm"
    )

    resolved_store, resolved_config = _resolve_default_store(store, config)

    class CloseAppRequest(BaseModel):
        pid: Optional[int] = None
        name: Optional[str] = None
        force: bool = False
        expected_start: Optional[str] = None

    @app.get("/", response_class=HTMLResponse)
    @app.get("/ui", response_class=HTMLResponse)
    def web_dashboard():
        return HTMLResponse(content=DASHBOARD_HTML)

    @app.get("/api/v1/health")
    def health():
        return {"status": "ok", "service": "uncrash", "standards": ["wellmanifest/nl-api-llm", "wellmanifest/skills"]}

    @app.get("/api/v1/registry")
    def registry():
        return {
            "schema": "wellmanifest.api-registry/v1",
            "standard": "wellmanifest/nl-api-llm",
            "operations": OPERATIONS_REGISTRY
        }

    @app.get("/api/v1/apps")
    def get_apps():
        apps = detected_gui_apps()
        return {"schema": "uncrash.gui-apps/v1", "count": len(apps), "applications": apps}

    @app.post("/api/v1/apps/close")
    def post_close_app(req: CloseAppRequest):
        try:
            res = close_gui_app(pid=req.pid, name=req.name, force=req.force, expected_start=req.expected_start)
            return res
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/api/v1/jetbrains")
    def get_jetbrains():
        return jetbrains_state()

    @app.get("/api/v1/inventory")
    def get_inventory():
        return {"schema": "uncrash.desktop-inventory/v1", "launchers": desktop_inventory()}

    @app.get("/api/v1/snapshots")
    def get_snapshots():
        from .preview import extract_preview_metadata
        snapshot_ids = resolved_store.list()
        items = []
        for sid in reversed(snapshot_ids):
            try:
                _, _, _, manifest = resolved_store.load(sid)
                meta = extract_preview_metadata(manifest, sid)
                items.append({
                    "id": sid,
                    "created_at": meta.get("created_at"),
                    "profiles": meta.get("profiles", []),
                    "terminal_tabs_count": meta.get("terminal_tabs_count", 0),
                    "gui_projects_count": meta.get("gui_projects_count", 0)
                })
            except Exception:
                items.append({"id": sid, "error": "unreadable"})
        return {"schema": "uncrash.snapshots-list/v1", "count": len(items), "snapshots": items}

    @app.get("/api/v1/snapshots/{snapshot_id}")
    def get_snapshot(snapshot_id: str):
        from .preview import extract_preview_metadata
        try:
            _, _, _, manifest = resolved_store.load(snapshot_id)
            return extract_preview_metadata(manifest, snapshot_id)
        except Exception as e:
            raise HTTPException(status_code=404, detail=str(e))

    @app.post("/api/v1/snapshots/{snapshot_id}/novnc")
    def post_snapshot_novnc(snapshot_id: str, port: Optional[int] = None):
        from .preview import preview_snapshot
        try:
            res = preview_snapshot(resolved_store, snapshot_id, resolved_config, novnc=True, port=port)
            if res.get("novnc"):
                return res["novnc"]
            raise HTTPException(status_code=500, detail=res.get("novnc_error", "Failed to launch noVNC"))
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/v1/snapshots/{snapshot_id}/screenshot")
    def post_snapshot_screenshot(snapshot_id: str):
        from .preview import preview_snapshot, _temp_dir
        shot_path = _temp_dir() / f"screenshot-{snapshot_id}.png"
        try:
            res = preview_snapshot(resolved_store, snapshot_id, resolved_config, screenshot=shot_path)
            if shot_path.exists():
                return {"status": "ok", "screenshot_url": f"/api/v1/snapshots/{snapshot_id}/screenshot.png"}
            raise HTTPException(status_code=500, detail=res.get("novnc_error", "Failed to capture screenshot"))
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/v1/snapshots/{snapshot_id}/screenshot.png")
    def get_snapshot_screenshot_file(snapshot_id: str):
        from .preview import _temp_dir
        shot_path = _temp_dir() / f"screenshot-{snapshot_id}.png"
        if not shot_path.exists():
            raise HTTPException(status_code=404, detail="Screenshot not found; generate it first via POST")
        return FileResponse(shot_path, media_type="image/png")

    @app.post("/api/v1/snapshots/{snapshot_id}/launch-tabs")
    def post_launch_tabs(snapshot_id: str, dry_run: bool = False):
        from .preview import extract_preview_metadata, launch_terminal_tabs
        try:
            _, _, _, manifest = resolved_store.load(snapshot_id)
            meta = extract_preview_metadata(manifest, snapshot_id)
            return launch_terminal_tabs(meta["terminal_tabs"], dry_run=dry_run)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/api/v1/virtualization/engines")
    def get_virtualization_engines_list():
        from .preview import get_virtualization_engines
        engines = get_virtualization_engines()
        return {"schema": "uncrash.virtualization-engines/v1", "count": len(engines), "engines": engines}

    @app.get("/api/v1/workspaces")
    def get_workspaces():
        from .preview import workspace_manager
        ws_list = workspace_manager.list_workspaces()
        try:
            from twinerd_mcp.targets import TargetRegistry
            reg = TargetRegistry()
            targets = reg.discover_targets()
            for t in targets:
                if t.vnc_port and not any(w["workspace_id"] == t.id for w in ws_list):
                    ws_port = t.vnc_port + 1000
                    ws_list.append({
                        "workspace_id": t.id,
                        "snapshot_id": "twinerd",
                        "name": f"Twinerd: {t.name}",
                        "display": t.details.get("display") or f":{t.vnc_port - 5900}",
                        "rfb_port": t.vnc_port,
                        "ws_port": ws_port,
                        "novnc_url": f"http://127.0.0.1:{ws_port}/vnc.html?autoconnect=true",
                        "tabs_count": 0,
                        "created_at": "",
                        "status": t.status,
                        "source": "twinerd"
                    })
        except Exception:
            pass
        return {"schema": "uncrash.workspaces-list/v1", "count": len(ws_list), "workspaces": ws_list}

    @app.post("/api/v1/snapshots/{snapshot_id}/workspace")
    def post_create_workspace(snapshot_id: str,
                              workspace_id: Optional[str] = None,
                              name: Optional[str] = None,
                              force_new: bool = False,
                              engine: str = "native",
                              port: Optional[int] = None):
        from .preview import extract_preview_metadata, workspace_manager
        try:
            _, _, _, manifest = resolved_store.load(snapshot_id)
            meta = extract_preview_metadata(manifest, snapshot_id)
            ws = workspace_manager.create_or_get_workspace(
                snapshot_id=snapshot_id,
                terminal_tabs=meta["terminal_tabs"],
                workspace_id=workspace_id,
                name=name,
                force_new=force_new,
                engine=engine,
                manifest=manifest,
                port=port
            )
            return ws.to_dict()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/v1/workspaces/{workspace_id}")
    def get_workspace_details(workspace_id: str):
        from .preview import workspace_manager
        ws = workspace_manager.get_workspace(workspace_id)
        if not ws:
            raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found or stopped")
        return ws.to_dict()

    @app.post("/api/v1/workspaces/{workspace_id}/close")
    def post_close_workspace(workspace_id: str):
        from .preview import workspace_manager
        closed = workspace_manager.close_workspace(workspace_id)
        return {"status": "ok" if closed else "not_found", "closed": closed, "workspace_id": workspace_id}

    @app.get("/api/v1/system/gpu")
    def get_system_gpu():
        from .inventory import get_gpu_status
        return get_gpu_status()

    @app.get("/api/v1/system/applications")
    def get_system_applications():
        from .inventory import get_application_matrix
        return get_application_matrix()

    return app


def create_mcp_server(store=None, config=None):
    """Create Model Context Protocol (MCP) server for uncrash."""
    resolved_store, resolved_config = _resolve_default_store(store, config)

    try:
        from mcp.server.mcpserver import MCPServer
        mcp = MCPServer(
            name="uncrash",
            version="0.1.2",
            description="Unified local process recovery, snapshot browser and window management tools"
        )
    except (ImportError, ModuleNotFoundError):
        from mcp.server.fastmcp import FastMCP
        class FastMCPCompat:
            def __init__(self, name: str, version: str = "0.1.2", description: Optional[str] = None):
                self._server = FastMCP(name)
            def tool(self, name: Optional[str] = None, description: Optional[str] = None):
                def decorator(fn):
                    self._server.tool(name=name, description=description)(fn)
                    return fn
                return decorator
            async def list_tools(self):
                return await self._server.list_tools()
            async def call_tool(self, name: str, arguments: dict):
                raw = await self._server.call_tool(name, arguments)
                contents = raw[0] if isinstance(raw, (tuple, list)) and len(raw) > 0 and isinstance(raw[0], list) else raw
                class CallResult:
                    def __init__(self, content): self.content = content
                return CallResult(contents)
            async def run_stdio_async(self):
                return await self._server.run_stdio_async()
            def sse_app(self):
                return self._server.sse_app()
            def streamable_http_app(self):
                return self._server.streamable_http_app()
        mcp = FastMCPCompat(
            name="uncrash",
            version="0.1.2",
            description="Unified local process recovery, snapshot browser and window management tools"
        )

    @mcp.tool(
        name="uncrash_list_gui_apps",
        description="List active user-opened windowed GUI applications (PyCharm, Chrome, Files, etc.) with PIDs and open projects."
    )
    def mcp_list_gui_apps() -> str:
        apps = detected_gui_apps()
        return json.dumps({"count": len(apps), "applications": apps}, ensure_ascii=False, indent=2)

    @mcp.tool(
        name="uncrash_close_gui_app",
        description="Close a whole application process using explicit PID and expected_start; force is opt-in. This is not a single-window close."
    )
    def mcp_close_gui_app(pid: Optional[int] = None, name: Optional[str] = None, force: bool = False, expected_start: Optional[str] = None) -> str:
        res = close_gui_app(pid=pid, name=name, force=force, expected_start=expected_start)
        return json.dumps(res, ensure_ascii=False, indent=2)

    @mcp.tool(
        name="uncrash_get_jetbrains_state",
        description="Inspect running JetBrains IDE instances (PyCharm, WebStorm) and their open projects."
    )
    def mcp_jetbrains_state() -> str:
        state = jetbrains_state()
        return json.dumps(state, ensure_ascii=False, indent=2)

    @mcp.tool(
        name="uncrash_get_desktop_inventory",
        description="Discover available desktop application launchers (.desktop files) and CLI commands."
    )
    def mcp_desktop_inventory() -> str:
        inventory = desktop_inventory()
        return json.dumps({"schema": "uncrash.desktop-inventory/v1", "launchers": inventory}, ensure_ascii=False, indent=2)

    @mcp.tool(
        name="uncrash_list_snapshots",
        description="List all available recovery snapshots with timestamps, profile and terminal tab counts."
    )
    def mcp_list_snapshots() -> str:
        from .preview import extract_preview_metadata
        snapshot_ids = resolved_store.list()
        items = []
        for sid in reversed(snapshot_ids):
            try:
                _, _, _, manifest = resolved_store.load(sid)
                meta = extract_preview_metadata(manifest, sid)
                items.append({
                    "id": sid,
                    "created_at": meta.get("created_at"),
                    "profiles": meta.get("profiles", []),
                    "terminal_tabs_count": meta.get("terminal_tabs_count", 0),
                    "gui_projects_count": meta.get("gui_projects_count", 0)
                })
            except Exception:
                items.append({"id": sid, "error": "unreadable"})
        return json.dumps({"count": len(items), "snapshots": items}, ensure_ascii=False, indent=2)

    @mcp.tool(
        name="uncrash_preview_snapshot",
        description="Extract terminal tabs, GUI applications and launch scripts for a specific snapshot."
    )
    def mcp_preview_snapshot(snapshot_id: str = "latest") -> str:
        from .preview import extract_preview_metadata
        _, _, _, manifest = resolved_store.load(snapshot_id)
        meta = extract_preview_metadata(manifest, snapshot_id)
        return json.dumps(meta, ensure_ascii=False, indent=2)

    @mcp.tool(
        name="uncrash_launch_terminal_tabs",
        description="Launch recorded terminal tabs from a snapshot in the system terminal (gnome-terminal)."
    )
    def mcp_launch_terminal_tabs(snapshot_id: str = "latest", dry_run: bool = False) -> str:
        from .preview import extract_preview_metadata, launch_terminal_tabs
        _, _, _, manifest = resolved_store.load(snapshot_id)
        meta = extract_preview_metadata(manifest, snapshot_id)
        res = launch_terminal_tabs(meta["terminal_tabs"], dry_run=dry_run)
        return json.dumps(res, ensure_ascii=False, indent=2)

    @mcp.tool(
        name="uncrash_list_virtualization_engines",
        description="List all available virtualization and workspace engines (Twinerd, Kasm, CloneBox VM, CloneBox Container, Pelorus Twin)."
    )
    def mcp_list_virtualization_engines() -> str:
        from .preview import get_virtualization_engines
        return json.dumps(get_virtualization_engines(), ensure_ascii=False, indent=2)

    @mcp.tool(
        name="uncrash_list_workspaces",
        description="List active isolated noVNC virtual desktop workspaces running snapshot sessions via Twinerd."
    )
    def mcp_list_workspaces() -> str:
        from .preview import workspace_manager
        workspaces = workspace_manager.list_workspaces()
        return json.dumps({"count": len(workspaces), "workspaces": workspaces}, ensure_ascii=False, indent=2)

    @mcp.tool(
        name="uncrash_create_workspace",
        description="Launch a dedicated noVNC workspace running all recorded terminal tabs for a specific snapshot."
    )
    def mcp_create_workspace(snapshot_id: str = "latest", workspace_id: Optional[str] = None, force_new: bool = False, engine: str = "native") -> str:
        from .preview import extract_preview_metadata, workspace_manager
        _, _, _, manifest = resolved_store.load(snapshot_id)
        meta = extract_preview_metadata(manifest, snapshot_id)
        ws = workspace_manager.create_or_get_workspace(
            snapshot_id=snapshot_id,
            terminal_tabs=meta["terminal_tabs"],
            workspace_id=workspace_id,
            force_new=force_new,
            engine=engine,
            manifest=manifest
        )
        return json.dumps(ws.to_dict(), ensure_ascii=False, indent=2)

    @mcp.tool(
        name="uncrash_close_workspace",
        description="Close an active noVNC virtual desktop workspace and stop all its processes."
    )
    def mcp_close_workspace(workspace_id: str) -> str:
        from .preview import workspace_manager
        closed = workspace_manager.close_workspace(workspace_id)
        return json.dumps({"status": "ok" if closed else "not_found", "closed": closed, "workspace_id": workspace_id}, ensure_ascii=False, indent=2)

    @mcp.tool(
        name="uncrash_get_gpu_status",
        description="Inspect host GPU hardware (NVIDIA GeForce/RTX/CUDA, VRAM, temperature, driver) and GPU utilities."
    )
    def mcp_get_gpu_status() -> str:
        from .inventory import get_gpu_status
        return json.dumps(get_gpu_status(), ensure_ascii=False, indent=2)

    @mcp.tool(
        name="uncrash_get_installed_applications",
        description="Discover and classify all installed PC applications (NVIDIA, AI agents, IDEs, browsers, terminals, virtualization) with recovery profiles."
    )
    def mcp_get_installed_applications() -> str:
        from .inventory import get_application_matrix
        return json.dumps(get_application_matrix(), ensure_ascii=False, indent=2)

    return mcp
