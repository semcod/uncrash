# Ticket 040: Keep environment settings out of persisted profile JSON

- **ID**: ticket-040
- **Owner**: agent:codex-root
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION

SESSION_EXECUTION_AUTHORIZATION: continuation of PLF-012 accepted SSOT scope. After template39 merge, code inspection found CLI profiles --apply writes the merged runtime/environment map into JSON. User requests operational .env as SSOT, with profile JSON only structured state. Existing session authorizes protected publication and bounded deployment; no real profile changes, native app launch or remote transfer in this slice.

- [x] AC-01: Profile persistence writes existing structured configuration plus selected profiles; never inject typed defaults/process/.env values. Remove legacy JSON operational values explicitly supplied by the selected file, including state/config paths before CLI consumption.
- [x] AC-02: Preserve original legacy JSON values when no selected .env defines them; effective runtime settings and explicit CLI overrides retain existing precedence.
- [x] AC-03: Meaningful file-persistence regressions, full suite and managed governance pass.
- [ ] AC-04: Verify independent protected exact-head merge; combined43setting installed runtime deployment/verification follows in PLF012.

Validation:32configuration tests passed, including env-authoritative persistence and legacy no-file behavior; full product501passed,9optional skips,8subtests. Managed governance0errors0warnings. Built combined43setting wheel and installed environment override probe passed; source publication and live deployment remain separate.
