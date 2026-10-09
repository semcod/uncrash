---
{
  "schema": "wellmanifest.docs/document/v2",
  "id": "uncrash-rust-and-environment",
  "kind": "service",
  "version": 1,
  "title": "Uncrash Rust worker and environment settings",
  "status": "draft",
  "owner": "semcod/uncrash",
  "scope": "repository",
  "updated": "2026-10-08",
  "source_revision": "99601d769ca03236d8ed1249bda97451fe455d79",
  "priority": "P1",
  "evidence": [
    "artifact://rust-suite-20261008-prefix",
    "artifact://production-rust-final-20261008"
  ]
}
---

# Rust worker and environment settings

<!-- docs:section summary -->
## Cel i rezultat

New snapshots default to Rust, no encryption and no compression. Durable session files/settings are captured; this does not restore live host RAM, provider conversations or JetBrains terminal tabs.

<!-- docs:section details -->
## Zakres i rozwiązanie

Copy `.env.example` to `.env` and edit literal values. The active local deployment uses the primary project's `.env`, mode 0600. It is excluded from Git. Restart only `uncrash.service` after changes.

```dotenv
UNCRASH_ENCRYPT=false
UNCRASH_SNAPSHOT_ENGINE=rust
UNCRASH_COMPRESS=false
UNCRASH_RUST_THREADS=4
UNCRASH_INTERVAL_SECONDS=300
UNCRASH_MAX_TOTAL_BYTES=34359738368
```

Use `UNCRASH_ENCRYPT=true` for AES-256-GCM. Existing encrypted copies and their separate key remain readable. Plain snapshots need no key; they use SHA256 checksums to detect accidental changes, without cryptographic authentication or confidentiality. Keep snapshot files private and immutable; restore into a separate destination.

Precedence: defaults, JSON configuration, `.env`, process environment, explicit CLI overrides. `--env-file /absolute/path/.env` or `UNCRASH_ENV_FILE` selects the file; otherwise the CLI uses the current directory's `.env`, then `~/.config/uncrash/.env`. Shell evaluation and variable interpolation are refused. Paths may start with `~/`; encryption keys never belong in `.env`.

`uncrash build-native` builds packaged `snapshot.rs` into a private source-hash cache. Requirements: Linux, rustc and OpenSSL/zlib development libraries. No Rust crates are downloaded. Ordinary files require stable identity while read; symlink traversal is refused. Parallel COW/kernel copies are used where supported. JSONL logs capture the initial-length prefix; if changed, that prefix is read again and must match. Growth may drop an unfinished last line. This is per-file capture, not an atomic cross-application state. SHA256 and optional AES-GCM use system OpenSSL; optional compression uses zlib.

Plain snapshots reuse unchanged prior blobs after source identity/size/mtime/ctime and cached-blob metadata checks. SQLite always receives a fresh online backup; equal content digests permit reuse. Cached files are hard-linked between completed snapshots, never to live application files. Retention counts allocated blocks for shared inodes once. Restore verifies every saved content digest before changing targets.

<!-- docs:section validation -->
## Weryfikacja

Combined suite: 44 passed, one optional systemd test skipped. Rust modes, Unicode paths, legacy encrypted coexistence, reuse, budgets, WAL, environment precedence and symlink refusal passed. Real noVNC Chrome/xterm and owned VM RAM/PTY fixtures passed. Final installed service captured four profiles, 3,780 files and 13.13 GB in 9.156 seconds with 3,775 reused files. Initial copying took minutes; lock contention affects reported duration. Full plaintext restore verified all 3,780 files and 13,126,729,992 bytes against saved sizes/hashes, then removed the private fixture; see `artifact://production-rust-full-restore-20261008`.

<!-- docs:section risks -->
## Ryzyka i następny krok

Attempts start every 300 seconds by default; slower captures delay subsequent starts. Active files can make a capture fail; previous completed copies remain. Two final service captures started 299.995729 seconds apart; later capture took 23.198 seconds during restore load. The known corrupt Agy source remains unchanged. Same-machine snapshots do not survive disk loss. Next: provider/IDE resume and protected publication after governance adoption and independent review.
