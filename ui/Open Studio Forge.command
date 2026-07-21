#!/bin/bash
# Studio Forge — desktop control (double-click or launched by Studio Forge.app)
DIR="$(cd "$(dirname "$0")/.." && pwd)"
export STUDIO_FORGE=1
export STUDIO_FORGE_ENGINE="$DIR"
PORT="${STUDIO_FORGE_PORT:-8765}"
URL="http://127.0.0.1:${PORT}"

echo "Starting Studio Forge…"

# Vision (optional)
OLLAMA_BIN=""
for c in /usr/local/bin/ollama /opt/homebrew/bin/ollama \
         "/Applications/Ollama.app/Contents/Resources/ollama" \
         "$(command -v ollama 2>/dev/null)"; do
  if [ -n "$c" ] && [ -x "$c" ]; then OLLAMA_BIN="$c"; break; fi
done
if [ -n "$OLLAMA_BIN" ]; then
  if ! curl -sf --max-time 1 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    [ -d "/Applications/Ollama.app" ] && open -a Ollama >/dev/null 2>&1 || true
    "$OLLAMA_BIN" serve >/dev/null 2>&1 &
  fi
fi

# Restart server so Studio Forge branding applies
pkill -f "$DIR/ui/server.py" >/dev/null 2>&1 || true
sleep 0.3

PY="$DIR/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
PORT="$PORT" STUDIO_FORGE=1 "$PY" "$DIR/ui/server.py" >/tmp/studio-forge-server.log 2>&1 &
SERVER_PID=$!
echo $SERVER_PID > /tmp/studio-forge-server.pid

for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
  curl -sf --max-time 1 "$URL/api/session" >/dev/null 2>&1 && break
  sleep 0.35
done

# Desktop window: Chrome/Edge app mode, else browser
if [ -d "/Applications/Google Chrome.app" ]; then
  open -na "Google Chrome" --args --new-window --app="$URL"
elif [ -d "/Applications/Microsoft Edge.app" ]; then
  open -na "Microsoft Edge" --args --new-window --app="$URL"
else
  open "$URL"
fi

echo ""
echo "  ✦ Studio Forge is running."
echo "  ✦ Keep this window open while you work."
echo "  ✦ Close it (or press Ctrl-C) to stop."
echo ""
wait $SERVER_PID
