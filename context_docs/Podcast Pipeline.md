---
title: Podcast Pipeline
type: note
tags: [auto-edit-forge, podcast, roadmap]
created: 2026-07-21
updated: 2026-07-21
summary: Purpose-built podcast pipeline — video-follows-audio switching, sync/audio, chapters/captions/show notes.
---
# Podcast Pipeline

Back to [[Auto Edit Forge — HOME]]. Product: **AUTOEDITING FORGE**.

## Golden rule

Editorial only. No grade / crop / zoom / face-track. Only rotate 180. Letterbox when dimensions differ.

## Video follows audio (shipped)

Studio cameras embed each speaker's audio in the camera file. The podcast multi-cam mode listens to that embedded track — no separate mic WAVs required.

| Setting | Default | Effect |
|---|---|---|
| `switch.video_follows_audio` | on | Missing `mic:` → use that angle's `video` file audio |
| `switch.min_shot_sec` | 2.5 | Anti-flicker / smooth holds |
| `switch.relative_activation_db` | 8 | Gate vs each cam's noise floor (room tone) |
| `switch.switch_margin_db` | 2 | Don't cut unless the other speaker is clearly louder |
| `switch.overlap_to_wide` | on | Cross-talk → wide |

UI: **Podcast Multi-Cam** → toggle **Video follows audio** + advanced **Min shot length**.

### Happens inside the forge run (not a preprocess)

When you hit **Forge the edit**, one pipeline pass:

1. Pull each camera’s embedded audio (works for this studio’s BRAW via ffmpeg)  
2. Sync cameras on that audio  
3. Build loudness envelopes → **video-follows-audio cut list**  
4. Mix master from those same embedded tracks → refine / titles / Resolve render  

No separate “extract audio first” step.

## Current foundation

Review → sync → switch → mix → transcribe/refine → titles → render/shorts. Loudness switching + wide on overlap. Review auto-applies rotate / gain / consensus edge trims (Stage A).

## Critical gaps still open

1. **BRAW picture** still needs Resolve for the video edit; audio analysis already runs in-edit via ffmpeg on embedded PCM  
2. **Sync confidence** — never silently assume 0.0; detect drift; support negative offsets  
3. **Switching polish** — attack/release envelopes, short-interjection hold  
4. **Podcast mix** — inactive-mic attenuate; video −14 LUFS / podcast audio −16 LUFS  
5. **Body cuts = hard cuts**; dissolves only at structural boundaries  
6. **Remap all timed artifacts** (SRT/VTT/chapters/sponsors) through one edit map  
7. **Resolve finishing parity** (rotation, master audio, markers, structural dissolves, render verify)

## Presets (UI)

| Preset | Character |
|---|---|
| **Natural Podcast** | Conservative fillers; 1.2s pauses; 2.5s min shot |
| **Tight YouTube Podcast** | 0.8s pauses; 2s shots; more silence cleanup |
| **Minimal Cleanup** | Level + captions + chapters; almost no dialogue removal |

## Stages (target)

Preflight → review plan → confidence sync → podcast audio master → speaker switch → transcript cleanup (protected ranges) → chapters/sponsors/captions/show notes → assemble + QC → deliverables

## Key outputs

`episode.mp4`, podcast audio (−16 LUFS), `episode.srt`/`vtt`, `transcript.json`, `chapters.json`, `youtube_chapters.txt`, `show_notes.md`, `sponsor_markers.json`, `qc.json`, manifest

## New modules (suggested)

`podcast_audio.py`, `timemap.py`, `chapters.py`, `deliverables.py`, `qc.py`

## Phased implementation

1. Preflight + time map + BRAW audio routing + caption remap + golden-rule enforcement  
2. Confidence sync + automix + switching timing + podcast loudness  
3. Metadata package (VTT, chapters, sponsors, show notes, QC)  
4. Resolve parity  
5. Podcast UI mode + presets + preflight warnings  
6. Regression suite  

## Depends on

[[Bugs & Integration Audit]] stages B–D, [[Editorial Smoothness]], [[Shorts Pipeline]] Phase 0 for vertical exports.
