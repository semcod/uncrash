# Ticket 022: Accelerate session hosts inspection via native proc scan

- **ID**: ticket-022
- **Owner**: agent:Antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-11

## Goal and scope

Accelerate session hosts discovery and process ancestry inspection via native proc scanning in Rust (`--session-hosts`), eliminating sequential Python filesystem and readlink overhead while retaining 100% Python fallback.

## Acceptance criteria

- [x] AC-01: Native session hosts inspection matches Python fallback across PID/UID fencing, process names, executable resolution, cmdline filtering, and ancestor stability.
- [x] AC-02: Native proc scan safely handles unstable processes, non-decimal directories, and missing/inaccessible proc nodes.
- [x] AC-03: All tests pass without regression; governance clean; publication via OneDev and independent Validator.

## Tracking boundary

This directory contains the minimal reviewed intent.
