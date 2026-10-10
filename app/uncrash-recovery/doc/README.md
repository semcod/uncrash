---
{
  "schema": "wellmanifest.docs/document/v1",
  "id": "uncrash-apx-recovery",
  "kind": "reference",
  "version": 1,
  "title": "Uncrash recovery interface for Willmux",
  "status": "implemented",
  "owner": "semcod/uncrash",
  "created": "2026-10-10",
  "updated": "2026-10-10",
  "review_after": "2026-11-10",
  "source_revision": "working-tree",
  "affected_repositories": ["semcod/uncrash"],
  "evidence": ["repo://semcod/uncrash/app/uncrash-recovery/server.py"]
}
---

# Recovery interface

<!-- docs:section purpose -->
Expose existing recovered sessions through an APX application that can occupy
a Willmux window, and transfer one explicitly configured portable bundle.

<!-- docs:section scope -->
This native-process adapter is owned by semcod/uncrash. It composes
wellmanifest/apx, gui, ssot, usermanual and logs. It does not implement a second
snapshot engine, change application ownership or replace a live conversation.

<!-- docs:section evidence -->
See `tests/test_server.py` for changed-file rejection, single-use confirmation,
expiry, same-origin enforcement and exact backend receipt binding. The APX
checker verifies packaging and `/health`; that check does not prove signed
execution receipts or sandbox isolation.

<!-- docs:section content -->
Use a compatible Uncrash installation exposing `bundle-transfer` and
`uncrash.events.append_event`. The verified local runtime currently uses the
recovery implementation from ticket-007; that implementation is still in an
open PR and must be integrated before a production rollout of this adapter.
Check `uncrash --help` for `bundle-transfer`. Start its Uncrash backend
separately; the dashboard remains available even without this app.

```bash
python app/uncrash-recovery/server.py --sessions-file /private/sessions.json \
  --bundle /private/recovery.tar --host tom@minis
```

The inventory is a private JSON array containing `conversation_id`, `cwd`,
`novnc_url`, `mode` and `fidelity`. Inventory URLs must be loopback HTTP.
Both the adapter state directory and input files must belong to the caller
and have no group/world permissions or symlinks. Runtime state defaults to
`~/.local/state/uncrash-apx`. The bundle is limited to 128 MiB. Review the
permission resources in `apx.yaml` for the selected deployment paths.

Willmux can open the running adapter with:

```text
view B "url:http://127.0.0.1:18893/"
```

An owning Willmux ticket can register a `kind: web` catalog item with id
`uncrash-recovery`, this URL and aliases `uncrash` / `odzyskiwanie`. Its per-node
override is `WILLMUX_APP_UNCRASH_RECOVERY_URL`. No catalog is edited by this
adapter. Across hosts, resolve URLs at the viewer host or use explicitly
configured authenticated tunnels; loopback is relative to the browser host.

The transfer panel first hashes the selected file and shows its destination,
size and digest. Confirmation expires after 120 seconds and is single-use.
The adapter checks file identity again, uploads a verified private copy using
the existing `uncrash bundle-transfer`, and checks the returned hash and host.
Only confirmation performs SSH. A successful transfer does not import or run
the remote application. Failure after upload may leave the remote inbox
populated; inspect its receipt before requesting another transfer.

<!-- docs:section limitations -->
X11/noVNC is a display transport, not process or filesystem isolation. There
is no live RAM/PTY recovery here. The adapter relies on the explicitly selected
Uncrash environment for transfers and logging. Runtime inventory is not a
source of conversation-to-process ownership authority. Signed Willman receipts,
Dockuri routing, container packaging and complete GUI conformance remain
separate integrations. No protected policy or new remote authority is granted
by the manifest or a successful local checker. Fixos has not been wrapped or
executed by this application.

<!-- docs:section next_actions -->
Register the adapter in Willmux under a bounded owning ticket, connect a
protected receipt signer where required, and implement a distinct Fixos APX
adapter with explicit diagnosis-versus-repair commands. Keep each deployment's
resources and endpoints aligned with its local SSOT.
