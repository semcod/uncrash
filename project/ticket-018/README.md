# Ticket 018: Native Rust acceleration for agent log panic scanning and session diagnostics

- **ID**: ticket-018
- **Owner**: Antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-11

## Goal and scope

Accelerate agent storage health inspections and panic diagnostics using native Rust
execution in the worker binary while preserving fail-safe Python fallbacks.
Specifically:
1. Extend `src/uncrash/snapshot.rs` with high-throughput `--scan-panics <dir> [budget]` mode.
2. Integrate native panic scanning into `src/uncrash/diagnostics.py` with safe binary discovery and automatic fallback.
3. Add worker precompilation helpers to eliminate runtime `rustc` compiler invocation latency during diagnostics.
4. Comprehensive test coverage ensuring bit-for-bit parity between native Rust and Python scanner results.

## Acceptance criteria

- [x] AC-01: Native worker supports `--scan-panics` sub-command with budget limits and symlink protections.
- [x] AC-02: `scan_agent_log_panics` transparently attempts native acceleration and falls back to pure Python if unavailable.
- [x] AC-03: Precompilation caching prevents redundant runtime `rustc` executions.
- [x] AC-04: Test suite verifies parity, edge cases, and fallback behavior without shortcuts or `pytest.skip`.

## Tracking boundary

This directory contains the reviewed intent and implementation record.
