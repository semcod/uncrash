# Ticket 045: bounded fresh snapshot retries

- **ID**: ticket-045
- **Owner**: agent:codex-root
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION

SESSION_EXECUTION_AUTHORIZATION: user requests continue, test and protected merge. Implements accepted PLF-017 reliability follow-up after ticket044 merged. Sole source writer root in canonical checkout with protected lease; no IDE/provider actions.

Live PyCharm LocalHistory736-byte index changed during capture; previous snapshot survived but next complete copy was10minutes later. Retry only typed verified source-change failures from a fully cleaned failed transaction. Re-plan the entire snapshot; never publish parts from an earlier attempt. Configurable attempt count and shared additional-retry deadline belong in Env DSL. Source supports old deployments with one attempt; a disjoint governance-owned template task enables explicit defaults after this source merge. Preserve no-follow, privacy, byte limits, encrypted and SQLite behavior.

- [x] AC-01: Real compiled Rust transient mutation recovers with fresh multi-file content; sustained mutation remains bounded and preserves previous complete snapshot.
- [x] AC-02: Unsafe, budget, SQLite/unknown and legacy diagnostics are not retried; deadline covers retry lock/scanning/worker/publication, failed staging remains private and removed.
- [ ] AC-03: Env DSL validates limits and honors canonical SSOT; regression/governance checks pass; trusted exact-head publication required.

Validation: wider source suite136PASS/1optional installed-serviceSKIP before final deadline propagation; final67retry/diagnostic/configuration regressions PASS including Python stable-read mutation and expired SQLite/compiler boundaries. Complete regression running on digest-bound final source. The first test fixture was corrected to acquire contention only after the original transaction released its lock; stale run was terminated and superseded, not reported PASS.

Final complete regression555PASS/9optionalSKIP/8subtests in321.70seconds on final digest-bound source; fresh private disk-backed TMPDIR resolved the prior environmental Errno28 failure without changing source or deleting unrelated data. Managed governance PASS0errors0warnings. AC-03 local validation complete; trusted exact-head review/merge remains pending.
