# Ticket 030: Repair workspace tab title escaping and add negative controls

- **ID**: ticket-030
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-11

## Goal and scope

Repair unsafe HTML rendering regression in workspace preview tab rendering (`src/uncrash/web_ui.py`) identified in PLF-008:
- Ensure terminal tab display names in `renderWorkspacePreview` are safely escaped via `escapeHtml(tabTitle)`.
- Add negative control unit tests in `tests/test_web_ui.py` across `name`, `title`, and `provider` fields, verifying markup (`<img src=x onerror=...>`, `<svg onload=...>`), quotes, punctuation, and Unicode are rendered strictly as text and do not introduce HTML tags or event attributes.
- Ensure all existing and new unit tests pass and `./project/governance-check.sh` succeeds cleanly.

## Acceptance criteria

- [x] AC-01: Terminal tab display name in `renderWorkspacePreview` is wrapped in `escapeHtml(...)`.
- [x] AC-02: Negative control tests parametrized across `name`, `title`, and `provider` verify tab titles are preserved as text and do not render unsafe elements (`img`, `svg`) or event handlers (`onerror`, `onload`).
- [x] AC-03: Full test suite passes without regressions.
- [x] AC-04: `./project/governance-check.sh` passes cleanly with 0 errors and 0 warnings.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
