---
title: Footage Review Engine
type: note
tags: [auto-edit-forge, review, ai]
created: 2026-07-17
updated: 2026-07-17
summary: The AI that watches the clips BEFORE editing — the critical piece.
---
# Footage Review Engine  ⭐

Back to [[Auto Edit Forge — HOME]]. Code: `autoedit/review.py`.

Christian's words: *"i need an ai thats going to review the footage before the edit is done so it knows what it's dealing with. that part is critical / huge. it must watch the clips beforehand, recommend edits, then go into the edit."*

## What it detects (per clip, deterministic = precise, not guessing)
- **Audio loudness** — EBU R128 integrated LUFS + true peak → verdict: `good` / `quiet` / `loud` / `silent`. Target = **-14 LUFS**.
- **Orientation** — container rotate tag, else a **YuNet face vote at 0° vs 180°** → flags **upside-down** (correctly caught the inverted BRAW).
- **Black / dead frames** — keyframe-only `blackdetect` → unusable ranges.
- **Content read** — talking-head vs b-roll (no audio) vs unusable.
- **Recommendations** — per-clip plain-language fixes.
- **Optional vision** — a local **Ollama** model (`moondream`) describes a frame, if installed.

## Turning findings into actions
- `analyze(path)` → the full report dict (18 keys).
- `review_session(paths)` → `{clips:[...], usable, total, fixes}`.
- `apply_review(clip)` → concrete decisions: `{rotate: 0|180, audio_gain_db, trim_ranges, add_music}`.
- `apply_session(session)` → list of the above.

Example (the upside-down clip): `{"rotate":180, "audio_gain_db":33.4, "trim_ranges":[], "add_music":false}`.

## Performance (important — it was 88s, now fast)
The killer bug: `_meta_rotation` used ffprobe `side_data=rotation`, which **fully decoded** the 4K HEVC clip (~83s). Fixed to `stream_side_data=rotation` → **0.03s**. Audio uses `-vn` (audio-only). Black/orientation use fast keyframe seeks + a cached YuNet model.
- Upside-down clip: **~0.9s**. 4K clip: **~3.4s**. (`AUTOEDIT_PROFILE=1` prints per-phase timings.)

## How it plugs in
The UI shows the review panel before the edit (`POST /api/review`). On forge, `pipeline.run` **re-runs review automatically** before sync, writes `out/review.json`, and applies:
- per-angle **180°** (ffmpeg + Resolve)
- peak-safe **mic gain** for switching/mix/render
- **consensus-only** black/dead head/tail trims (all cameras agree after sync offsets; ≥0.25s)

Silent b-roll music and interior black cuts are still deferred. Vision layer: see [[Ollama Visual Reviewer]].
