# Ticket 026: Keep snapshot terminal previews separate from unverified agents

- **ID**: ticket-026
- **Owner**: agent:codex-root
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: user requested continued backlog repair, tests and protected publication through Willman. This bounded PLF-004 follow-up preserves the matching-session PLF-002 requirement. Snapshot provider/cwd records have unresolved conversation bindings, yet previews currently generate `codex resume --last`, `agy --continue` or start a new Claude session. Native per-tab shell interpolation also treats recorded cwd/banner text as shell syntax.

Open plain shells in the recorded directories and preserve provider labels. Rebuild terminal launch arguments rather than executing cached provider commands/scripts. Quote native tab cwd and banner data. Preserve actual IDEs/conversations, independent exact-ID recovery, protected CI and broader integration scope.

## Acceptance criteria

- [x] AC-01: Guarded execution tests reject inferred provider launches and shell interpolation while preserving recorded cwd/text.
- [x] AC-02: Existing preview, REST/MCP and noVNC tests pass.
- [x] AC-03: Full source suite, mandatory four-window X11 and managed governance pass through Willman.
- [ ] AC-04: Frozen exact-head OneDev and independent Validator produce trusted protected merge evidence.

## Validation

Willman safe synthetic baseline: 15 failed, 1 passed; no actual agents/terminals/desktops launched. Corrected focused preview/API/noVNC suite: 55 passed, 3 optional skips. Full source suite: 380 passed, 9 optional skips and 8 passed subtests; all 16 new execution regressions and the mandatory four-window X11 case passed. Managed governance passes with zero findings. Fresh exact-head OneDev and independent Validator publication remain required for AC-04.
