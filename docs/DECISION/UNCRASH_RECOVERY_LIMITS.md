---
{
  "schema": "wellmanifest.docs/document/v2",
  "id": "uncrash-recovery-limits",
  "kind": "decision",
  "version": 1,
  "title": "Uncrash recovery limits and safety",
  "status": "accepted",
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

# Uncrash recovery limits and safety

<!-- docs:section summary -->
## Cel i rezultat

Restore durable application files into separate recovery directories and launch only explicit current configuration. Report fidelity per application, with full session recovery requiring native assertions.

<!-- docs:section details -->
## Zakres i rozwiązanie

Opening an application window, splash or welcome dialog verifies launch only. It does not demonstrate restoration of editor tabs, unsaved documents, terminal history, provider chat context or process memory. The Chrome fixture verifies two native saved tabs and localStorage. The xterm fixture verifies saved-file replay; it does not resurrect the previous shell or PTY.

Tests use synthetic profiles on dedicated Twinerd NativeClone desktops and real noVNC/RFB rendering. Application fixtures use namespaces, read-only host OS, private HOME/runtime, private D-Bus and an offline network namespace. This shares the host kernel and is not a complete machine snapshot or VM. Snap, system D-Bus, GNOME desktop services, licensing and GPU prerequisites can prevent a window in this environment.

Never close unrelated user applications during tests. Stop only recorded owned PID identities, and clean up the dedicated Twinerd test desktop through its own controller. Ordinary application data may be encrypted even when it contains sensitive text; credential filename exclusions are a bounded precaution, not a semantic secret scanner.

<!-- docs:section validation -->
## Weryfikacja

Recovery unit tests check byte roundtrip, quarantine preservation, integrity, startup selection, bounds and PID identity. Every inventoried desktop launcher receives an explicit tested or pending status. Session-level assertions are recorded separately from generic data/window checks in the [application matrix](../ANALYSIS/UNCRASH_APPLICATION_MATRIX.md).

<!-- docs:section risks -->
## Ryzyka i następny krok

Native durable session-file/settings backups are active for four selected profiles. This does not demonstrate restored provider conversations or JetBrains terminal tabs. Two complete captures started five minutes apart; the configured 8 GiB budget holds about two current full copies. Universal deep restoration is unfinished. Native JetBrains terminal-tab and Codex/Claude/Agy adapters require format/version-specific work and genuine resumed-session tests. CloneBox FULL restored memory-only text in an owned synthetic BIOS VM through Uncrash and actual noVNC. A second minimal Linux/BusyBox guest restored a real shell/PTY with the same PID, PTY name and memory-only variable. Installed GUI apps and host PyCharm recovery remain unverified. See [local backends](../ANALYSIS/UNCRASH_LOCAL_RECOVERY_BACKENDS.md). Publication remains subject to adoption gates and independent protected review.
