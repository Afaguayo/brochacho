#!/usr/bin/env bash
# Brochacho installer for macOS. Run in Terminal:
#   curl -fsSL https://raw.githubusercontent.com/Afaguayo/brochacho/main/install.sh | bash
# Downloads the brochacho program from the latest release and starts the setup wizard.
set -euo pipefail
case "$(uname -m)" in
  arm64) ASSET=brochacho-macos-arm64 ;;
  *)     ASSET=brochacho-macos-x64 ;;
esac
DIR="$HOME/.brochacho/bin"
mkdir -p "$DIR"
echo "Downloading Brochacho ($ASSET)..."
curl -fL --progress-bar "https://github.com/Afaguayo/brochacho/releases/latest/download/$ASSET" -o "$DIR/brochacho"
chmod +x "$DIR/brochacho"
xattr -d com.apple.quarantine "$DIR/brochacho" 2>/dev/null || true
exec "$DIR/brochacho" setup < /dev/tty
