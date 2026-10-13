# Ticket 046: capture retry Env DSL defaults

- **ID**: ticket-046
- **Owner**: agent:codex-root
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION

SESSION_EXECUTION_AUTHORIZATION: user requests continued tests and protected merge. Completes governance-owned template slice of PLF-017 after independently merged source ticket045/PR45/0949c216. Sole writer in canonical disjoint checkout, no source ownership expansion or IDE/provider operation.

Publish total attempt count and shared additional-retry deadline as literal typed Env DSL settings. Keep BASE one-attempt compatibility; document explicit2or3 attempts for a deployment. Immutable source support exists on accepted current main. Local deployment will explicitly select2attempts/120seconds only after trusted source/template publication and guarded migration of the old43-field private configuration.

- [x] AC-01: Public template parses through the merged typed Env DSL reader with both limits and preserves existing values.
- [ ] AC-02: Managed gate and relevant configuration/retry tests pass; exact-head independent protected publication required.

Validation: template canary preserves43existingtypedvalues and adds2fields;54configuration/retry tests PASS with explicitPYTHONPATH=src; managed governancePASS0errors0warnings. Core source is unchanged from PR45 independently verified555PASS/9optionalSKIP/8subtests; this template head requires fresh independent CI/review. The initial selected-test collection lacked a source import path and is preserved as an execution failure, corrected by the explicit source path.
