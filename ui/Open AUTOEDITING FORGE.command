#!/bin/bash
# Double-click this to open AUTOEDITING FORGE.
# Starts Ollama (vision engine) + the local UI, then opens the browser.
DIR="$(cd "$(dirname "$0")/.." && pwd)"
echo "Starting AUTOEDITING FORGE…"

# Hardwired vision: bring Ollama up before the UI (idempotent if already running).
OLLAMA_BIN=""
for c in /usr/local/bin/ollama /opt/homebrew/bin/ollama \
         "/Applications/Ollama.app/Contents/Resources/ollama" \
         "$(command -v ollama 2>/dev/null)"; do
  if [ -n "$c" ] && [ -x "$c" ]; then OLLAMA_BIN="$c"; break; fi
done
if [ -n "$OLLAMA_BIN" ]; then
  if ! curl -sf --max-time 1 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    echo "  ▸ starting Ollama…"
    if [ -d "/Applications/Ollama.app" ]; then
      open -a Ollama >/dev/null 2>&1 || true
    fi
    "$OLLAMA_BIN" serve >/dev/null 2>&1 &
    for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
      curl -sf --max-time 1 http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break
      sleep 0.5
    done
  fi
  # Ensure vision model is present (no-op if already pulled).
  "$OLLAMA_BIN" list 2>/dev/null | grep -q '^moondream' \
    || "$OLLAMA_BIN" pull moondream
  echo "  ▸ Ollama vision ready"
else
  echo "  ✗ Ollama not found — install from https://ollama.com"
fi

"$DIR/.venv/bin/python" "$DIR/ui/server.py" &
SERVER_PID=$!
sleep 2
open "http://127.0.0.1:8765"
echo ""
echo "  ✦ AUTOEDITING FORGE is running in your browser."
echo "  ✦ Keep this window open while you work."
echo "  ✦ Close it (or press Ctrl-C) to stop."
echo ""
wait $SERVER_PID
