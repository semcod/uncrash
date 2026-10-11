# Ticket 032: Clear stale workspace shortcuts after empty refresh

- **ID**: ticket-032
- **Owner**: agent:codex-root
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: the user requested continued backlog repairs, tests and protected publication through Willman. PLF-010 accepts this remaining shortcut defect. After all active workspaces disappear, the bar is hidden but digit keys still select a stale workspace because visibleWorkspaces survives the empty-list early return. Clear that list at each render and add an executable disappearance regression. Preserve normal filtered navigation and input/modifier guards. Real application operations, dependencies, protected policy and deployment are outside this ticket.

## Acceptance criteria

- [x] AC-01: Rendering an empty refreshed workspace inventory clears digit targets; digit 1 neither selects a stale workspace nor consumes the event.
- [x] AC-02: Executable regression covers nonempty inventory followed by empty inventory, with both unfiltered and filtered views; existing copy and shortcut tests still pass.
- [x] AC-03: Full source suite, mandatory four-window X11 and managed governance pass through Willman.
- [ ] AC-04: Frozen exact-head OneDev and independent Validator produce trusted protected merge evidence.

## Tracking boundary

PR31 head ebb42c6f1e86986cffbb2af65877052aadf002e9 is the source of the observed defect; accepted base is main 276a8d20a52656f005220881425456c31e9a7230. Pre-fix independent execution: 25 passed, 1 failed. One-line external candidate: 26 passed. Ticket027 publication remains blocked by POST_APPROVAL_RECEIPT_MISSING and is preserved in the external recovery record; this ticket does not claim to reconcile historical review.

## Validation

Pre-fix regression: 2 failed, 2 passed. After the fix, dashboard 56 passed; full source suite 436 passed, 9 optional runtime/service skips and 8 passed subtests. Mandatory real four-window X11 test passed on an owned desktop. Managed governance: 0 errors, 0 warnings. All commands ran through Willman. No user applications were opened or closed. Independent exact-head OneDev and Validator remain required for AC-04.
