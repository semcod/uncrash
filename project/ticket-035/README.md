# Ticket 035: Optimize workspace tabs bar layout and compact display without scrolling

- **ID**: ticket-035
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-12

## Goal and scope

Optimize the workspaces / machines tabs bar (`#workspacesBar`, `#workspacesChips`) in the Uncrash dashboard (`src/uncrash/web_ui.py`):
1. **Compact & Non-scrolling Layout (Wrap Mode by Default)**:
   - Provide a responsive layout where `#workspacesChips` can wrap cleanly (`flex-wrap: wrap`) without forcing horizontal scrolling across all active machines.
   - Include a layout toggle (`⤸ Zawijaj` vs `↔ 1 wiersz`) persisted in localStorage (`uncrash_ws_wrap_mode`).
2. **Compact Chip Design & De-duplication**:
   - Streamline `.workspace-chip` to be compact and readable.
   - Remove redundant backend/engine string repetitions (such as `[Twinerd NATIVE]`) from the chip title while retaining full context in tooltips.
   - Distinct, styled badges for engine and tabs count (`(${tabsInfo})`).
3. **Keyboard & Usability Optimizations**:
   - Add keyboard shortcut `0` for the 10th workspace (supporting instant 1-0 switching across all 10 running machines).
   - Display a workspace counter badge in the toolbar showing active/matching counts.
4. **Test coverage & Governance**:
   - Verify all unit tests pass in `tests/test_web_ui.py` with Node VM harnesses.
   - Pass `./project/governance-check.sh` with 0 errors and 0 warnings.

## Acceptance criteria

- [x] AC-01: `#workspacesChips` supports wrapping layout (`flex-wrap: wrap`), eliminating forced horizontal scrolling when displaying 10+ workspaces.
- [x] AC-02: Workspace chip display is streamlined and compact, stripping redundant backend markers from the label while keeping complete metadata.
- [x] AC-03: Layout toggle allows switching between wrapping and single-row scrolling, with preference persisted in localStorage.
- [x] AC-04: Keyboard navigation supports switching up to 10 workspaces using keys 1-9 and 0.
- [x] AC-05: Unit tests in `tests/test_web_ui.py` verify compact rendering, wrap mode toggle, and literal text preservation.
- [x] AC-06: `./project/governance-check.sh` passes cleanly with 0 errors and 0 warnings.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
