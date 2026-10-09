---
{
  "schema": "wellmanifest.docs/document/v2",
  "id": "uncrash-license-and-publication",
  "kind": "information",
  "version": 1,
  "title": "Apache licensing and public distribution",
  "status": "draft",
  "owner": "semcod/uncrash",
  "scope": "repository",
  "updated": "2026-10-09",
  "source_revision": "99601d769ca03236d8ed1249bda97451fe455d79",
  "priority": "P1",
  "evidence": [
    "artifact://license-audit-20261008",
    "artifact://license-continuation-intake-20261009",
    "artifact://apache-final-artifact-verification-20261009",
    "artifact://github-observation-20261009-apache"
  ]
}
---

# Apache licensing and public distribution

<!-- docs:section summary -->
## Cel i rezultat

Uncrash is intended as a public Python package licensed under Apache-2.0. A local installed service, a built wheel, a public GitHub repository and a package registry release are separate delivery effects. The public GitHub repository now exists and is anonymously readable; it is empty. Code push, protected review/merge and PyPI release remain incomplete.

<!-- docs:section details -->
## Zakres i rozwiązanie

Use the `opensource-python` profile from wellmanifest/license revision `49ed1f7c2d37fa26bce1cfc1c52ff76084e96842`. Its matrix prioritizes explicit user choice, then selects Apache-2.0 for public Python packages. Software owner: Tomasz Sapletta Prototypowanie.pl, NIP 5881918662, REGON 220665410. Preserve the owner notice in the profile's full license text.

Version 0.1.1 changes Python metadata from Proprietary to the SPDX expression `Apache-2.0`. `project.license-files = ["LICENSE"]` includes the root license in wheel and source distributions. SPDX expressions require setuptools 77 or later; this is a build dependency, not a runtime dependency. Root LICENSE is staged in governance ticket-003 and included in the verified artifacts. Integration ticket-001 owns metadata/docs; application ticket-002 synchronizes module version.

The proprietary anti-mining profile is a separate option and is not applied to this Apache distribution. External dependencies keep their own licenses. The wheel contains authored Python/Rust/systemd files and the environment example; installed PyCharm, noVNC, Twinerd, OpenSSL and zlib are not bundled or relicensed. A full transitive dependency legal review is not implied by artifact inspection.

<!-- docs:section validation -->
## Weryfikacja

The earlier 0.1.0 wheel declared Proprietary and had no license file. Inspect the new wheel metadata for License-Expression and License-File, and compare its packaged license bytes with the pinned standard template. Both final artifacts pass these checks, including payload hashes. Installed module and distribution report 0.1.1 / Apache-2.0. Fresh recovery/native regression: 56 passed, one optional systemd skip; noVNC was not repeated for this version-only change.

Publication requires governance adoption, a protected repository profile and independent Validator approval of the current commit. Repository creation was authorized by the requested public delivery. Anonymous GitHub metadata now returns HTTP200/public. No code was uploaded. Current protected preflight still reports PUBLICATION_PROFILE_MISSING; adoption gate still rejects unresolved/adopter required checks.

<!-- docs:section risks -->
## Ryzyka i następny krok

Apache licensing of code grants no right to publish captured sessions, LocalHistory, private .env files or credentials. Build from an explicit authored-source allowlist. Continue the linked license task, verify artifacts and use the declared protected delivery controller for publication and merge. PyPI publishing is not configured by the GitHub publication request.
