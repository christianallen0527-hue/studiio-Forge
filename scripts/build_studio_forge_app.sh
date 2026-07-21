#!/bin/zsh
# Rebuild + install Studio Forge.app to Desktop and /Applications
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/desktop_app/Studio Forge.app"
chmod +x "$SRC/Contents/MacOS/Studio Forge"
echo "/Users/studio/Desktop/auto-edit-forge" > "$SRC/Contents/Resources/engine.root"
rsync -a --delete "$SRC/" "$HOME/Desktop/Studio Forge.app/"
rsync -a --delete "$SRC/" "/Applications/Studio Forge.app/"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
  -f "$HOME/Desktop/Studio Forge.app" 2>/dev/null || true
echo "Installed:"
echo "  $HOME/Desktop/Studio Forge.app"
echo "  /Applications/Studio Forge.app"
echo "Double-click Studio Forge to launch."
