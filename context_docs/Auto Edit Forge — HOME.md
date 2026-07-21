---
title: Auto Edit Forge — HOME
type: moc
tags: [auto-edit-forge, editing-forge, moc, studio]
created: 2026-07-17
updated: 2026-07-17
summary: Home base for the automated video editor (product UI name "EDITING FORGE", repo "auto-edit-forge").
---
# 🔨 Auto Edit Forge — HOME

**One line:** a **fully automated video editor** — point it at footage, it reviews the clips, cuts the ums and dead air, adds titles/transitions/fades/shorts, and delivers a finished YouTube/podcast episode. The UI is called **EDITING FORGE**.

> [!important] The golden rule
> This tool does **EDITORIAL work only** — cutting, pacing, titles, transitions, audio, shorts.
> It does **NOT** color-grade and does **NOT** reframe/crop/track faces. The footage's **look and framing are kept exactly as shot** (a separate "god-eye" studio-operations system owns camera work + LUT/color). The one picture fix allowed is **rotating upside-down footage 180°** (a defect fix). See [[Roadmap & Rules]].

## Map of this system
- [[System Overview]] — what it is, who it's for, the philosophy (fully automated, but fully accessible)
- [[Architecture & Pipeline]] — the stages, the modules, how footage becomes a finished cut
- [[Footage Review Engine]] — the AI that **watches the clips before editing** (audio/orientation/usable) ⭐ the critical piece
- [[EDITING FORGE UI]] — the powerful, beautiful interface (ember/forge look) + its API
- [[Resolve & BRAW]] — DaVinci Resolve 21 integration (reads BRAW natively, renders timelines)
- [[Camera Forge Ingest]] — BRAW pull from Camera Forge; ZowieBox is monitor-only
- [[Environment & Gotchas]] — paths, TCC quirks, ffmpeg, venv, Ollama — READ THIS before touching the code
- [[Repo, Backup & Cloud]] — GitHub repo, the Desktop zip backup, phone/cloud access
- [[Roadmap & Rules]] — what to build next, and what to NEVER re-add
- [[Shorts Pipeline]] — vertical package design (letterbox default; crop opt-in only)
- [[Talking Head Pipeline]] — single-cam styles, cleanup safety, edit plan
- [[Podcast Pipeline]] — multicam switching, sync confidence, chapters/show notes
- [[Editorial Smoothness]] — professional cuts: hard speech cuts + structural dissolves
- [[Ollama Visual Reviewer]] — pre-edit footage QC + post-edit vision review
- [[Bugs & Integration Audit]] — P0/P1 gaps and staged delivery order (2026-07-21)

## Where everything lives
- **Project code:** `/Users/studio/Desktop/$k auto editing pipeline/` (note the literal `$k` in the path)
- **Run the UI:** open `ui/Open Auto Edit.command` (double-click) → serves EDITING FORGE at `http://127.0.0.1:8765`
- **GitHub:** `auto-edit-forge` (private) — `https://github.com/christianallen0527-hue/auto-edit-forge`
- **Backup zip:** `~/Desktop/auto-edit-forge.zip` (full code + docs + git history + helper scripts)
- **Helper scripts:** `~/Movies/*.py` (Resolve/BRAW tools) + `~/Movies/_fwenv` (a small venv)

## Current status (2026-07-17)
- ✅ Core pipeline works end-to-end; delivered a real finished video from BRAW (`~/Movies/sample_edit_smooth.mp4`): title → clips → ending, with **180° rotation fix, cross-dissolves, fade in/out**.
- ✅ [[Footage Review Engine]] built + fast (~1–3s/clip).
- ✅ [[EDITING FORGE UI]] built (ember/forge design + review panel).
- ✅ Transitions / fades / intro-outro / sponsor spots / audio-normalize baked into the render.
- ⏳ GitHub repo **created**; the push got interrupted — finish with one command next session.
- ⏳ Vision layer: Ollama installed, `moondream` model pulled (optional semantic read).

Log of changes: [[30-log/Changelog]]
