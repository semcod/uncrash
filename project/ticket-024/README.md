# Ticket 024: Bound noVNC preview total HTTP deadline

- **ID**: ticket-024
- **Owner**: agent:codex-root
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-11

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: user requested continuing backlog work and PR repairs through Willman, with tests and protected publication. Resume PLF-007 as a bounded follow-up because original ticket-011 / PR #9 is merged. Fresh probes fail on current main for both slow headers and body. Own APX server, its tests, and a root collection bridge. The deployed protected OneDev command runs only `tests`, so the bridge makes the APX regressions mandatory there.

## Acceptance criteria

- [x] AC-01: Slow HTTP headers and body share the 0.2 second monotonic budget.
- [x] AC-02: Existing valid preview and transfer safety behavior passes.
- [x] AC-03: Willman executes regression verification; the standard root product suite includes APX, and managed governance passes.
- [ ] AC-04: Protected independent exact-head review and merge completes.

## Validation

Willman actual-source APX: 21 passed and 8 subtests. Standard root product collection: 348 passed, 9 optional skips and 8 subtests, including APX and the required four-windows/one-process X11 fixture. Managed governance: zero errors/warnings. Source is ready for exact-head OneDev and independent Validator publication; AC-04 remains pending the trusted merge receipt.
