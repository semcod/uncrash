#!/usr/bin/env bash
set -euo pipefail

# Find uncrash command or Python with uncrash installed
if command -v uncrash >/dev/null 2>&1; then
    UNCRASH_CMD=(uncrash)
elif [[ -x "/home/tom/github/twinerd/twinerd/venv/bin/python" ]]; then
    UNCRASH_CMD=("/home/tom/github/twinerd/twinerd/venv/bin/python" -m uncrash.cli)
elif [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
    UNCRASH_CMD=("${VIRTUAL_ENV}/bin/python" -m uncrash.cli)
elif command -v python3 >/dev/null 2>&1; then
    UNCRASH_CMD=(python3 -m uncrash.cli)
else
    echo "Error: Python or uncrash not found" >&2
    exit 1
fi

if [[ "${1:-}" == "--list" || "${1:-}" == "-l" || "${1:-}" == "list" ]]; then
    exec "${UNCRASH_CMD[@]}" apps
fi

target="${1:-pycharm}"

if ! "${UNCRASH_CMD[@]}" close-app "$target" "${@:2}"; then
    echo ""
    echo "Wykryte otwarte aplikacje okienkowe użytkownika:"
    "${UNCRASH_CMD[@]}" apps
    echo ""
    echo "Aby zamknąć wybraną aplikację: $0 <PID_lub_nazwa>"
fi
