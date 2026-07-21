---
title: Resolve & BRAW
type: note
tags: [auto-edit-forge, resolve, braw]
created: 2026-07-17
updated: 2026-07-17
summary: DaVinci Resolve 21 integration — reads BRAW natively, builds + renders timelines.
---
# Resolve & BRAW

Back to [[Auto Edit Forge — HOME]]. Code: `autoedit/resolve_backend.py`.

## Why Resolve
**ffmpeg cannot read `.braw`.** DaVinci Resolve Studio 21 reads Blackmagic RAW natively, so it's the backend whenever BRAW is involved. For mp4/mov/ProRes (e.g. ZowieBox recordings), the free ffmpeg path also works and is faster.

## Requirements at run time
- **DaVinci Resolve Studio 21 must be OPEN** (free/App-Store builds can't be scripted).
- Prefs → System → General → *External scripting using* = **Local**.
- Env: `RESOLVE_SCRIPT_API` = `/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting`, `RESOLVE_SCRIPT_LIB` = `…/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so`.

## How it works
- Connect via `DaVinciResolveScript.scriptapp("Resolve")` (retry — the connection can be flaky; loop a few times).
- Build a timeline (V1 video + A1 master audio), append clips (trimmed by frame), render to mp4 (`SetCurrentRenderFormatAndCodec("mp4","H264")`).
- Gotchas: `CreateEmptyTimeline` returns **None on a duplicate name** → use timestamped names. Resolve **overwrites** same-name renders. `MediaStorage` API can **list/read external drives** even when the shell can't (see [[Environment & Gotchas]]).

## Helper scripts (`~/Movies/`, also in the backup zip under `helper_scripts/`)
- `resolve_inspect.py` — dump current project's media pool + timelines.
- `sample_edit.py` — build title→BRAW clips→ending and render to `~/Movies/sample_edit.mp4`.
- `mkfinished.py` — self-contained finished-work renderer (operator plan + Pillow cards + Resolve build/render; accepts `.braw` paths as args).
- `list_braw.py` — list `.braw` on a drive via Resolve's MediaStorage.

## Proven output
`~/Movies/sample_edit_smooth.mp4` — title → 3 BRAW clips → ending, rendered via Resolve then finished in ffmpeg with **180° rotation fix + cross-dissolves + fade in/out**. Christian approved it.

## Known BRAW clips (project "finished_work", from `/Volumes/Studio Files`)
`A001_04281422_C002.braw` (1h27m), `A001_05010946_C003.braw` (5s), `A001_05122245_C003.braw` (17m).
BRAW footage was shot **upside-down** on an inverted mount → needs 180° rotation.
