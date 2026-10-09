# Ticket 001: Define Uncrash package metadata and recovery contract

- **ID**: ticket-001
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-08

## Goal and scope

Define package metadata and the durable recovery, privacy, and service contract for Uncrash. This ticket owns `pyproject.toml`, `docs/**` and the user-requested `.env.example`; implementation and automated tests are assigned to a follow-up application ticket.

## Acceptance criteria

- [x] AC-01: User-requested package placement and recovery boundaries are recorded in `intent.json` and `ai-codex.md`.
- [x] AC-02: Python packaging metadata declares the supported runtime and CLI entry point.
- [x] AC-03: Wellmanifest docs index and compact documents cover recovery behavior, privacy, service operations, and fidelity limits.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.

Validation: installed offline wheel includes Rust source and .env.example; 63 tests passed, 1 skipped. Eight documentation bodies use the pinned docs contract; tracked adoption remains incomplete. Full plaintext native restore passed: all 3,780 files/13.13 GB verified by size/hash; private test data removed. No new commit, push, PR or merge; protected publication profile and governance adoption remain blockers.

Current installed wheel SHA256: f2f605566cd9963836b7dbc4a0a3bd1d6acde8ff35bd4493d97b10a09d6f182a. New portable file recovery and metadata are deployed locally; first five-profile copy completed. Protected profile observation is current at 21:17 UTC, registry digest 5c66499ec70ee47c6bc38f2ca27a5fb4732b0c622e38558b3b4485800ae1016f; publication is still blocked, no GitHub write.

Apache delivery milestone 2026-10-09: metadata/module 0.1.1, SPDX Apache-2.0 and pinned root LICENSE are joined in verified wheel/sdist; final hashes in apache-final-artifact-verification-20261009.json. Installed module/distribution/license verified in Twinerd venv; service restarted gracefully. Fresh recovery/native tests 56 passed / 1 skipped; noVNC tests not repeated for version-only edit. Public empty semcod/uncrash repository created under existing user publication authorization; anonymous HTTP200/public confirmed, delete_branch_on_merge=true. No code push, PR or merge. Independent protected profile and tracked governance adoption remain blockers.
