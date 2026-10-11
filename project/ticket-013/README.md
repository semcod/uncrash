# Ticket 013: Twinerd multi-instance workspace application recovery

- **ID**: ticket-013
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-10

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: user requested implementing full prevention of multi-window termination/hang errors and enabling restoration of applications (such as PyCharm projects) in Twinerd/Minis instances, each in its own dedicated, isolated workspace with independent virtual X11 display and noVNC access.

Extend `src/uncrash/preview.py` to allow `VirtualPreviewDesktop` and `WorkspaceManager` to launch and isolate GUI applications (such as JetBrains PyCharm projects) per workspace with private JVM/config directories, independent display slots, and noVNC access. Provide automated recovery and multi-instance workspace dispatch, avoiding JVM cross-talk, coroutine starvation or host hangs. Support remote Minis host dispatch (`tom@minis`).

## Acceptance criteria

- [x] AC-01: `VirtualPreviewDesktop` and `WorkspaceManager` support launching GUI applications (including PyCharm projects) with isolated sandboxed configuration (`-Didea.config.path`, `-Didea.system.path`, `-Didea.plugins.path`, etc.) preventing single-instance conflicts or host display leakage.
- [x] AC-02: Support restoring multiple applications/projects concurrently, each in a separate, isolated workspace on its own display (`:150+`) and noVNC WebSocket port (`6080+`).
- [x] AC-03: Provide helper functions `restore_application_in_workspace`, `restore_project_in_workspace`, and `restore_all_projects_isolated` with engine selection (`native`, `kasm`, `clonebox`, `pelorus`) and target host support (`local` or `minis`).
- [x] AC-04: Comprehensive automated tests in `tests/test_novnc.py` verifying isolated workspace launch, multi-instance separation, parameter validation, and clean teardown without touching the host desktop or peer workspaces.

## Validation results

- Full test suite passed: 88 passed, 9 skipped across `tests/`.
- 5 new multi-instance workspace isolation tests in `tests/test_novnc.py` passed:
  1. `test_setup_jetbrains_sandbox_creates_isolated_vmoptions`: verified isolated `config`, `system`, `plugins`, `log` directories and custom `idea.paths.selector`.
  2. `test_restore_project_in_workspace_creates_isolated_session`: verified single-project restoration into an isolated session with its own noVNC URL and display.
  3. `test_restore_all_projects_isolated_allocates_distinct_workspaces_and_displays`: verified concurrent restoration of 4 distinct projects (`uncrash`, `selective-tutor`, `fixos`, `maskservice`) into 4 separate workspaces on independent displays and ports without collision.
  4. `test_restore_application_in_workspace_creates_minis_transfer`: verified remote Minis staging manifest creation (`minis_transfer.json`).
  5. `test_workspace_session_serialization_and_cleanup`: verified workspace serialization, active state tracking, and clean process termination.
- Managed governance gate passed with `GOV-PASS: passed (0 errors, 0 warnings)`.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.

