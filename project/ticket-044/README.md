# Ticket 044: distinguish native capture failures

- **ID**: ticket-044
- **Owner**: agent:codex-root
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION

SESSION_EXECUTION_AUTHORIZATION: user requests continued fixes, tests and protected publication. PLF-002 records this accepted diagnostic follow-up. Prior source tickets are merged and released; the scoped allocator admitted this canonical checkout while preserving primary IDE changes.

A refused 736-byte PyCharm LocalHistory index was reported as UNCRASH-CAPTURE-BUDGET because the worker adapter described every refusal as unstable/unsafe/oversized. Preserve fail-closed capture and previous snapshots; report the observed reason without private paths/content.

- [x] AC-01: Real worker source changes and file budget failures reach distinct existing error codes.
- [x] AC-02: Private bounded reason metadata contains no source paths, secrets or arbitrary error text; old or malformed worker diagnostics remain generic native failures.
- [ ] AC-03: Regression and managed governance checks pass; publication uses exact-head trusted local validation.

Validation: focused real-worker and snapshot recovery suite 84 passed / 1 optional installed-service skip. Managed governance gate passed 0 errors / 0 warnings. Full product regression and protected publication remain pending.

Full validation: 533 passed / 9 optional platform or installed-service skips in 188.89 seconds. Native refusal tests execute the compiled worker, preserve the last complete snapshot, and validate private diagnostic records. Canonical governance PASS. Exact-head independent local review/merge remains pending; keep IN_PROGRESS / PUBLICATION until an external protected terminal receipt.
