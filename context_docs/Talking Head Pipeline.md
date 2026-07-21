---
title: Talking Head Pipeline
type: note
tags: [auto-edit-forge, talking-head, roadmap]
created: 2026-07-21
updated: 2026-07-21
summary: Single-camera talking-head pipeline — conservative cleanup, non-destructive overlays, hard framing/color policy.
---
# Talking Head Pipeline

Back to [[Auto Edit Forge — HOME]]. Product name: **AUTOEDITING FORGE**.

Design produced 2026-07-21. No implementation yet.

## Hard policy (non-configurable for this format)

- No grade / crop / zoom / punch-in / face-track / operator
- Preserve full source raster (pad allowed for container only)
- Only `rotate: 180` picture fix
- Shorts: `vertical_fit_pad` only (never increase+crop)
- Reject `operator.enabled`, `output.grade`, and auto 90°/270° correction

## Workflow

1. Validate + lock policy  
2. Review → persist `review.json` (180°, black trims, audio)  
3. Transcribe once → `transcript.json`  
4. Structure analysis (sentences, hooks, CTA, chapters)  
5. Cleanup candidates with confidence + reasons  
6. Safety pass (budgets, protected phrases, sentence integrity)  
7. Canonical `edit_plan.json` (single timeline map for all outputs)  
8. Assemble — hard cuts inside A-roll; dissolves only at structural boundaries  
9. Captions + metadata (burn-in optional; corrected SRT/VTT)  
10. QC + delivery  

## Styles (presets)

| Style | Pace / cleanup | Hook | B-roll | Music | Chapters |
|---|---|---|---|---|---|
| **educational** | Natural; 8% max delete; tangents suggest | 10–15s | ≤1/min | off | on (≥3 min) |
| **commentary** | Tighter pauses; 10% max | 8–12s | ≤1.5/min | optional b-roll-only | on |
| **announcement** | Tightest; 12% max | 6–9s (off if <60s) | ≤2/min | optional bed | only if long |

## Key product rules

- **One edit plan** — SRT, captions, chapters, shorts, hook all share the same timeline map (fixes current remap/SRT drift).
- **Tangents default to suggest**, not auto-cut.
- **B-roll overlays** on V2 without shifting body duration; music ducked; assets must be user-supplied.
- **Captions** via Pillow PNG + overlay in chunks (no drawtext/libass).

## API (target)

Keep browse/media. Add/extend: `GET /api/presets`, review persist, `POST /api/plan` + `GET /api/plan/<id>`, `/api/run` with `plan_id` (or build plan internally for back-compat).

## New modules (recommended)

`timeline.py`, `talking_head.py`, `hooks.py`, `inserts.py`, `captions.py`, `chapters.py`, `qc.py`

## Phased implementation

1. Policy + review wiring + timeline map + corrected SRT + shorts letterbox  
2. Safe cleanup (confidence, budgets, cut report; hard cuts + audio fades)  
3. Hooks + chapters + CTA  
4. Long-form captions  
5. B-roll + music  
6. UI presets (Educational / Commentary / Announcement)  
7. QC + regression tests  

## Depends on (stabilize first)

See [[Bugs & Integration Audit]] stages A–D and [[Shorts Pipeline]] Phase 0 before deep Talking Head work.
