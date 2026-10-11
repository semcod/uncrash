# Ticket 020: Restore native diagnostics safety and Python parity

- **ID**: ticket-020
- **Owner**: agent:codex-root
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Authorization**: SESSION_EXECUTION_AUTHORIZATION; user handed over ticket-018 and requested continuation, testing, fixes and merging. Its blocking ticket-019 was independently merged and released; this allocated follow-up owns the free scope.

## Goal and scope

Repair the reproduced scanner and snapshot audit/listing regressions from PRs #17 and #18. Retain safe acceleration, explicit compilation and verified Python fallback. Existing receipts bind three scanner failures and nine snapshot/listing disagreements to their exact predecessor sources.

## Acceptance criteria

- [x] AC-01: Direct worker and wrapper reject ancestor symlinks; reads are bounded and nonblocking.
- [x] AC-02: Panic scanning matches forced Python fallback for multiline descriptions, exact IDs and repeated prefixes; unsupported Unicode falls back.
- [x] AC-03: Snapshot health rejects malformed JSON, invalid dates, altered checksum spelling and linked metadata, and preserves deterministic Python results.
- [x] AC-04: Snapshot listing preserves Store identity and encrypted fallback; cold diagnostic queries never invoke a compiler.
- [x] AC-05: Regression/full suites and governance pass, followed by protected exact-head validation and publication.
