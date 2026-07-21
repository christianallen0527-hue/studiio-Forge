---
title: Shorts Pipeline
type: note
tags: [auto-edit-forge, shorts, roadmap]
created: 2026-07-21
updated: 2026-07-21
summary: Implementation-ready Shorts pipeline — letterbox by default, crop only with explicit consent.
---
# Shorts Pipeline

Back to [[Auto Edit Forge — HOME]]. Product name: **AUTOEDITING FORGE**.

Design produced 2026-07-21 from current code (`autoedit/shorts.py`, `pipeline.py`, `config.py`, UI/API).

## Golden rule (critical)

Current Shorts **center-crop** 16:9 → 9:16. That conflicts with “preserve framing as shot.”

**Ship rule:** default `framing: fit` (letterbox/pillarbox). Any `crop_*` requires `allow_reframe: true` and an explicit UI checkbox. Never use face-track / punch-in / grade for Shorts. Rotate-180 from review remains the only automatic picture fix.

## Current gaps

- Silent center-crop (golden-rule conflict)
- Weak highlight selection (sentence heuristic only)
- Caption style limited; no word-timed mode
- UI/API only pass `enabled` + `count` (min/max/captions dropped)
- No `shorts_manifest.json`
- No Shorts unit tests in `selftest.py`

## Stages (post-assemble)

```
[S0] inputs: episode.mp4 + transcript + removals + intro_offset
[S1] score moments (word/cue windows, optional hook bias)
[S2] select package (non-overlap, platform clamps, diversity)
[S3] remap master → edited times
[S4] caption plan (Pillow PNGs)
[S5] render with framing policy
[S6] write MP4s + shorts_manifest.json (+ optional SRT)
```

## Config (target)

```yaml
shorts:
  enabled: true
  count: 5
  min_sec: 20.0
  max_sec: 60.0
  captions: true
  framing: fit              # fit | native | require_vertical | crop_center | crop_top | crop_bottom
  allow_reframe: false      # must be true for any crop_*
  platform: youtube_shorts  # youtube_shorts | tiktok | reels | generic
  prefer_questions: true
  prefer_hooks: true
  min_gap_sec: 8.0
  caption_mode: sentence    # off | sentence | words
  caption_style: outline    # outline | bar
  width: 1080
  height: 1920
```

Validation: `crop_*` without `allow_reframe` → clear `ValueError`.

## Platform presets

| Preset | max_sec | count | framing |
|---|---|---|---|
| youtube_shorts | 60 | 5 | fit |
| tiktok | 60 | 5 | fit |
| reels | 90 | 4 | fit |
| generic | config | config | fit |

## Default render filter (Phase 0)

```
scale=1080:1920:force_original_aspect_ratio=decrease,
pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,format=yuv420p
```

Crop only if `allow_reframe: true` and framing is `crop_*`.

## Phased plan

0. **Safety** — default `fit`; gate crops; UI hint; selftest for filter + validation  
1. **Config + API** — full schema; `_build_yaml` pass-through; manifest stub  
2. **Selection** — word windows, hook bonus, `min_gap_sec` + tests  
3. **Captions** — words mode, bar style, per-short SRT  
4. **Package UX** — delivered grid uses manifest; shared cold-open scorer later  

## Files to touch (when implementing)

`autoedit/shorts.py`, `config.py`, `pipeline.py`, `textgen.py`, `config.example.yaml`, `ui/server.py`, `ui/index.html`, `selftest.py`.  
Do **not** turn on `operator.py` / `facetrack.py` / `grade.py`.

## Acceptance

- Default run never center-crops  
- Crop path requires explicit consent  
- Manifest lists times + framing mode  
- Graceful skip when whisper/transcript missing  
- Golden rule intact  
