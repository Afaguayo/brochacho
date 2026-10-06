#!/usr/bin/env bash
# Starts Brochacho: a Claude Code session in your vault that listens to your Discord bot.
#   BROCHACHO_VAULT=~/notes ./start-brochacho.sh      # folder Claude works in
#   ./start-brochacho.sh --stay-awake                  # keep the Mac awake while it runs
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
VAULT="${BROCHACHO_VAULT:-$HOME/Documents/SecondBrain}"
[ -d "$VAULT" ] || VAULT="$PWD"
STAY_AWAKE=0
[ "${1:-}" = "--stay-awake" ] && STAY_AWAKE=1

printf '\033]0;Brochacho\007'
export PATH="$HOME/.bun/bin:$HOME/.local/bin:/opt/homebrew/bin:$PATH"

# Only one Brochacho per machine: two sessions on one bot token would both answer.
LOCK="${TMPDIR:-/tmp}/brochacho.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "Brochacho is already running on this Mac (remove $LOCK if it isn't)."; exit 0
fi
trap 'rmdir "$LOCK"' EXIT

for tool in bun claude; do
  command -v "$tool" >/dev/null || { echo "$tool is not installed. Run macos/install.sh first."; exit 1; }
done
if [ ! -f "$HOME/.claude/channels/discord/.env" ] && [ -z "${DISCORD_BOT_TOKEN:-}" ]; then
  echo "No bot token yet. Run macos/setup.sh first."; exit 1
fi

PERSONA="$(cat "$REPO/brochacho.md")

This machine: $(scutil --get ComputerName 2>/dev/null || hostname) (macOS). Wake tool: python3 \"$REPO/tools/wake.py\" <machine-name>"

cd "$VAULT"
[ -d .git ] && git pull --ff-only >/dev/null 2>&1 || true

cat <<EOF

  +------------------------------------------+
  |  BROCHACHO is on. DM the bot on Discord. |
  |  Close this window to turn it off.       |
  +------------------------------------------+
  vault: $VAULT

EOF

run() {
  if [ "$STAY_AWAKE" = 1 ]; then
    caffeinate -is claude --settings "$REPO/brochacho.settings.json" --channels plugin:discord@claude-plugins-official --permission-mode acceptEdits --append-system-prompt "$PERSONA"
  else
    claude --settings "$REPO/brochacho.settings.json" --channels plugin:discord@claude-plugins-official --permission-mode acceptEdits --append-system-prompt "$PERSONA"
  fi
}

# Restart after a crash or a dropped connection; a clean /exit (code 0) stops for good.
while true; do
  code=0; run || code=$?
  [ "$code" = 0 ] && break
  echo "Brochacho stopped (exit $code). Restarting in 10 s; close the window to cancel."
  sleep 10
done
