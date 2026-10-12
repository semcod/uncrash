# Ticket 039: Complete APX Env DSL BASE defaults

- **ID**: ticket-039
- **Owner**: agent:codex-root
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION

SESSION_EXECUTION_AUTHORIZATION: continuation of PLF-012 and repeated user request to move all important operational variables into .env as SSOT using Wellmanifest. Existing session authorizes protected publication and bounded operational deployment. Core/APX compatible consumers are already protected-merged in PRs36/38. This slice owns public BASE defaults only; private .env/wheel deployment follows verified merge. No credentials, protocol/private-permission/consent invariants, native GUI launch or remote transfer.

- [x] AC-01: BASE documents all43 operational values supported by the merged typed consumer; the optional Rust worker and explicit SSH target remain unset comments.
- [x] AC-02: Exact pinned Env DSL checker a056ea2937f782e4ee885ccbb021703cae4034c6 accepts the complete BASE; main/APX consumers and installed wheel obey selected environment precedence.
- [x] AC-03: Managed governance and full product tests pass; packaging includes the validated BASE document.
- [ ] AC-04: Protected exact-head independent merge is verified; deploy immutable wheel and43-value private LOCAL.env while preserving5profiles,5-minute cadence and24h expiration; verify behavior.

Formal six-pack adoption remains an audit question, not authority to fabricate S3/S4 records. Existing Docs location/index and nohardcode findings are reported separately. Completed source038 misbound reservation has been explicitly released; this new disjoint lease must bind the actual039branch.

Validation: exact pinned Env DSL checker ENV-PASS; full suite499passed,9optional fixture skips,8subtests; managed governance0errors0warnings. Wheel packages43BASE values and an isolated installed probe confirms deployment overrides and APX defaults without an implicit SSH destination. Exact-head protected publication and operational deployment/verification remain pending.
