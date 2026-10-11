# Ticket 014: Require executed X11 window preservation validation

- **ID**: ticket-014
- **Owner**: agent:codex-root
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-11

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: the user requested continued testing, fixes and protected merge, and explicitly confirmed the other writer had finished and authorized takeover. Parent PR10 merged at 24e00f9015da6c39eaf8ba4872db2ace7d286d0a while the tested correction d062c780ad8ba963ea4424d7545ed246f9f78b3a remained local. An external actor removed its canonical checkout and branch. Preserve that unique commit through a secret-scanned external snapshot, bundle and recovery ref. The managed allocator admitted this exact free source scope on current main b69af09385fa9c43e11e456d330669fd3ebf4a50. This ticket delivers only the remaining fixture correction; do not rewrite the merged PR or reopen its carrier.

Missing Xlib, Xvfb or Openbox currently makes the safety fixture return a successful test without any actual windows. Require these dependencies and prove missing dependencies fail before launching processes. Preserve the actual owned X11 graceful-close request and all three peer-window assertions. Runtime code remains inherited from the parent. Approved OneDev scratch cleanup and protected Uncrash registry have been deployed with external exact-version receipts. After protected publication, refresh only the previously authorized versioned user CLI from exact merged source, preserving its old launcher and daemon.

## Acceptance criteria

- [x] AC-01: Missing dependencies fail before subprocess creation; the actual close-one-of-four fixture and complete product suite pass.
- [ ] AC-02: Managed governance, current-base native CI and trusted exact-head review/merge publish the material fixture correction; exact merged CLI source is available under existing local-install authority.

Validation on the accepted current base: 219 tests passed with 9 unrelated opt-in skips in 31.16 seconds, including the actual X11 fixture and all three missing-dependency failures. Managed governance and diff formatting passed. Current-base native OneDev, independent exact-head merge and the authorized merged-source CLI installation remain pending.

Publication preflight observed authorized upstream PR11 merge to 49e1cbec2cbc349cb39042c659490bd2444ae20b before this branch was pushed. Revalidated the same free window-fixture scope and rebased the unpushed material commit onto that exact current base, preserving upstream preview implementation. Refresh complete tests and native/independent review for the rebuilt head.

Current-base validation: 224 tests passed with the same 9 unrelated opt-in skips in 36.14 seconds, including newly integrated preview tests. Managed governance passed against exact base 49e1cbec2cbc349cb39042c659490bd2444ae20b. Fold the updated base/validation carriers atomically into the unpushed material commit, then freeze its resulting head through native review and merge.

Final base reconciliation: upstream PR9 merged to a2887cbcc2cf154d5a39c595cd48dedc28bd667c before this branch was published. Its delta does not change any src/uncrash or tests path, so the product test tree is unchanged. Rebase the same fixture correction, retain the 224-test evidence and require the publisher/native gates to validate this resulting exact head. No upstream PR remains open at observation.
