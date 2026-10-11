# Ticket 025: Bound recovery TAR header processing

- **ID**: ticket-025
- **Owner**: agent:codex-root
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: user requested continued backlog/Issue/PR repair through Willman, with tests and protected merging. This bounded PLF-004 follow-up fixes a confirmed import resource-exhaustion defect. A 512-byte PAX or GNU long-name header requests a 1 GiB read before existing metadata checks. The safe baseline probe prevented that allocation and left the destination untouched.

Own only portable recovery import and its focused regression tests. Preserve actual IDEs, saved user sessions, SSH transfer, deployed CI, and the unresolved Willmux ticket-271 approval/check criterion.

## Acceptance criteria

- [x] AC-01: Reject unsupported and oversized raw TAR headers before extension-body reads or destination creation.
- [x] AC-02: Valid plaintext/encrypted native bundle roundtrips and existing tamper checks pass.
- [x] AC-03: Willman executes focused/full source checks; required X11 and managed governance pass.
- [ ] AC-04: Exact-head OneDev and independent Validator produce trusted protected merge evidence.

## Validation

Willman guarded baseline: 10 regressions fail and 6 pass without allocating the declared 1 GiB body. The corrected member-processing hook passes the full source suite: 364 pass, 9 optional skips, 8 subtests pass; the required four-window X11 test and all 16 new header/compatibility cases pass. Existing plaintext/encrypted native restoration and tamper checks pass. The initial OneDev run exposed a Python 3.13.15 difference in TAR header parsing; validation now uses the common pre-body processing hook. Isolated qualification on the deployed CI image with Python 3.13.15 passes all 25 bundle import/restoration cases. Fresh exact-head OneDev and independent Validator publication remain required for AC-04.
