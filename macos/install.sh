#!/usr/bin/env bash
# Installs Brochacho on macOS: Bun, the Discord channel plugin, a Brochacho.command on the Desktop,
# and this Mac's entry in ~/.brochacho/machines.json for Wake-on-LAN.
#   ./install.sh [--stay-awake]
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
FLAG="${1:-}"
export PATH="$HOME/.bun/bin:$PATH"

command -v bun >/dev/null || { echo "Installing Bun..."; curl -fsSL https://bun.sh/install | bash; }
command -v claude >/dev/null || { echo "Claude Code is not installed: https://code.claude.com/docs/en/quickstart"; exit 1; }
if ! claude plugin list | grep -q "discord@claude-plugins-official"; then
  claude plugin marketplace add anthropics/claude-plugins-official || true
  claude plugin install discord@claude-plugins-official --scope user
fi

chmod +x "$REPO/macos/"*.sh "$REPO/tools/wake.py"
CMD="$HOME/Desktop/Brochacho.command"
printf '#!/bin/bash\nexec "%s/macos/start-brochacho.sh" %s\n' "$REPO" "$FLAG" > "$CMD"
chmod +x "$CMD"
echo "Desktop launcher: $CMD"

# Register this Mac for Wake-on-LAN (prefers the interface of the default route).
IFACE="$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')"
if [ -n "$IFACE" ]; then
  MAC="$(ifconfig "$IFACE" | awk '/ether/{print $2}')"
  BCAST="$(ifconfig "$IFACE" | awk '/broadcast/{print $NF}')"
  NAME="$(scutil --get LocalHostName 2>/dev/null | tr '[:upper:]' '[:lower:]')"
  python3 - "$NAME" "$MAC" "${BCAST:-255.255.255.255}" <<'PY'
import json, sys
from pathlib import Path
name, mac, bcast = sys.argv[1:]
cfg = Path.home() / ".brochacho" / "machines.json"
cfg.parent.mkdir(exist_ok=True)
data = json.loads(cfg.read_text()) if cfg.exists() else {}
data[name] = {"mac": mac, "broadcast": bcast, "os": "macos"}
cfg.write_text(json.dumps(data, indent=2))
print(f"Registered '{name}' ({mac}) in {cfg}")
PY
fi

cat <<EOF

To start at login: System Settings > General > Login Items > + > pick Brochacho.command.
To let other machines wake this Mac: System Settings > Battery (or Energy) > Options >
"Wake for network access" (laptops: only while on power).
EOF
[ -f "$HOME/.claude/channels/discord/.env" ] || echo "Next: run macos/setup.sh to add your bot token."
