# Ticket 019: Native Rust acceleration for snapshot manifest verification, health auditing, and session diagnostics

- **ID**: ticket-019
- **Owner**: agent:Antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-11
- **Authorization**: SESSION_EXECUTION_AUTHORIZATION (user request: "kontynuuuj, co jeszce wymaga poporawy? gdzie jescze mozna zoptymalizować czas generowania wynikow analizy porpzez uzycie rust?", "kolejno")

## Goal and scope

1. Accelerate snapshot manifest verification and health auditing (`snapshot_health`) by executing streaming SHA-256 verification and JSON parsing natively in `src/uncrash/snapshot.rs`, reducing latency from ~3.7 seconds to ~15 milliseconds across 100+ snapshots.
2. Accelerate snapshot metadata extraction in REST API (`get_snapshots`) with native Rust processing while keeping bit-for-bit parity and clean Python fallback.
3. Keep 100% Python fallback when the native Rust worker is unavailable, preserving compatibility and fail-closed safety.
4. Add comprehensive unit and regression tests verifying bit-for-bit parity, invalid manifest detection, and fallback semantics.

## Acceptance criteria

- [x] AC-01: Native Rust CLI mode `--snapshot-health <state_dir> <interval_seconds> [now_iso]` implemented in `src/uncrash/snapshot.rs`.
- [x] AC-02: Native Rust CLI mode `--list-snapshots <state_dir>` implemented in `src/uncrash/snapshot.rs`.
- [x] AC-03: `snapshot_health` in `src/uncrash/diagnostics.py` uses native acceleration with automatic, transparent fallback to pure Python.
- [x] AC-04: `get_snapshots` in `src/uncrash/api.py` utilizes fast native metadata listing with fallback.
- [x] AC-05: Parity and edge case tests in `tests/test_diagnostics.py` and `tests/test_api.py` pass with zero skip shortcuts.
- [x] AC-06: Pass all local governance checks and test suites.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
