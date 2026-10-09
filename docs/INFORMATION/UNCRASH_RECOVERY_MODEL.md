---
{
  "schema": "wellmanifest.docs/document/v2",
  "id": "uncrash-recovery-model",
  "kind": "information",
  "version": 1,
  "title": "Uncrash recovery model",
  "status": "draft",
  "owner": "semcod/uncrash",
  "scope": "repository",
  "updated": "2026-10-08",
  "source_revision": "99601d769ca03236d8ed1249bda97451fe455d79",
  "priority": "P1",
  "evidence": [
    "artifact://ticket-001",
    "artifact://ticket-002",
    "artifact://uncrash-tests-20261008"
  ]
}
---

# Uncrash recovery model

<!-- docs:section summary -->
## Cel i rezultat

Uncrash 0.1.0 saves durable files, optionally encrypted, from explicitly registered application directories and historical process identities. Manual recovery creates separate application directories and can launch explicitly configured commands on a selected X11 display.

<!-- docs:section details -->
## Zakres i rozwiązanie

The service captures immediately, scheduling subsequent starts 300 seconds apart without overlap. Slower attempts delay the next start. Configuration: `~/.config/uncrash/config.json`; snapshots: `~/.local/state/uncrash`. Profiles contain unique lowercase `id`, absolute `state_dir` and optional explicit `argv`. `{state_dir}` and `{display}` refer to recovered data and selected display; app-specific flags are required.

Encrypted writes authenticate files with AES-256-GCM; plaintext writes use SHA256 checksums. Both publish a completed manifest after fsync and atomic directory rename, and retain the previous completed snapshots when capture fails. Ordinary files must remain unchanged while read. A profile may declare confined relative `sqlite_backup_files` or dynamic `sqlite_backup_globs`; online backup includes committed WAL data without plaintext temporary files, bounded by size and a ten-second deadline per database. Missing/invalid declared databases refuse capture. Consistency is per database, not across the complete app; other formats require native exports or quiescing.

Native `include_globs` select session files/settings. Optional zlib compression precedes encryption. Restore checks all hashes before target changes and again during staging, bounding memory by file size. See [Rust/environment controls](../SERVICE/UNCRASH_RUST_AND_ENVIRONMENT.md).

`uncrash restore latest --destination /path/to/separate-recovery` restores files without launching anything. Add `--display :NN` only for an explicitly prepared recovery desktop. Existing targets are refused by default; `--replace` preserves their contents under a separate `.pre-uncrash-*` directory. Restoring several profiles is atomic per profile, not across all profiles. A partial receipt preserves the observed result.

The pinned `wellmanifest/nl-uri-dsl-llm` export declares zero messages and `chatAdapterAvailable: false`. It records process identities without arguments or environment. `action://uncrash/restore` accepts snapshot and absolute destination only; it never evaluates shell commands. A universal Twinerd chat adapter remains unimplemented.

<!-- docs:section validation -->
## Weryfikacja

Thirty-eight unit/native tests passed in the Twinerd Python environment; the combined noVNC/backend suite passed 44 tests with one optional test skipped. Two selected real four-profile snapshots completed five minutes apart. A later full restore of the third verified 3,779 files and 13,072,648,410 logical bytes against every saved hash; private test data was removed. SQLite integrity is checked separately, and genuine provider/UI resumption remains unverified. Genuine Twinerd NativeClone/noVNC fixtures separately proved Chrome saved-tab and localStorage recovery, plus terminal replay of a saved file. See the [application matrix](../ANALYSIS/UNCRASH_APPLICATION_MATRIX.md) for coverage and limitations.

Of 503 restored SQLite images, 502 passed integrity checks. One Agy database returned SQLITE_CORRUPT in both the saved image and current source; the system SQLite engine independently confirmed the source error. File hash equality does not repair this corruption. Encrypted evidence was preserved separately from rotating snapshots; originals were not modified.

<!-- docs:section risks -->
## Ryzyka i następny krok

RAM, live PTYs, terminal scrollback, unsaved buffers and arbitrary AI sessions are not captured. Native durable-data selection exists for Codex, Claude, Agy and JetBrains settings. No Codex, Claude or Agy provider-resume adapter is implemented yet. Synthetic Agy database/history and prepared VM RAM recovery, including a real Linux shell/PTY, were tested; see [local backends](../ANALYSIS/UNCRASH_LOCAL_RECOVERY_BACKENDS.md). A process name alone is insufficient to restart the original application or conversation. Next: versioned native exports and resumption tests for these providers and IDE terminal tabs.
