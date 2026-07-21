---
title: Roadmap & Rules
type: note
tags: [auto-edit-forge, roadmap, rules]
created: 2026-07-17
updated: 2026-07-17
summary: What to build next, and what to NEVER re-add.
---
# Roadmap & Rules

Back to [[Auto Edit Forge — HOME]].

## 🚫 Hard rules (do NOT break — Christian was emphatic)
1. **No color grading.** Footage has a LUT baked in at capture. Leave color 100% untouched — "right out of camera." `grade` stays **False**. (`grade.py` exists but is unused.)
2. **No reframing / cropping / punch-ins / face-tracking for framing.** Keep the footage's framing exactly as shot. (`operator.py` + `facetrack.py` exist but are unused in the default flow.)
3. Those jobs belong to his separate **"god-eye" studio-operations system**, not the editor.
4. The **one** allowed picture change: **rotate upside-down footage 180°** (a defect fix, not creative reframing).
5. Keep it **fully automated** (great defaults, zero required input) while staying **fully accessible/adjustable** in [[EDITING FORGE UI]].

## ✅ The editor's actual job (make it flow like top 2026 YouTube/podcast)
Already done: filler/pause/silence removal, titles, intro/outro, **sponsor spots**, cross-dissolves, fade in/out, audio normalize to -14 LUFS, shorts, [[Footage Review Engine]], upside-down auto-fix.

## Roadmap (next, in rough priority)

**Stabilize first** (see [[Bugs & Integration Audit]] — do before new features):
1. **A. Wire review → edit** — rotate first (ffmpeg + Resolve); then gain/trims. YAML must pass `angles[].rotate`.
2. **B. BRAW reliability** — Resolve audio extract (or require WAV); unique timeline names; verify render output exists.
3. **C. Job persistence + queue** — status survives restart; no pipe deadlock; single-flight or small queue.
4. **D. Login UI + hard-reject grade/operator** — auth when password set; sandbox scan/thumb/media paths.
5. **E. Dashboard wired** — health, active jobs, issues panel; backend auto-select from ingest engine.
6. **F. Settings + tests + deps** — persist editorial defaults; test A–D; Pillow/OpenCV in requirements.

**Then product depth:**
7. **Shorts Phase 0** — letterbox default; crop only with `allow_reframe` (see [[Shorts Pipeline]]).
8. **Pipeline profiles** — Shorts / Podcast / Talking Head with style-specific defaults.
9. **Cold-open HOOK** — strongest ~10–15s before title.
10. **Background music for b-roll** — review `add_music` flag.
11. **Styled burned-in captions** on the main episode.
12. **Chapters / segment markers** + YouTube timestamps.
13. **Retention pacing** — trim tangents/rambles.
14. **Social package** — title/description/thumbnail/metadata.
15. **Multicam quality** + speaker-ID (diarization).
16. Finish the **cloud push** (see [[Repo, Backup & Cloud]]).

## Parallel-agents note
On 2026-07-17, 3 background agents built pieces in parallel (review perf, EDITING FORGE UI, editorial render) with non-overlapping file ownership. That pattern works — scope each agent to distinct files.
