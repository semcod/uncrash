# Ticket 003: Apply Apache license to public Uncrash package

- **ID**: ticket-003
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-09

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: user requests public Python package, Apache-2.0 alignment through wellmanifest/license, and continued delivery. This bounded governance ticket owns LICENSE only; ticket-001 owns Python metadata/docs, ticket-002 owns runtime/tests. No adoption scaffold or remote policy is changed here.

## Acceptance criteria

- [x] AC-01: Allocator reserves canonical identity and admitted governance LICENSE scope; controller accepts explicit owner handoff and rebinds current intent.
- [x] AC-02: Root LICENSE matches pinned public-Python Apache template including owner attribution; Python artifacts include it.
- [ ] AC-03: Governed commit/publication/integration completes through independent protected delivery.

## Recovery

Allocator reserved ticket-003 and canonical worktree, then failed on relative ticket_storage.py lookup. The unchanged primary managed helper validated LICENSE ownership. Its linked-root persistence failed because that checkout lacks the untracked manifest; the allocator's exact metadata projection was applied to the reserved intent after primary validation. No ID was reassigned and no failed path was retried. Current primary writer explicitly hands off and rebinds revised intent before implementation.

Validation: pinned LICENSE bytes match SHA256 48e3dd3a8d539adb592ab8d6273176aba365d236992abc972385bc5b236f93fa. Version 0.1.1 wheel and sdist both contain identical full LICENSE and metadata License-Expression Apache-2.0 / License-File LICENSE. Installed in Twinerd venv; ten runtime files match the prior 63-test source, running service unchanged. Current protected publication preflight still PUBLICATION_PROFILE_MISSING. Local adoption gate rejects unresolved/adopter required-checks. No new commit/push/PR/merge.
