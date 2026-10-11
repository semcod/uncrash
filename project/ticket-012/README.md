# Ticket 012: Safe window close and read-only freeze prevention

- **ID**: ticket-012
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: VALIDATION
- **Created**: 2026-10-10

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: the user requested investigation and closing only the last PyCharm window, preserving other windows, then instructed continuation. Intake PLF-13801. Implement in the disjoint CLI/window-control scope; ticket-010 retains recovery.py and ticket-011 remains frozen for publication. No whole-process termination of the user's IDE is authorized.

Require explicit whole-process intent for CLI, REST and MCP process-close routes. Inspect live X11 windows and request one fenced PyCharm window close with verification and no kill fallback. Report native Wayland control as unavailable when no verified adapter exists. No GUI keyboard automation, JVM injection or dependency changes. The later continuation below authorizes only the versioned local user CLI.

Scope continuation: src/uncrash/api.py is free according to the managed work-start observation. It exposes the same process-signalling operation through REST/MCP, so consent there is necessary for the accepted safety outcome. The controller released only this session's prior lease by exact CAS and rebound ticket-012 to the extended scope; snapshot and decision receipt are in the external local operator receipts.

Prevention continuation (PLF-13803): SESSION_EXECUTION_AUTHORIZATION on 2026-10-10 requests improvements preventing future freezes. Extend the owned ticket with bounded, read-only health.py and tests/test_health.py, CLI doctor and REST/MCP inspection. Detect fresh IO exhaustion, Docker/IJent thread waits, memory/IO pressure and generated indexing roots. Stale, missing, malformed or quota-limited data must not produce a healthy verdict. No automatic signals, Docker operations, JVM injection, dependency changes, IDE configuration edits or deployment. External scope decision and controller lease bind this extension.

Restore-gate continuation: SESSION_EXECUTION_AUTHORIZATION from the user's next continuation covers connecting the risk check to explicit PyCharm restore and making this tested local CLI available. Keep this in the existing owned scope. Local inspection found the user launcher pointing at Twinerd with an editable source path to an absent ticket-007 checkout. Prepare a versioned per-user CLI installation, preserve the original symlink for rollback, verify the exact committed source, and replace only that launcher by CAS. Do not edit the shared environment, restart the daemon, change IDE settings, terminate processes, push or merge. Planfile synchronization is retained in the external outbox because the adapter session is terminated.

Strict-flag continuation: SESSION_EXECUTION_AUTHORIZATION from "kontynuuj, testuj, poprawiaj" covers testing and correcting the existing process-close safety boundary. Read-only mock probes reproduced MCP coercion of 1, "true" and "yes" into whole-process consent. Require literal JSON booleans for consent and force through both MCP and REST; retain positive explicit-boolean behavior and reject malformed flags before any close function call. The shared live PyCharm PID remains protected, and the separate proposed two-window restart still awaits explicit authority. Preserve the request in the PLF-13803 external outbox while its adapter session is terminated.

## Acceptance criteria

- [x] AC-01: close-app, apps --close and pycharm close require --entire-process independently of --force; REST/MCP require entire_process=true. Missing consent never reaches the signal function. Dry-run remains read-only and reports the whole-process scope.
- [x] AC-02: Window inventory binds XID, PID and process start identity. Single-window close verifies target, records remaining peer windows and never falls back to a process signal.
- [x] AC-03: Stale identity, unavailable/Wayland backend, unresolved target, blocked close and peer loss have meaningful negative tests; focused/full stack tests and managed governance pass.
- [x] AC-04: Re-observe the user's requested maskservice window and preserve other IDE windows; do not claim closure without direct evidence. User confirmed fixos was closed independently.

- [x] AC-05: Bounded read-only doctor reports incident IO starvation patterns, fresh/stale/unknown evidence, system pressure and IDE generated-root exclusion audit.
- [x] AC-06: CLI preflight gates additional load; REST/MCP expose equivalent read-only findings without changing liveness health.
- [x] AC-07: Regression tests cover incident counts, coroutine duplicates, stale/missing/malformed/oversized evidence, unsafe paths, process identity and exclusion boundaries; full stack and managed governance pass.

- [x] AC-08: Explicit pycharm restore --preflight blocks all restore calls on warning/critical/unknown evidence; bounded saved-dump discovery avoids JVM attach and has quota/symlink/freshness tests.
- [x] AC-09: A versioned user CLI installation from exact committed source supports doctor and refusal of unconsented close; original launcher and daemon process/config are preserved.
- [x] AC-10: MCP and REST reject non-boolean process-close consent and force without calling recovery; explicit JSON booleans still work on both supported MCP backends.

## Validation and remaining work

Full Twinerd venv suite: 112 passed / 10 skipped, including optional runtime/GUI fixtures and python-xlib unavailable in that venv. Separate system-Python window suite: 30 passed, including an actual Xvfb/Openbox desktop with four same-PID synthetic PyCharm windows, one WM_DELETE_WINDOW and three preserved windows. Managed governance and diff formatting pass. Live-host negative probes refused process termination and unavailable native Wayland control; original PID/start identity remained alive.

REST request model annotation is resolved before route registration so JSON bodies reach the consent check. MCP refusal uses an anticipated ToolError rather than hiding the explanation as an unexpected crash. Existing process PID/start checks remain in recovery.py, untouched under ticket-010 ownership.

Live observation at 18:34:42 UTC: maskservice is absent, selective-tutor and uncrash remain, and JVM PID 59643/start 13484 is unchanged. The user confirmed fixos was closed independently and another agent still acts on the IDE. A single compositor close-button click was sent in the earlier authorized attempt, but concurrent ForceCloseProjectAgent activity prevents causal attribution to that click. AC-04 records target disappearance and peer preservation, not proof of which actor closed it. Recovery of remaining windows is unverified. The product native Wayland window backend remains unavailable. Source changes are local only; the running installation was not modified. Existing PR9 remains frozen, with protected preflight PUBLICATION_PROFILE_MISSING; this ticket creates no push/PR/merge/deployment authority.

## Prevention validation and operation

Final full suite: 151 passed / 10 skipped, including 39 health/preflight tests. Optional installed GUI/runtime fixtures and venv python-xlib are skipped; the earlier system-Python Xvfb single-window fixture passed. Managed governance and diff formatting pass. CLI doctor returns inspection JSON without initializing a store or reading an environment file. With --preflight, exit codes are 0 no risk observed in supplied evidence, 1 warning, 2 critical, 3 unknown. REST /api/v1/doctor and MCP uncrash_inspect_health expose the same operation; /api/v1/health remains transport liveness.

Example after this branch is installed: `uncrash doctor --log-dir ~/.cache/JetBrains/PyCharm2026.2/log --thread-dump /path/to/existing-thread-dump.txt --project /path/to/project --preflight`. It does not collect a new JVM dump. Evidence files do not become PID-bound merely by passing --pid/--start-ticks. This is an explicit advisory launch gate, not an automatically deployed monitor or proof that the UI responds.

Live-host read-only inspection reproduced the critical IO-exhaustion finding, with verified process identity. Existing dump counts were 63 Docker exit waits and 115 IJent filesystem waits, correctly marked stale. Generated roots had unknown IDE exclusions; source content, raw stack traces, terminal commands and private agent data are not returned. Limits bound bytes, module/directory counts and accepted XML; symlinks, special files, malformed, stale and truncated evidence cannot yield a green verdict.

New material source remains local; no production installation, push, PR, merge or deployment was requested. Planfile PLF-13803 exists, but its status update failed with MCP session terminated; a local external outbox preserves the next synchronization. Do not retry that terminated session indefinitely. Ticket remains IN_PROGRESS / VALIDATION pending authorized delivery, and the session lease is released by exact controller CAS after the local commit/checkpoint.

## Restore-gate validation and local installation

Restore-gate source passed 168 tests / 9 optional skips under the base Python runtime selected for the per-release environment, including the actual Xvfb/Openbox single-window fixture. The Twinerd venv focused suite passed 84 / 1 python-xlib skip. The health suite now contains 55 tests. Managed governance and diff formatting pass. The live restore gate returned blocked_by_preflight, launched=false, exit 2 on current IO exhaustion.

Doctor can now select the newest saved IDE thread dump when --log-dir is given and --thread-dump is omitted. It bounds directory entries, directories and files, rejects links/special files and never invokes jcmd or attaches to Java. Freshness remains explicit; no available dump or an incomplete inventory cannot produce a green result.

After local installation, run `uncrash doctor --log-dir ~/.cache/JetBrains/PyCharm2026.2/log --project . --preflight`. To gate an explicit restore, use `uncrash pycharm restore --project /path/to/project --log-dir /path/to/IDE/log --preflight`. --preflight requires a known project, cannot combine with close, and returns 1/2/3 before any restore call on warning/critical/unknown evidence. Direct desktop launches and restores without this flag remain outside this gate.

AC-09 was completed by the external installation receipt for faacaf7dbb6229b6c5fa7a15b4728cb8b02b667b. The versioned release binds committed source digests, uses a private per-release venv with existing base-system dependencies, and replaced only the observed per-user uncrash symlink. The original target remains available for rollback. Twinerd, the running snapshot daemon, IDE processes/settings, Docker, remote branches and PRs were preserved. Completion and rollback bindings remain in the external installation/delivery receipt; create no carrier-only closure commit.

## Strict process-close flag validation

Mock transport probes reproduced whole-process consent from 1, "true" and "yes" in MCP. The regression matrix failed 24 cases before the fix. MCP consent and force now use actual StrictBool annotations bound before tool registration on both supported backends; REST force uses the same strict boolean model as its consent field. Numeric, string, null, array and object values are rejected before recovery. Explicit boolean consent and both boolean force values retain their behavior. No live process signals were sent.

The full base-runtime suite passed 213 tests with 9 opt-in skips, including the owned Xvfb/Openbox fixture that closes one of four shared-PID windows and preserves three. The focused Twinerd-runtime suite passed 129 tests with one python-xlib skip, covering the alternative MCP backend. The follow-up local release will be installed from this material commit under the existing user-CLI authorization, preserving its preceding version for rollback. The separate proposal to restart the user's shared two-window IDE remains pending explicit authorization.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.

## Native qualification continuation

Native qualification found a host-dependent API inventory test and transient X11 startup/teardown observations. Use explicit synthetic installed/empty inventory fixtures, await the owned window manager redirect subscription before creating clients, and retry only a typed client-list change within the existing close deadline. Preserve process identity and peer-window checks; send no additional close request or signal. Existing PR10 must receive fresh exact-head verification and independent review after this material follow-up.

Follow-up validation: 84 focused API/window tests and 216 complete product tests pass with 9 existing opt-in skips. Managed governance passes. AC-11 remains pending fresh native qualification and protected exact-head publication.

- [ ] AC-11: Native canary verifies deterministic installed/empty API fixtures and bounded transient X11 observation without additional close requests or process signals; fresh independent review covers the resulting head.
