---
{
  "schema": "wellmanifest.docs/document/v2",
  "id": "uncrash-service-operations",
  "kind": "service",
  "version": 2,
  "title": "Uncrash service operations",
  "status": "draft",
  "owner": "semcod/uncrash",
  "scope": "repository",
  "updated": "2026-10-09",
  "source_revision": "4f01b1c8508e524c43965ba798a6a850d5d5ab08",
  "priority": "P1",
  "evidence": [
    "artifact://ticket-001",
    "artifact://ticket-002",
    "artifact://uncrash-tests-20261008"
  ]
}
---

# Uncrash service operations

<!-- docs:section summary -->
## Cel i rezultat

Uncrash uses the Twinerd Python environment and a systemd user service with Restart=always. Five selected profiles cover Codex/Claude/Agy files, JetBrains settings and LocalHistory. A running service does not prove that backups succeed. Provider resumption and terminal-tab restoration remain unverified.

<!-- docs:section details -->
## Zakres i rozwiązanie

Install a verified wheel and run `uncrash install-user`. The installer preserves configuration and creates a private user unit. Configuration and environment overrides are loaded at startup; restart only `uncrash.service` after a configuration or package change.

Inspect profiles with `uncrash profiles`; explicitly select authorized IDs using `--select ID --apply`. Selection preserves the previous configuration and does not launch applications. Five-minute scheduling, optional encryption and effective byte budgets are described in [Rust settings](UNCRASH_RUST_AND_ENVIRONMENT.md). Production overrides select plaintext Rust copies, 300 seconds, 512 MiB/file, 16 GiB/snapshot and 32 GiB allocated storage.

Use `systemctl --user status uncrash.service`, its journal and `uncrash diagnose --output NEW_PRIVATE_DIRECTORY`. Diagnostic freshness is based on the newest checksum-verified plaintext manifest, not service status. `uncrash snapshot` requests an immediate capture. Restore into a separate directory with `uncrash restore latest --destination NEW_DIRECTORY`.

Version 0.1.2 writes canonical, hash-chained `wellmanifest.logs/event/v1` events into private hourly `logs/uncrash-YYYYMMDD-HH.jsonl` streams. Capture failures include fixed diagnostic codes without exception text. Packaged `uncrash/errors/{CODE}.md` runbooks explain remediation. Invalid log history is preserved and append is refused; the daemon reports logging failure separately from capture failure.

`uncrash apps --json` provides observed process identities. Whole-process close requires `uncrash close-app PID --start-ticks TICKS`; `--force` explicitly enables SIGKILL after SIGTERM timeout. This may close multiple windows. REST `/api/v1/apps/close` and MCP `uncrash_close_gui_app` require `pid` and `expected_start`. Name-only/default process selection is refused. For one supported X11 window use `window-close` with XID/PID/start identity. `pycharm close --dry-run` sends no signal.

Optional REST and MCP servers use `uncrash serve` and `uncrash mcp`. `uncrash stop-owned` controls only recorded recovery launches. Stop collection with `systemctl --user disable --now uncrash.service`.

Startup rollback requires explicit `startup_restore`, `recovery_destination` and optionally an existing X11 `recovery_display`. It restores files only without a display and does not create Twinerd VMs. Startup rollback is disabled on this host.

<!-- docs:section validation -->
## Weryfikacja

The diagnostic change passed 74 tests; nine optional integration/systemd/noVNC tests were skipped in this run. Earlier physical-file restore and noVNC evidence remains in the [application matrix](../ANALYSIS/UNCRASH_APPLICATION_MATRIX.md). An isolated current five-profile capture copied 13,317,593,714 logical bytes in 14.996 seconds. These results do not verify provider UI restoration.

Earlier restored SQLite integrity checks found one corrupt Agy database in both source and snapshot. Hash equality preserves corruption; never present a file checksum as database integrity. See [storage limits](../INFORMATION/UNCRASH_PRIVACY_AND_STORAGE.md).

<!-- docs:section risks -->
## Ryzyka i następny krok

No service runs during power loss. Recovery uses the last completed copy; slow or failed captures can exceed five minutes. Source metadata and summary rows do not prove recoverability. Keep local reports private and preserve existing snapshots. Owner: semcod/uncrash. The deployed 0.1.2 wheel produced a fresh five-profile snapshot at 08:57 UTC (13,333,022,888 logical bytes; 16.068 seconds). Next: explicit conversation-to-tab attachment and independent publication review.
