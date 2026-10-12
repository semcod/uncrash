# Ticket 041: Support pidfd signaling when Python lacks the wrapper

- **ID**: ticket-041
- **Owner**: agent:codex-root
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Accepted base**: `e64534a01005345eccc64ccc368a584ae3a33284`

SESSION_EXECUTION_AUTHORIZATION: The user explicitly requested continued repair, testing, and protected merging. This ticket addresses the full-suite failures reproduced on Uncrash main: Python 3.11–3.14 in the available Linux environment do not expose `signal.pidfd_send_signal`, so process stop paths fail and tests cannot exercise safe pidfd signaling. Implement a Linux pidfd syscall fallback with a strictly bounded architecture allowlist and fail closed elsewhere. Keep PID identity checks and descriptor pinning. No process may be signaled by a numeric PID fallback. Publication is authorized only through exact-head local OneDev and the independent Validator; never merge directly.

- [x] AC-01: `Launcher.stop` and explicit GUI process close use a safe pidfd signal helper when Python lacks its wrapper, with no PID-only fallback and fail-closed behavior on unsupported systems.
- [x] AC-02: Tests cover native wrapper, syscall fallback, unsupported architecture and syscall errors, stale PID identity, and TERM/KILL behavior without signaling unrelated processes.
- [x] AC-03: Focused and full pytest suites and managed governance pass on the accepted current base; report platform-specific skips separately.
- [ ] AC-04: Exact-head protected review and merge complete through OneDev and the independent Validator after all gates pass.

Scope is limited to the declared intent paths. Preserve unrelated ticket branches, generated caches and worktrees.
