# Ticket 034: Add app launch to workspace and grid-table view toggle to applications catalog

- **ID**: ticket-034
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-12

## Goal and scope

Enhance the Applications Catalog modal (`modal=apps`) in Uncrash dashboard (`src/uncrash/web_ui.py`):
1. **Target machine / workspace selector & launch action**:
   - Provide the ability to add and launch an application directly from the catalog into a chosen active workspace machine, or spawn a new workspace for that application.
   - Support action buttons per application (`🚀 Uruchom w workspace`, `📋 Kopiuj polecenie`).
2. **Switchable Display Modes (Panels / Table)**:
   - Provide a view mode toggle between **Panels (Grid)** (`#appsGrid` / `.app-card`) and **Table** (`.apps-table`).
   - The table view organizes columns: Application (Icon, Name, Category), Recovery Profile status, Executable CLI command, Desktop file path, and Action buttons.
3. **Backend API support**:
   - Add endpoint `POST /api/v1/workspaces/{workspace_id}/launch-app` and support launching application commands inside workspaces.
4. **Test coverage & Governance**:
   - Add tests in `tests/test_web_ui.py` and `tests/test_api.py` covering view mode toggling, table vs grid rendering, and app launch actions.
   - Verify `./project/governance-check.sh` passes cleanly.

## Acceptance criteria

- [x] AC-01: Applications catalog modal provides a target workspace selector and per-app action to launch/add the application to a new or chosen workspace machine.
- [x] AC-02: View mode toggle allows switching between Grid (cards) and Table view with action options.
- [x] AC-03: `POST /api/v1/workspaces/{workspace_id}/launch-app` endpoint allows launching an app command in an existing workspace session.
- [x] AC-04: Unit tests in `tests/test_web_ui.py` and `tests/test_api.py` verify view mode switching, table rendering, and app launch action handling.
- [x] AC-05: `./project/governance-check.sh` passes cleanly with 0 errors and 0 warnings.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
