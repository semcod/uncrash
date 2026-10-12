# Ticket 037: Runtime environment consumer

- **ID**: ticket-037
- **Owner**: agent:codex-root
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION

SESSION_EXECUTION_AUTHORIZATION: user requests all important operational settings in .env as SSOT using Wellmanifest standards. Existing session authorizes protected publication/merge and bounded operational deployment. Application slice owns source/tests only; ticket036 owns public env template and waits for compatible parser. No private env, credentials, protocol invariants or protected approval policy are published/moved into configuration.

- [x] AC-01: One typed environment adapter accepts current dotenv and explicit literal Env DSL documents, rejects unsafe/unknown/invalid settings, and uses one selected deployment file for runtime defaults.
- [x] AC-02: CLI/API/MCP and preview consume configurable ports, bindings, backend paths, display search range, sizes and timing; backup/daemon policy consumes the same map while preserving explicit operation arguments.
- [x] AC-03: Meaningful precedence/propagation/invalid-input regressions, full product suite and managed governance pass.
- [ ] AC-04: Independent exact-head protected publication/merge verified; deployment remains separate and preserves current24h expiry.

Compatibility: current callers and legacy env remain supported; explicit CLI/SDK inputs remain intentional overrides. New public template follows this consumer in ticket036. Constants that define protocols, consent or private file permissions remain immutable. Current standards audit finds incomplete formal pack adoption; local checks grant no merge authority.

Validation: 83 focused tests passed; full suite 490 passed, 9 optional fixture tests skipped, 8 subtests passed. Managed governance 0 errors, 0 warnings. The initial environment-selection lifetime defect was fixed using a per-invocation context reset. Protected exact-head review/merge and operational deployment remain pending.
