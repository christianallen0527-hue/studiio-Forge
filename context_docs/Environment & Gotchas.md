---
title: Environment & Gotchas
type: note
tags: [auto-edit-forge, environment, gotchas]
created: 2026-07-17
updated: 2026-07-21
summary: Paths, NAS storage, TCC quirks, ffmpeg, venv, Ollama — read before touching the code.
---
# Environment & Gotchas

Back to [[Auto Edit Forge — HOME]]. **Read this before editing/running the system.**

## Storage (Studio Files NAS — mandatory)
- **Permanent storage:** `/Volumes/Studio Files/AUTOEDITING FORGE Inbox` + `…/AUTOEDITING FORGE Jobs`
- **Fast Mac staging only:** `~/Movies/AUTOEDITING FORGE Staging` (Camera Forge `BRAW_DEST`)
- Mac internal SSD is nearly full — do **not** park finished BRAW or job masters there. AUTOEDITING FORGE drains staging → NAS every ~30s. If the NAS is unmounted, ingest refuses permanent Mac writes.
- See [[Camera Forge Ingest]].

## Paths
- Project root: `/Users/studio/Desktop/auto-edit-forge`
- Python venv: `/Users/studio/Desktop/auto-edit-forge/.venv/bin/python`

## macOS TCC (the big one)
- The Claude/agent **shell cannot READ** some `~/Desktop` top-level items and **external volumes** (`/Volumes/Studio Files`, TerraMaster, SSDs) → "Operation not permitted". It's TCC, not a sandbox (persists even with sandbox disabled).
- BUT: running the venv python / ffmpeg / git **inside** the project subfolder works; the **Read/Write tools** can access Desktop files; and **Resolve's MediaStorage API** reads external drives fine.
- Workarounds used: run from `~/Movies` (always readable); read external footage via Resolve; render to `~/Movies` then let Resolve (which has Full Disk Access) write to Desktop.
- **Permanent fix:** grant the Claude app **Full Disk Access** (System Settings → Privacy & Security → Full Disk Access), or move the project off the Desktop.
- Shell **cwd resets between commands** → always use absolute paths.

## ffmpeg
- Minimal Homebrew build: has libx264, `xfade`, `acrossfade`, `fade`, `afade`, `loudnorm`, `ebur128`, `blackdetect`, `colorchannelmixer`, `vflip/hflip`, `scale`, `overlay`.
- **Missing** `drawtext` / `subtitles` / `libass` → title cards + captions are **Pillow-rendered PNGs** composited via `overlay` (`textgen.py`).
- Cannot read `.braw` (use [[Resolve & BRAW]]).
- Put it on PATH: `export PATH=/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin`.

## Ollama (optional vision)
- Installed (`/usr/local/bin/ollama`, v0.32.x). Model **`moondream`** pulled (~828MB). Serves at `127.0.0.1:11434`.
- Used only as an optional semantic layer in [[Footage Review Engine]]; everything works without it.

## OpenCV note
- OpenCV 5.0 dropped `CascadeClassifier`; use `cv2.FaceDetectorYN` with `models/yunet.onnx`. Harmless objc "libavdevice implemented in both av and cv2" warning at import.

## Live-feed / OBS (separate track)
- Live "auto producer" (video-follows-audio) built as `~/Movies/ai_producer.py` (obs-websocket v5, loudest-mic-wins). ZowieBox live feed is RTSP at `192.168.1.221` (auth-gated — needs its login). Not required for the editor.
