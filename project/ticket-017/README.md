# Ticket 017: SQLite recovery cleanup and private failure diagnostics

- **ID**: ticket-017
- **Owner**: agent:codex-root
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-11

## Scope and authority

SESSION_EXECUTION_AUTHORIZATION: user requested continuing fixes, tests and merge,
and explicitly handed over ticket-015. PR14 merged while the last source changes
were dirty; its canonical checkout was removed by another operator. This bounded
follow-up restores the remaining delta from the digest-verified external snapshot.
Only recovery source and its regression tests are owned. No user database repair,
IDE restart, other-worktree cleanup or governance changes. Maximum 120 active minutes.

## Acceptance criteria

- [x] AC-01: Failed SQLite imports close both handles before temporary cleanup and return no private exception details; preserve source and do not publish output.
- [ ] AC-02: Full product tests, governance, native OneDev verification and independent protected exact-head review/publication pass.

## Validation

Full product suite: 245 passed, 9 optional integration tests skipped. Mandatory
owned X11 fixture closes one of four windows sharing a process and preserves
the other three. Managed governance at exact accepted base: PASS, zero findings.
Protected native verification and independent publication remain pending.
