# Ticket 006: Refine environment configuration resolution in uncrash CLI

- **ID**: ticket-006
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-09

## Goal and scope

Refine environment configuration resolution in `uncrash` CLI to ensure deterministic execution across all directories by prioritizing the dedicated user configuration `~/.config/uncrash/.env` over unrelated `.env` files located in `$HOME`.

## Acceptance criteria

- [x] AC-01: CLI resolves `--env-file`, then `UNCRASH_ENV_FILE`, then `~/.config/uncrash/.env`, and only falls back to `Path.cwd() / '.env'` when distinct from `$HOME`.
- [x] AC-02: Add regression unit test in `tests/test_native.py` verifying that execution from `$HOME` with an unrelated `.env` correctly uses `~/.config/uncrash/.env`.
- [x] AC-03: Governance checks pass cleanly with 0 errors and test suites pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
