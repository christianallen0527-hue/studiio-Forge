#!/bin/zsh
# AUTOEDITING FORGE — daily editorial learning
# Studies top podcasts / talking heads / long-form / shorts into the brain.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
if [[ ! -x "$PY" ]]; then PY="$(command -v python3)"; fi
"$PY" -m autoedit.learning daily --per-category 3
echo "Done. See context_docs/obsidian/Daily Learning Journal.md"
