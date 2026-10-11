# Ticket 015: Preserve session databases and verify salvage outcomes

- **ID**: ticket-015
- **Owner**: agent:codex-root
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-11

## Goal and scope

Fix the four reproduced failures from merged ticket-010 / PR13 in the three
owned source/test paths. Existing session authorization: SESSION_EXECUTION_AUTHORIZATION
from repeated user instructions to continue, handle backlog, test and merge.
Delivery includes protected publication and merge. No real session database
repair, IDE restart, peer checkout removal or protected policy modification.
Maximum active session: 120 minutes.

## Acceptance criteria

- [ ] AC-01: Recovery preserves source and existing destination, uses private exclusive staging, verifies SQLite restoration and never reports completion or publishes output after failure.
- [ ] AC-02: Busy/inaccessible SQLite inputs are unavailable/degraded rather than corrupted; bounded scans find recent panic signatures in large logs.
- [ ] AC-03: Focused regressions, full product tests, governance and independent exact-head protected publication pass.

## Evidence boundary

The original 229-test suite passed, but four additional fixture-only probes
failed at source 0769dc8e2d95ec76d48107e97fb19ccefe7e2329. Immutable external
receipts retain their results and PR13 merge observation. This follow-up owns
only the allocator-declared paths; ticket-008 dirty data remains preserved.
