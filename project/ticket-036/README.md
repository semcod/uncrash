# Ticket 036: Operational environment defaults

- **ID**: ticket-036
- **Owner**: agent:codex-root
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION

SESSION_EXECUTION_AUTHORIZATION: user requests all important configuration values in .env as SSOT and verification of Wellmanifest standards. Earlier session explicitly authorizes publication and protected merge. This governance slice owns .env.example only; application consumers and integration documentation are separate owned slices. No private .env or secrets are published.

- [x] AC-01: Declare deployment paths, network bindings/ports, backup retention and timing defaults once in the public Env DSL BASE document.
- [x] AC-02: Exact local wellmanifest/env-dsl a056ea2937f782e4ee885ccbb021703cae4034c6 checker accepts the document; no shell expansion or credentials.
- [x] AC-03: Managed governance and current full product checks pass.
- [ ] AC-04: Exact-head independent protected publication and merge verified.

Non-goals: source consumer changes, protocol/security invariants, protected policy mutation or claiming complete standards adoption. Application migration must validate and consume this contract before deployment of private extended settings.

Dependency resolved: application consumer ticket-037 merged through protected PR #36 at 1a4f3f6bcc551d204aefc2f71fd8590dddfa09c5. This checkout advanced to that accepted base. The prior source reservation was explicitly released before a new bounded lease was acquired.

Validation: immutable Env DSL checker ENV-PASS; full suite 490 passed, 9 optional fixture skips, 8 subtests passed; managed governance 0 errors, 0 warnings. Wheel builds successfully and an isolated installation loads its packaged BASE document (36 constants) and a selected LOCAL override. Exact-head independent publication remains pending.
