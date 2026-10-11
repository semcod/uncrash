# Ticket 027: Render snapshot dashboard data as inert text

- **ID**: ticket-027
- **Owner**: agent:codex-root
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: user requested continued backlog repairs, tests and protected publication through Willman. PLF-004 accepts this bounded dashboard follow-up. Snapshot IDs, terminal metadata, GUI paths, launch scripts, recorded processes and GPU fields currently enter HTML; IDs also enter inline JavaScript. Render these as text and preserve exact quoted/Unicode action arguments and copied scripts. Other dashboard panels, real application launches, dependencies, protected CI and deployment remain outside this ticket.

## Acceptance criteria

- [x] AC-01: Executable dashboard regression cases prevent HTML/attribute/script injection and preserve Unicode text and copied scripts.
- [x] AC-02: Normal list/details and action behavior remain compatible with existing API/recovery tests.
- [x] AC-03: Full source suite, mandatory four-window X11 and managed governance pass through Willman.
- [ ] AC-04: Frozen exact-head OneDev and independent Validator produce trusted protected merge evidence.

## Validation

Executable pre-fix baseline: 26 failed, 2 passed. Focused dashboard/API/recovery suite: 62 passed, 1 optional service skip. Added empty-state and provider compatibility coverage for the full suite. Tests execute the shipped JavaScript in existing Node, inspect generated markup and invoke button callbacks with stubbed launches; no real applications started.

Full source suite: 413 passed, 9 optional runtime/service skips and 8 passed subtests; all 33 dashboard regressions and the mandatory four-window X11 case pass. Full suite runs managed governance with zero findings. Fresh exact-head OneDev and independent Validator remain required for AC-04.
