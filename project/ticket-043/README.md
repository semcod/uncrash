# Ticket 043: Require an installed runtime before service installation

- **ID**: ticket-043
- **Owner**: agent:codex-root
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Accepted base**: `39f3261f801da535e603a6a2af2eea79535adfe1`
- **Planfile request**: PLF-011

SESSION_EXECUTION_AUTHORIZATION: The user requests continued implementation, testing and protected merging. Prevent the reproduced outage caused by installing uncrash.service from a borrowed editable interpreter that referenced a removed worktree. Validate an installed non-editable package in the selected interpreter independently of cwd/PYTHONPATH and reject linked-worktree runtimes before state/config/unit/systemctl effects. Preserve valid wheel installations, systemd escaping and canonical .env selection. New profile configuration must not duplicate operational defaults from the typed settings registry. No new dependency, live service restart or deployment-policy change. Publication only through exact-head OneDev and the independent protected Validator.

- [x] AC-01: A bounded isolated import/installed-distribution probe rejects missing, source-only, editable and linked-worktree runtimes before installation effects and hides private failure detail.
- [x] AC-02: Real installed-wheel and editable/missing/source-only regression fixtures verify acceptance/rejection; CLI fixtures preserve existing files on refusal and prove .env propagation and profile-only initialization.
- [x] AC-03: Focused and full pytest, managed governance and installed-artifact checks pass; optional integrations are reported separately.
- [ ] AC-04: Frozen exact head passes OneDev and independent protected review/merge; finish the external delivery ledger and exact-checkout cleanup.

Session bound: 120 active minutes. Scope: declared source/test paths and ticket carriers. Service operations in tests are simulated; use only fixture-owned runtimes and data.
