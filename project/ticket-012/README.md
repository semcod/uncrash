# Ticket 012: Safe explicit single-window close and whole-process CLI consent

- **ID**: ticket-012
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: VALIDATION
- **Created**: 2026-10-10

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: the user requested investigation and closing only the last PyCharm window, preserving other windows, then instructed continuation. Intake PLF-13801. Implement in the disjoint CLI/window-control scope; ticket-010 retains recovery.py and ticket-011 remains frozen for publication. No whole-process termination of the user's IDE is authorized.

Require explicit whole-process intent for CLI, REST and MCP process-close routes. Inspect live X11 windows and request one fenced PyCharm window close with verification and no kill fallback. Report native Wayland control as unavailable when no verified adapter exists. No GUI keyboard automation, JVM injection, dependency changes or production installation.

Scope continuation: src/uncrash/api.py is free according to the managed work-start observation. It exposes the same process-signalling operation through REST/MCP, so consent there is necessary for the accepted safety outcome. The controller released only this session's prior lease by exact CAS and rebound ticket-012 to the extended scope; snapshot and decision receipt are in the external local operator receipts.

## Acceptance criteria

- [x] AC-01: close-app, apps --close and pycharm close require --entire-process independently of --force; REST/MCP require entire_process=true. Missing consent never reaches the signal function. Dry-run remains read-only and reports the whole-process scope.
- [x] AC-02: Window inventory binds XID, PID and process start identity. Single-window close verifies target, records remaining peer windows and never falls back to a process signal.
- [x] AC-03: Stale identity, unavailable/Wayland backend, unresolved target, blocked close and peer loss have meaningful negative tests; focused/full stack tests and managed governance pass.
- [ ] AC-04: Re-observe the user's requested maskservice window and preserve other IDE windows; do not claim closure without direct evidence. User confirmed fixos was closed independently.

## Validation and remaining work

Full Twinerd venv suite: 112 passed / 10 skipped, including optional runtime/GUI fixtures and python-xlib unavailable in that venv. Separate system-Python window suite: 30 passed, including an actual Xvfb/Openbox desktop with four same-PID synthetic PyCharm windows, one WM_DELETE_WINDOW and three preserved windows. Managed governance and diff formatting pass. Live-host negative probes refused process termination and unavailable native Wayland control; original PID/start identity remained alive.

REST request model annotation is resolved before route registration so JSON bodies reach the consent check. MCP refusal uses an anticipated ToolError rather than hiding the explanation as an unexpected crash. Existing process PID/start checks remain in recovery.py, untouched under ticket-010 ownership.

Fresh compositor observation at 18:13:13 UTC: maskservice, selective-tutor and uncrash remain. fixos was independently closed by the user. No close request or process signal was sent this continuation. AC-04 awaits a verified native Wayland/project close adapter; no keyboard close automation or JVM injection is used. Source changes are local only; the running installation was not modified. Existing PR9 remains frozen, with protected preflight PUBLICATION_PROFILE_MISSING; this ticket creates no push/PR/merge/deployment authority.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
