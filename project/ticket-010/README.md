# Ticket 010: detect LLM session storage corruption and panic issues

- **ID**: ticket-010
- **Owner**: agent:gemini
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-10

## Goal and scope

Implement robust detection of LLM coding-agent storage corruptions (e.g. SQLite page corruption `database disk image is malformed` in `~/.gemini/antigravity-cli/conversations`) and unhandled panic signatures (such as nil-pointer dereferences during trajectory loading) within `uncrash` diagnostics and recovery.

## Acceptance criteria

- [x] AC-01: Implement `check_sqlite_integrity(path)` for preflight validation of agent SQLite databases using `PRAGMA quick_check`.
- [x] AC-02: Implement `scan_agent_log_panics(log_dir)` to detect unhandled panic signatures in agent host logs.
- [x] AC-03: Implement `check_agent_storage_health(home)` providing comprehensive diagnostic status (`HEALTHY`, `DEGRADED`, `CORRUPTED`).
- [x] AC-04: Implement `salvage_agent_session_db(source, dest)` to safely quarantine and salvage corrupted session databases into clean stores.
- [x] AC-05: Unit test coverage in `tests/test_diagnostics.py` verifying detection of corrupt databases, log panics, and database salvage.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
