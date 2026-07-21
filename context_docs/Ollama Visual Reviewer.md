---
title: Ollama Visual Reviewer
type: note
tags: [auto-edit-forge, review, ollama, vision]
created: 2026-07-21
updated: 2026-07-21
summary: Hardwired Ollama vision — auto-start, model pull, watchdog. Not optional.
---
# Ollama Visual Reviewer

Back to [[Auto Edit Forge — HOME]] · [[Footage Review Engine]].

## Status — hardwired (2026-07-21)

Ollama is a **required** engine for AUTOEDITING FORGE, not an optional skip.

On launch (`ui/Open AUTOEDITING FORGE.command` + `ui/server.py`):
1. Start Ollama if not listening (`Ollama.app` and/or `ollama serve`)
2. Pull `moondream` if missing
3. Background watchdog re-ensures every 60s if the process dies

Dashboard health treats Ollama as **critical** when down (same class as ffmpeg).

## Code

- `autoedit/vision.py` — `ensure_ollama()`, `require_ollama()`, `should_run_vision()` (auto-starts)
- Pre-edit via `review_session(..., ollama=True)`
- Post-edit → `out/qc_vision.json`
- Default `vision.enabled: on` (legacy `auto` → `on`)
- `AUTOEDIT_VISION=0` only for self-tests

## Config

```yaml
vision:
  enabled: on
  model: moondream
  base_url: http://127.0.0.1:11434
  timeout_sec: 45
  samples: 3
  qc_samples: 5
```

## Install once

https://ollama.com — after that the forge keeps it alive. Model `moondream` is pulled automatically.

## Golden rule in prompts

Recommend rotate / trim / flag blur·out-of-frame. **Never** recommend color grade or creative reframe.
