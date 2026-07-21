---
title: Bugs & Integration Audit
type: note
tags: [auto-edit-forge, audit, bugs]
created: 2026-07-21
updated: 2026-07-21
summary: Evidence-backed gaps vs a hands-off AUTOEDITING FORGE with login, progress, and health monitoring.
---
# Bugs & Integration Audit

Back to [[Auto Edit Forge — HOME]]. Audit date: 2026-07-21.

## Verdict

Core editorial pipeline exists, but several goal-critical paths are disconnected or broken: **review does not drive the edit**, **Resolve does not apply the allowed 180° fix**, **BRAW single-cam audio still depends on ffmpeg**, and **auth/dashboard need UI wiring**. Jobs/reviews are still in-memory only unless persistence lands with the backend work.

## P0 — Breaks the product promise

1. ~~**Review → edit not wired**~~ **DONE (2026-07-21)** — pipeline auto-runs review before sync; applies 180° (ffmpeg+Resolve), peak-safe mic gain, consensus head/tail black trims; writes `out/review.json`. UI “queued” copy is now true via re-review (optional later: pass `review_id` to skip re-scan).
2. ~~**Resolve never rotates**~~ **DONE (2026-07-21)** — Resolve path applies angle rotate/flip from review.
3. **BRAW + edit mode audio via ffmpeg** — mic=video for single-cam; ffmpeg cannot read `.braw`.
4. ~~**Auth API without login UI**~~ **DONE (2026-07-21)** — login screen + dashboard poll `/api/session|login|logout|dashboard`.
5. **Resolve timeline name collision** — fixed `…_edit` / `…_operated` names fail on second run.

## P1 — Reliability / security

6. Job/review state not persisted; dashboard timestamps unused  
7. ~~`/api/dashboard` unused~~ **DONE** — home dashboard polls health/jobs/issues  
8. Job runner stderr/stdout pipe deadlock risk  
9. No concurrency control (stacked Resolve/ffmpeg jobs)  
10. BRAW review/thumbs fail hard or silently  
11. Resolve render success not verified  
12. Default backend Resolve vs ingest `engine: ffmpeg` mismatch  
13. Auth opt-in; scan/thumb/media path hardening needed  
14. Grade/operator still reachable — hard-reject in server+config  
15. `_build_yaml` drops `rotate` even if client sends it  

## P2

16. Settings incomplete / not persisted  
17. Progress/issue visibility gaps  
18. Tests cover operator/facetrack more than review→edit  
19. Pillow/OpenCV not in hard deps  
20. Doc/launcher drift  

## Staged delivery (do this order)

| Stage | Focus |
|------|--------|
| **A** | Review→edit (rotate) + Resolve flip + YAML `rotate` pass-through |
| **B** | BRAW audio path + early validation + unique timeline names + render verify |
| **C** | Persist job/review status; fix `_run_job` I/O; job queue; timestamps |
| **D** | Login UI ↔ auth; harden media/scan/thumb; reject grade/operator |
| **E** | Wire dashboard into header + issues; backend auto-select from ingest |
| **F** | Settings persistence; tests for A–D; deps/docs cleanup |

Defer cold-open / chapters / social package until A–D are solid.
