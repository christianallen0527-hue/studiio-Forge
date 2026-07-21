---
title: EDITING FORGE UI
type: note
tags: [auto-edit-forge, ui]
created: 2026-07-17
updated: 2026-07-17
summary: The powerful, beautiful interface and its API.
---
# EDITING FORGE UI

Back to [[Auto Edit Forge — HOME]]. Code: `ui/index.html` + `ui/server.py` (Flask, local, `127.0.0.1:8765`).

## Identity
Named **EDITING FORGE**. Dark, premium, cinematic — a "forge" look: near-black backgrounds, **molten ember-orange** (`#ff6a2b`) primary + warm gold secondary, subtle glow/heat, tasteful motion. Single self-contained HTML file (inline CSS/JS, no external calls). Human-centered and easy; powerful under the hood.

## Flow (2026-07-21)
0. **Login** (only if `AUTOEDITING_FORGE_PASSWORD` set) — session cookie; 401 → login.
1. **Home dashboard** — health (ffmpeg / Ollama / Python / Resolve / disk), active + recent jobs, issues, inbox strip, primary CTA **Start a new automated edit**.
2. **Mode** — keep-framing edit vs multi-cam.
3. **Setup** — footage, title/subtitle, editorial options, Advanced.
4. **Review** ⭐ — `/api/review` per-clip findings (+ vision when Ollama ready). See [[Footage Review Engine]].
5. **Forge** — live stages, console, shot map; can return home while it runs.
6. **Delivered** — episode, stats, shorts, downloads.

## To launch (for Christian)
Double-click **`ui/Open Auto Edit.command`** in the project folder → opens EDITING FORGE in the browser. Everything runs locally on the Mac.

## Identity note
Product branding is **AUTOEDITING FORGE** (docs may still say EDITING FORGE historically).

## API (Flask, in `server.py`)
- `GET /api/session` → `{auth_required, authenticated}` (auth only if `AUTOEDITING_FORGE_PASSWORD` set).
- `POST /api/login` → `{password}`; session cookie (HttpOnly, SameSite).
- `POST /api/logout`
- `GET /api/dashboard` → health (ffmpeg/Python/Resolve/disk), active/recent jobs, reviews, progress, issues, UTC timestamps.
- `GET /api/home` → starting folders to browse.
- `GET /api/scan?dir=` → folder contents (dirs/videos/audios).
- `GET /api/inbox` → auto-detected sessions.
- `POST /api/review` → runs `review.review_session`, returns per-clip findings.
- `POST /api/run` (JSON cfg) → starts an edit job; cfg fields: mode, title/subtitle, angles, remove_fillers/pauses, silence, shorts, render, backend (ffmpeg|resolve), model, shorts_count, pause_sec, project_name. **grade stays false.**
- `GET /api/job/<id>` → {state, log, stage_line, outputs, shotmap, stats}.
- `GET /api/media?path=` → serve rendered video/shorts (sandboxed to reported outputs).

When password is set, sensitive `/api/*` routes require login; static UI stays public. Optional: `AUTOEDITING_FORGE_SECRET_KEY`, `AUTOEDITING_FORGE_SECURE_COOKIE=true`.

## Notes
- Color-grade + reframe controls were intentionally **removed** from the UI (not the editor's job — see [[Roadmap & Rules]]).
- Built partly by a background agent; keep the exact cfg/endpoint contract when editing.
