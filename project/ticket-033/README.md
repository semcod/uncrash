# Ticket 033: Render workspace bar metadata as inert text and bind actions safely

- **ID**: ticket-033
- **Owner**: agent:codex-root
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: user requested continued backlog repairs, tests and protected publication through Willman. PLF-009 retains unsafe workspace bar labels and inline select/close handlers. Workspace names, ID fallbacks and display/count metadata must stay literal text. Bind selection and close callbacks to raw IDs without interpolating them into JavaScript; close must stop propagation so only the requested workspace is closed. Preserve filtering, visible digit targets, active styling, engine badges and empty states. API semantics, dependencies, real application actions, protected policy and deployment are outside this ticket.

## Acceptance criteria

- [x] AC-01: Workspace chip metadata is rendered as inert text for HTML, quotes and Unicode; no metadata introduces elements or event attributes.
- [x] AC-02: Actual selection/close callbacks preserve quoted and Unicode IDs; close stops bubbling and never selects another workspace. Callbacks bind only existing rendered nodes.
- [x] AC-03: Full source suite, mandatory four-window X11 and managed governance pass through Willman; filtering, digit targets and safe noVNC copy still pass.
- [ ] AC-04: Frozen exact-head OneDev and independent Validator produce trusted protected merge evidence.

## Tracking boundary

Accepted base: 29f9580af155f317d5588df622a2451086916fe0. Read-only chip controls on the inherited source reproduced two failures and one Unicode positive control. Prior ticket032 is independently approved and merged; historical ticket027 publication remains preserved as blocked by missing prior approval. This repair creates no retrospective approval.

## Validation

Corrected execution tests against the exact accepted-base dashboard: 12 failed, 9 passed. An earlier incomplete DOM fixture could not reach rendering and is not used as baseline evidence. After the fix: dashboard 77 passed; full source suite 457 passed, 9 optional runtime/service skips and 8 passed subtests. The mandatory real four-window X11 fixture passed; managed governance reports zero findings. All checks ran through Willman. No user application action was performed. Independent exact-head OneDev and protected Validator remain required for AC-04.
