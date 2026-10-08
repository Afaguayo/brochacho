#!/usr/bin/env bash
# Compatibility launcher for Brochacho.command files made by Brochacho 1.x. Brochacho is now one
# program (~/.brochacho/bin/brochacho); this starts it, or runs it from source with python3.
set -e
ARGS=(start); [ "${1:-}" = "--stay-awake" ] && ARGS+=(--stay-awake)
[ -n "${BROCHACHO_VAULT:-}" ] && ARGS+=(--vault "$BROCHACHO_VAULT")
BIN="$HOME/.brochacho/bin/brochacho"
[ -x "$BIN" ] && exec "$BIN" "${ARGS[@]}"
command -v python3 >/dev/null && exec python3 "$(cd "$(dirname "$0")/.." && pwd)/app/brochacho.py" "${ARGS[@]}"
echo "Brochacho is now one program. Install it with:"
echo "  curl -fsSL https://raw.githubusercontent.com/Afaguayo/brochacho/main/install.sh | bash"
