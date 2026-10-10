# wellmanifest.usermanual/v1 — recovery interface

Queries never transfer files or start agents. Commands have explicit effects.
Static `GET /` serves the documented interface and is excluded from business
route comparison. All business routes are declared by `GET /api/registry`.

| Kind | Method and path | Input | Output / effect |
| --- | --- | --- | --- |
| Query | `GET /health` | None | `{status: ok, app: uncrash-recovery}` without external calls |
| Query | `GET /api/registry` | None | Complete query/command route list |
| Query | `GET /api/sessions` | None | Bounded configured inventory; socket availability only |
| Query | `GET /api/backend` | None | Configured loopback dashboard URL |
| Command | `POST /api/transfer/plan` | `{}` | Hash file; store bounded ephemeral confirmation; no SSH |
| Command | `POST /api/transfer/apply` | `{token: string}` | Consume confirmation once; verify file, upload and store backend receipt |

POST requires `Content-Type: application/json`, `Origin` equal to this
loopback server origin, and a recognized loopback Host header. Request bodies
are bounded to 4096 bytes. Unknown parameters are rejected. Host and file path
come from operator configuration, never the request. A changed or expired
plan, invalid receipt or failed backend returns HTTP 409. A forbidden origin
or host returns HTTP 403. Undeclared routes return HTTP 404. Error responses
contain no backend stderr, prompt bodies, credentials or shell commands.

On success, apply returns `{transferred: true, sha256, host, receipt,
applicationsLaunched: false}`. The receipt proves only what the backend
observed. An unsigned observation is not independent approval or a signed
Willman ExecutionReceipt. Process identity is
`process://local/apps/uncrash-recovery/server.py`; the private PID record is
under the runtime state directory. GUI selection is held in URL query
parameters `tab` and `session`, with `theme` retained across transitions.
