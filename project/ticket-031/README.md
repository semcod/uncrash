# Ticket 031: Fix workspace copy URL handler and align digit shortcuts with filtered list

- **ID**: ticket-031
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-11

## Goal and scope

Address PLF-009 and PLF-010 in `src/uncrash/web_ui.py`:
1. **PLF-009**: Decouple `copyWorkspaceUrl` from inline HTML `onclick` interpolation (`onclick="copyWorkspaceUrl('${ws.novnc_url}')"`). Bind the copy handler using DOM event listeners (`addEventListener` / data attributes) so URLs containing single quotes, apostrophes, or special characters copy accurately without script execution risks.
2. **PLF-010**: Align 1-9 digit keyboard shortcuts with visible filtered workspaces rather than the raw `activeWorkspaces` array, ensuring pressing key `1` always activates the item labeled with shortcut badge `1`.
3. Add unit test coverage in `tests/test_web_ui.py` covering:
   - Copy handler with exact URLs containing quotes and special parameters.
   - Filtered digit keydown selection ensuring visible item is selected.
4. Verify all tests pass and `./project/governance-check.sh` succeeds.

## Acceptance criteria

- [x] AC-01: Copy noVNC link button does not evaluate URL inside inline `onclick` string; uses safe data attribute / event binding.
- [x] AC-02: Pressing number key 1-9 selects the corresponding visible filtered workspace matching the displayed badge.
- [x] AC-03: Regression tests verify copy URL handling and filtered shortcut activation.
- [x] AC-04: Full test suite passes without regressions.
- [x] AC-05: `./project/governance-check.sh` passes cleanly with 0 errors and 0 warnings.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
