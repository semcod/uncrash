# Ticket 042: Make pidfd tests portable without the native Python wrapper

- **ID**: ticket-042
- **Owner**: agent:codex-root
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Accepted base**: `34691586129636979e19e5dea475ea5f50dff378`
- **Planfile request**: PLF-014

SESSION_EXECUTION_AUTHORIZATION: The user requests continued implementation, testing and merging. Follow up ticket-041 / PR #41: at its exact merged source, independently simulated wrapper absence causes AttributeError during test mock setup (1 failed, 2 passed); real owned-process pidfd fallback succeeds. Fix test portability and verify the bounded process target. Publication is authorized only through exact-head OneDev and the independent protected Validator. This ticket changes tests and its declared tracking paths only.

- [x] AC-01: Native-wrapper unit mocks can install an absent wrapper; GUI identity and TERM/KILL tests mock the runtime signaling boundary and run without the Python wrapper, with no added skips.
- [x] AC-02: Real Linux owned-process tests exercise syscall signaling with the native wrapper absent; Launcher.stop leaves an unrelated sibling alive and clears stopped ownership records.
- [x] AC-03: Focused wrapper-absence regressions, full pytest and managed governance pass; optional integration skips are reported separately.
- [ ] AC-04: The frozen exact head passes OneDev and protected Validator review/merge. No direct merge or synthetic approval.

Implementation session bound: 120 active minutes. Preserve unrelated work and actual GUI applications; process fixtures are spawned by these tests and cleaned up.
