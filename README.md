# uncrash

`uncrash` is a local Python service for preserving recoverable state around
JetBrains IDEs, terminal programs, and coding-agent conversations. It is being
built to record safe launch and session references continuously, then produce
a deliberate recovery plan after an application or desktop crash.

The service is intended to run as a `systemd --user` unit with automatic
restart. Recovery records stay on this machine with restrictive permissions.
The design will distinguish state that can be resumed from a transcript from
process memory or terminal contents that cannot be reconstructed after a crash.

Repository mode: standalone Python package; runtime owner: `semcod`.

Project implementation and recovery limits are tracked in the governed ticket
index at [`project/TICKETS.md`](project/TICKETS.md).
