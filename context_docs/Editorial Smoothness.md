---
title: Editorial Smoothness
type: note
tags: [auto-edit-forge, assemble, polish]
created: 2026-07-21
updated: 2026-07-21
summary: Smart joins shipped — speech hard/micro cuts + structural dissolves; config under finish.*.
---
# Editorial Smoothness

Back to [[Auto Edit Forge — HOME]]. Product: **AUTOEDITING FORGE**.

## Status (2026-07-21)

Implemented in `assemble.py` + `finish:` config. Pipeline calls `silence.prune_short_segments` after trims.

## Behavior

| Join | Picture | Audio |
|---|---|---|
| Body→body (speech) | Hard/micro (`speech_transition_sec: 0`) | ~40 ms acrossfade (`speech_audio_crossfade_sec`) |
| Intro/title/sponsor/outro | Cross-dissolve (`transition_sec`) | Matching acrossfade |
| Program in/out | Fade from/to black (`fade_sec`, clamped) | afade |
| Tiny clips | Hard-cut if dissolve unaffordable | — |

Legacy “dissolve every cut”: set `speech_transition_sec: 0.5`.

## Config

```yaml
finish:
  transitions: true
  transition_sec: 0.5
  speech_transition_sec: 0.0
  speech_audio_crossfade_sec: 0.04
  fade_sec: 0.5
  audio_normalize: true
```

## Remaining polish

- Chapter/major-section markers → override join kinds mid-body  
- Resolve backend parity for smart joins  
- Shorts path polish (separate; letterbox default)  
- When `transitions: false`, add micro afade + loudnorm on plain concat  
