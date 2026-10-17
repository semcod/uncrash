# Ticket 047: Remediate PERF-AUDIT findings across preview, recovery, runtime, and diagnostics

- **ID**: ticket-047
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-17

SESSION_EXECUTION_AUTHORIZATION: user requests remediation of all PERF-AUDIT-* findings and publication of uncrash via goal -a.

## Goal and scope

Resolve all 13 `PERF-AUDIT-*` findings across `src/uncrash/{diagnostics,preview,recovery,runtime}.py`:
- Close `sqlite3.connect` handles via `contextlib.closing` in `src/uncrash/preview.py` (`PERF-AUDIT-SQLITE-002`).
- Extract single-target subprocess helpers in `src/uncrash/preview.py`, `src/uncrash/recovery.py`, and `src/uncrash/runtime.py` (`PERF-AUDIT-SUBPROC-001`).
- Eliminate unused default keyword arguments across `src/uncrash/{diagnostics,preview,recovery,runtime}.py` while preserving zero-arg monkeypatch compatibility for `_find_free_display` (`PERF-AUDIT-KWARG-001`).

## Acceptance criteria

- [x] AC-01: `audit_repository` reports 0 `PERF-AUDIT-*` findings across `src/uncrash/{diagnostics,preview,recovery,runtime}.py`.
- [x] AC-02: Full regression suite (`555 passed, 9 skipped`) and `./project/governance-check.sh` (`GOV-PASS`) pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
