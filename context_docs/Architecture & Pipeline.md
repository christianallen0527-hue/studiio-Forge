---
title: Architecture & Pipeline
type: note
tags: [auto-edit-forge, architecture, code]
created: 2026-07-17
updated: 2026-07-17
summary: The pipeline stages and the code modules that implement them.
---
# Architecture & Pipeline

Back to [[Auto Edit Forge — HOME]].

## Flow
```
footage → REVIEW → sync → decide cuts → mix audio → transcribe → remove fillers/pauses
        → titles/intro/sponsor/outro → assemble (transitions+fades) → shorts → deliver
```

## Code modules (`autoedit/`)
| Module | Job |
|---|---|
| `review.py` | **Footage Review** — watches clips before editing. See [[Footage Review Engine]]. |
| `sync.py` / `audiotools.py` | Audio cross-correlation sync across cameras/mics; RMS loudness envelopes. |
| `switch.py` | Multi-cam decision — cut to whoever's talking, wide on cross-talk (loudness + hysteresis). |
| `transcribe.py` | faster-whisper → word-level timings + caption cues. |
| `refine.py` | Filler-word + pause removal from the transcript. |
| `silence.py` | Silent-air detection + interval subtraction. |
| `titles.py` / `textgen.py` | Pillow-rendered title/ending cards (this ffmpeg has no drawtext); master-audio mixing. |
| `assemble.py` | **ffmpeg render** — straight edit (keep framing) + operator path. Now with **cross-dissolves, fade in/out, per-angle 180° rotate, audio-normalize -14 LUFS**. |
| `resolve_backend.py` | DaVinci Resolve build+render (reads BRAW). See [[Resolve & BRAW]]. |
| `shorts.py` | Pick highlights → vertical 9:16 shorts with burned-in captions. |
| `ingest.py` | Watches network/recording folders + freshly-plugged SSDs → auto-inbox. |
| `pipeline.py` | Orchestrates all stages (`run()`), writes `editlist.json`, remaps shorts through edits. |
| `config.py` | YAML → `Config` dataclass. All the knobs. |
| `operator.py` / `facetrack.py` / `grade.py` | **Present but OFF by default** — punch-in "camera operator", face-tracking, color-grade. Kept in code, NOT used (see [[Roadmap & Rules]]). |

## Editorial finishing (in `assemble.render`, config-driven)
- `transitions` (default on), `transition_sec` (0.5) — cross-dissolve every clip/segment (`xfade` + `acrossfade`).
- `fade_sec` (0.5) — fade in from black / out to black (`fade` + `afade`).
- `audio_normalize` (default on) — `loudnorm=I=-14:TP=-1.5`.
- `Angle.rotate` (0 or 180) — corrects an upside-down camera (`vflip,hflip`).
- `intro_video` / `sponsor_video` / `outro_video` — extra clips that also participate in the dissolves.

## Config sections (YAML → `config.py`)
`angles[]` (name/video/mic/rotate), `switch`, `sync`, `silence`, `refine`, `title`, `intro`/`sponsor`/`outro`, `finish` (transitions/fades/audio_normalize), `transcribe`, `shorts`, `output` (backend ffmpeg|resolve, render, grade=false, project_name).

## Entry points
- `edit.py project.yaml` — CLI (uses `os._exit` to dodge a Resolve teardown segfault).
- `ui/server.py` — Flask app driving the pipeline per job. See [[EDITING FORGE UI]].
- `selftest.py` — unit tests (offsets, switching, filler/pause, operator, ingest, face-track framing).
