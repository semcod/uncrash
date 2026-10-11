# Ticket 023: Diagnostic metadata parity and bounded process reads

- **ID**: ticket-023
- **Owner**: agent:codex-root
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Authorization**: SESSION_EXECUTION_AUTHORIZATION; user requested continued tests/fixes and previously authorized protected publication.

## Goal and scope

Fix four reproduced native provider metadata discrepancies in merged ticket-021 and bound process metadata reads in ticket-022. Source and tests only in the declared three paths; no IDE signals or restarts, no database recovery or protected CI edits.

## Acceptance criteria

- [x] AC-01: BOM, UTF16, unsupported JSON and first-line budget match Python.
- [x] AC-02: FIFO, links and oversized process metadata refuse promptly in both paths.
- [x] AC-03: Normal output, identity and privacy remain unchanged, with safe cached-worker fallback.
- [x] AC-04: Full tests including real X11 and governance pass; exact-head protected publication.
