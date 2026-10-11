# Ticket 021: Accelerate agent storage health and provider inventory

- **ID**: ticket-021
- **Owner**: agent:Antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-11

## Goal and scope

Accelerate diagnostic report generation by parallelizing SQLite integrity checks across hundreds of conversation databases and optimizing native Rust audit pipelines (multi-threaded snapshot health audit and native provider inventory scan), retaining 100% Python fallback.

## Acceptance criteria

- [x] AC-01: Bounded parallel SQLite integrity checks preserve exact error classification ('ok', 'corrupted', 'unavailable', 'missing') and sequential parity.
- [x] AC-02: Multi-threaded native snapshot health audit matches Python fallback and preserves security boundaries.
- [x] AC-03: Native provider inventory acceleration matches Python output structure and falls back safely on any IO or format error.
- [ ] AC-04: All tests pass without regression; governance clean; publication via OneDev and independent Validator.

## Tracking boundary

This directory contains the minimal reviewed intent.
