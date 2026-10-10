# Ticket 009: Add APX recovery interface for Willmux and Minis transfer

- **ID**: ticket-009
- **Owner**: agent:codex (session execution authorization)
- **Status**: IN_PROGRESS
- **Workflow state**: VALIDATION
- **Created**: 2026-10-10

## Goal and scope

Deliver a loopback APX recovery interface in `app/uncrash-recovery/**` that presents the
existing Uncrash dashboard and recovered noVNC sessions in Willmux, and offers
an exact-bundle, confirmed transfer to Minis. Reuse existing recovery engines;
do not edit ticket-007 source, Willmux source, Fixos source or protected policy.
Maximum active session: 120 minutes. Publication and production rollout are
outside this slice; a tested local commit and runtime are the delivery target.

## Acceptance criteria

- [x] AC-01: APX manifest, loopback `/health`, SSOT and CQRS documentation pass the local APX checker.
- [x] AC-02: Panel shows recorded recovered sessions and opens each noVNC separately; session selection is reflected in the URL.
- [x] AC-03: Transfer preview binds a configured bundle hash, Minis target and expiry; a confirmation executes at most once and rejects changed content or cross-origin requests.
- [x] AC-04: Existing Uncrash panel embeds without modifying its service; Fixos integration remains explicitly queued.
- [x] AC-05: Focused security/transfer tests, browser verification and governance pass.


## Placement decision

The previous API placement attempt (ticket-008) is preserved as read-only
recovery evidence. This ticket owns the remaining runnable application under
app/**, the declared application workstream, using its separately allocated
checkout and lease. The outcome does not depend on a commit from ticket-008.

## Validation evidence

Focused transfer/security suite: 10 tests passed. Browser checks verified
three distinct noVNC links, separate popup canvas, session URL selection,
backend iframe, private exact-hash transfer preview and cancel, narrow viewport,
empty and error states. No apply request or SSH upload was executed.
APX static check passes with one explicit warning: no Willman execution-receipt
signer. Repository governance and diff whitespace checks pass. Local runtime
uses the compatible ticket-007 Uncrash installation; production remains
dependent on its trusted integration. Willmux catalog and Fixos adapter remain
queued in PLF-004. Evidence is retained outside source in the APX audit receipts.
