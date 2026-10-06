#!/usr/bin/env bash
# One-time bot setup: paste the bot token; this saves it and opens the invite page.
set -euo pipefail
echo; echo "=== Brochacho setup ==="; echo

read -rsp "Paste your Discord bot token (hidden): " TOKEN; echo
TOKEN="$(echo "$TOKEN" | tr -d '[:space:]')"
if ! [[ "$TOKEN" =~ ^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$ ]]; then
  echo "That doesn't look like a bot token (three parts separated by dots)."; exit 1
fi

DIR="$HOME/.claude/channels/discord"
mkdir -p "$DIR" && chmod 700 "$DIR"
printf 'DISCORD_BOT_TOKEN=%s\n' "$TOKEN" > "$DIR/.env" && chmod 600 "$DIR/.env"
echo "Token saved to $DIR/.env"

# A bot token's first part is the bot's ID in base64, which is also the application ID.
ID_PART="$(echo "${TOKEN%%.*}" | tr '_-' '/+')"
while [ $(( ${#ID_PART} % 4 )) -ne 0 ]; do ID_PART="$ID_PART="; done
APP_ID="$(echo "$ID_PART" | base64 -D 2>/dev/null || echo "$ID_PART" | base64 -d)"

open "https://discord.com/oauth2/authorize?client_id=$APP_ID&scope=bot&permissions=274878008384"
cat <<EOF
Opened the invite page: add the bot to a server you're in.

Last step:
 1. Start Brochacho (double-click Brochacho.command on your Desktop).
 2. DM your bot 'hi' on Discord. It replies with a pairing code.
 3. In the Brochacho window:  /discord:access pair <code>
 4. Then lock it to you:      /discord:access policy allowlist
EOF
