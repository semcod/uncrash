---
{
  "schema": "wellmanifest.docs/document/v2",
  "id": "uncrash-privacy-and-storage",
  "kind": "information",
  "version": 1,
  "title": "Uncrash privacy and storage",
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

# Uncrash privacy and storage

<!-- docs:section summary -->
## Cel i rezultat

New snapshots, receipts and process records default to private plaintext. AES-GCM encryption is opt-in with `UNCRASH_ENCRYPT=true`. Existing encrypted copies remain readable. Recovery data, local `.env` and encryption keys are excluded from Git.

<!-- docs:section details -->
## Zakres i rozwiązanie

The store and recovered directories use mode 0700; snapshot files and any separate random 32-byte encryption key use 0600. Optional AES-GCM associated data binds format, origin, snapshot and file label. Plain SHA256 checksums detect accidental changes but provide no authentication or confidentiality. Missing keys, a different origin or corrupted ciphertext prevent restore. Preserve the key through a separately protected backup; copying snapshots alone is insufficient.

The process observer omits command lines, environments and terminal input. Profiles are opt-in and cannot target the entire home directory or overlap the store. Common credential stores, `.ssh`, `.gnupg`, `.env*`, browser Cookies/Login Data, `auth.json`, `oauth.json`, `tokens.json`, `.credentials.json`, `antigravity-oauth-token`, `secrets.json` and private-key suffixes are excluded. Symlinks, special files, oversized files and unstable file reads cause capture refusal rather than traversal.

Default limits: 64 MiB per file, 512 MiB of source data per snapshot, 288 completed snapshots, 4 GiB allocated snapshot storage and 1000 restore receipts. The byte budget can shorten the nominal one-day retention at a five-minute cadence. The Rust deployment uses 512 MiB per file, 16 GiB logical data and a 32 GiB allocated-storage budget, encryption/compression disabled. Shared unchanged blobs count once. Earlier encrypted full copies occupied about 3.39 GB each under an 8 GiB budget. Retention deletes oldest completed snapshots only. Pending directories left by SIGKILL are not yet scavenged automatically.

The implementation follows the Wellmanifest secrets principles of restricted access, origin binding, explicit opt-in and no secret output. It does not claim adoption of an external secrets vault or independent key-management service. Filename exclusions cannot remove all secrets embedded in an ordinary document or application database. Production child output is discarded; event logs expose safe event names and error classes.

<!-- docs:section validation -->
## Weryfikacja

Tests verify encryption, key mode, origin mismatch, secret filename exclusions, corruption refusal before destination mutation, symlink refusal and storage budgets. Synthetic desktop fixtures use separate HOME/runtime directories and no personal profiles or provider accounts.

Of 503 restored SQLite images, 502 passed integrity checks. One Agy database returned SQLITE_CORRUPT in both the saved image and current source; the system SQLite engine independently confirmed the source error. File hash equality does not repair this corruption. Encrypted evidence was preserved separately from rotating snapshots; originals were not modified.

<!-- docs:section risks -->
## Ryzyka i następny krok

Same-machine backups do not survive disk loss. Declared `sqlite_backup_files` and `sqlite_backup_globs` use SQLite online backup into bounded memory, including committed WAL transactions and omitting WAL/SHM/journal sidecars. This gives consistency per database, not across databases/files, and cannot save application data never flushed. Selected native profiles now capture Codex session JSONL and state SQLite, Claude project JSONL, Agy conversation SQLite/history, and JetBrains options/keymaps/colors/templates/code styles/dictionaries. Unrelated caches, plugins and known credential files are excluded. Other active databases require native exports or quiescing. Active files that keep changing can prevent a snapshot. Next: genuine provider/IDE resumption adapters, per-profile failure isolation, controlled vault integration and off-machine encrypted storage.
