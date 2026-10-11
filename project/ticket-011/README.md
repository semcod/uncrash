# Ticket 011: Verify noVNC preview availability before opening recovered sessions

- **ID**: ticket-011
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-10

## Goal and scope

An open TCP port can belong to another application or a noVNC server without the requested page. Validate the actual noVNC HTTP preview and prevent stopped or stale selected sessions from opening an iframe or separate-window link. HTTP availability does not prove VNC authentication, framebuffer state or live RAM/PTY recovery.

SESSION_EXECUTION_AUTHORIZATION: user requested continuation, with prior instructions to implement, test and merge. Local implementation, tests, commit and PR are authorized. Merge requires the declared independent protected process. No session restart, SSH transfer or production activation is included. Session bound:120 active minutes.

## Acceptance criteria

- [x] AC-01: A bounded direct HTTP probe accepts noVNC HTML and rejects unrelated services, redirects, missing pages, oversized responses and timeouts.
- [x] AC-02: Stale/stopped selection never opens an iframe or actionable separate window; available previews remain usable and refresh removes stale frames.
- [x] AC-03: APX regression tests, full source tests and managed governance pass; browser readback and exact delivery states are preserved externally.

## Ownership and publication

This scope is disjoint from active ticket010 and preserves blocked ticket008 recovery inventory. The Willmux catalog path has competing unknown-owned dirty changes; no catalog or primary UI edit is made here. Current independently deployed OneDev/Validator profiles do not contain semcod/uncrash; a tested local commit/PR is reviewable, while protected merge remains pending profile onboarding by its owner.

## Validation results

98 tests passed,9 optional fixtures skipped,8 subtests passed. The isolated real browser canary passed8 observations: installed noVNC HTML recognition, rejection of another live HTTP service, stale/stopped URL gating, real WebSocket/RFB connection to our own Xvnc, independent window opening, refresh revocation, empty inventory and invalid-inventory error handling. Both owned desktop subprocesses were reaped. No existing recovery session was restarted or closed. Probe readiness is HTTP client availability, not an RFB attestation.

Managed governance passes with0 errors. Source lint passes. Deployed coordinator profile digest622e53abcdd2061c4c27c75391d5c9039ef2f24dc30c8fd42b699050779582b5 has no semcod/uncrash profile; the protected Validator registry1.3.109 likewise lacks this repository. Keep publication pending exact protected onboarding; a local PASS is not approval evidence. External evidence: private state directory uncrash-preview-availability-20261010.

APX packaging checker reports valid=true with its existing APX-COMP-001 missing optional Willman receipt-provider warning. Fifteen focused APX tests and8 subtests passed after final import normalization. Keep this ticket IN_PROGRESS/PUBLICATION for independent exact-head review; no closure commit or deployment is claimed.
