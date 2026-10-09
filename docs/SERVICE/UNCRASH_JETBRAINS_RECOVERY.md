---
{
  "schema": "wellmanifest.docs/document/v2",
  "id": "uncrash-jetbrains-recovery",
  "kind": "service",
  "version": 1,
  "title": "JetBrains inspection and portable file recovery",
  "status": "draft",
  "owner": "semcod/uncrash",
  "scope": "repository",
  "updated": "2026-10-08",
  "source_revision": "99601d769ca03236d8ed1249bda97451fe455d79",
  "priority": "P1",
  "evidence": [
    "artifact://pycharm-suite-20261008-final",
    "artifact://pycharm-relocated-file-verification-20261008",
    "artifact://pycharm-minis-transfer-test-20261008"
  ]
}
---

# JetBrains inspection and portable file recovery

<!-- docs:section summary -->
## Cel i rezultat

Inspect a frozen IDE without closing it. Save durable settings, LocalHistory and selected project metadata; relocate verified copies to separate directories or another machine. These copies do not contain live JVM memory, unsaved editor buffers, terminal PTYs or automatic provider resume.

<!-- docs:section details -->
## Zakres i rozwiązanie

`uncrash jetbrains` reports owned process identities, ancestor relationships, terminal paths and persisted opened-project records. `uncrash pycharm` (or the `close-last-pycharm` script/entrypoint) provides specialized inspection, graceful closure, and project restoration (`--restore`, `--close`, `--dry-run`), detecting both active and recently closed projects from `recentProjects.xml` and locating IDE binaries across PATH, Snap, and JetBrains Toolbox. Helper processes retaining JVM mappings are distinguished from root IDE candidates. Persisted XML can lag live windows. Wayland window counts are unverified. No terminal stream is read and no process signal is sent during inspection.

Enable `UNCRASH_JETBRAINS_METADATA=true` to record that inspection in each manifest. Register the optional `jetbrains-recovery` profile from `uncrash profiles` for LocalHistory/workspace files. Select project `.idea` and project source roots explicitly; this profile does not copy project sources automatically. LocalHistory may contain older sensitive content. Encryption remains optional and disabled by default.

```sh
uncrash bundle-export latest --destination /private/copy.tar
uncrash bundle-import /private/copy.tar --destination /private/new-store
uncrash --state /private/new-store --config /private/new-store/recovery-config.json restore latest --destination /private/restored
uncrash bundle-transfer /private/copy.tar --host tom@minis
```

Export pins a completed snapshot, copies declared payloads and verifies hashes. Import requires a new store, refuses unexpected members, traversal, links, duplicates and damaged content. It does not launch applications. Encrypted bundles require the original key through a separate channel; no key is included. SHA256 detects accidental corruption, without authenticating an untrusted sender.

SSH transfers an opaque private archive into `~/.local/state/uncrash-inbox`; strict known-host verification applies. The receiver checks exact length/digest and refuses overwrites. Python 3 is required remotely. Install Uncrash there, import into a new store, restore into separate paths and configure target-specific launch arguments before running apps. SSH transfer alone does not create a remote desktop or migrate live processes.

Window closure requires explicit X11 window ID, PID and start ticks via `window-close`; python-xlib is required. Wayland refuses closure because target identity cannot be verified. Default inspection never infers the latest window from focus or numeric window IDs.

<!-- docs:section validation -->
## Weryfikacja

Current combined suite: 63 passed, one optional systemd test skipped. Emergency real-data relocation verified 133 files / 86,166,986 bytes and private modes. Synthetic SSH transfer to minis passed; remote fixture removed, personal data remained local. Owned Twinerd/noVNC PyCharm showed User Agreement after file recovery. Editor visibility was false; no agreement was accepted automatically. Chrome saved tabs/localStorage, xterm file replay and owned VM RAM/PTY fixtures have separate proofs.

<!-- docs:section risks -->
## Ryzyka i następny krok

A copied profile may need compatible IDE versions, remapped project paths and user approval of fresh-profile agreements. Detached terminals/provider adapters and deep host IDE restoration remain unfinished. The updated local service captured five profiles / 3,786 files using Rust without encryption in 18.985 seconds; JetBrains metadata is present. `close_last_pycharm.sh` now defaults to inspection and refuses Wayland closure. Frozen production IDE was left running. Protected publication remains blocked by adoption, GitHub access and the absent independent Validator profile.
