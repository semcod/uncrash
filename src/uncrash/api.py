"""Universal multi-protocol API conforming to wellmanifest/nl-api-llm and wellmanifest/skills.

Dispatches operations across Shell CLI, REST HTTP (FastAPI) and MCP (Model Context Protocol).
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from pathlib import Path

from .recovery import detected_gui_apps, close_gui_app, jetbrains_state
from .inventory import desktop_inventory


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
    }
]


def create_fastapi_app():
    """Create FastAPI REST application for uncrash."""
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel

    app = FastAPI(
        title="Uncrash Multi-Protocol API",
        version="0.1.2",
        description="Unified REST and MCP API conforming to wellmanifest/nl-api-llm"
    )

    class CloseAppRequest(BaseModel):
        pid: Optional[int] = None
        name: Optional[str] = None
        force: bool = False
        expected_start: Optional[str] = None

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

    return app


def create_mcp_server():
    """Create Model Context Protocol (MCP) server for uncrash."""
    try:
        from mcp.server.mcpserver import MCPServer
        mcp = MCPServer(
            name="uncrash",
            version="0.1.2",
            description="Unified local process recovery and window management tools conforming to wellmanifest/skills"
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
            version="0.1.1",
            description="Unified local process recovery and window management tools conforming to wellmanifest/skills"
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

    return mcp

