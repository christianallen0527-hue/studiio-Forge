---
title: Camera Forge Ingest
type: note
tags: [auto-edit-forge, camera-forge, braw, ingest, studio-files]
created: 2026-07-21
updated: 2026-07-21
summary: BRAW lands on Mac staging for speed, then drains to Studio Files NAS. ZowieBox is monitor-only.
---
# Camera Forge ↔ AUTOEDITING FORGE ingest

Back to [[Auto Edit Forge — HOME]] · [[Resolve & BRAW]].

## Studio roles

| System | Job |
|---|---|
| **Camera Forge** | Camera control, record BRAW to USB SSD, **pull .braw** (fast) onto Mac staging |
| **ZowieBox** | **Monitor only** — HDMI → RTSP → Camera Desk live.jpg. Never edit footage |
| **AUTOEDITING FORGE** | Drain staging → **Studio Files NAS**, then review + Resolve edit |
| **Studio Files NAS** | **Permanent storage** for inbox + jobs (`/Volumes/Studio Files`) |

The Mac SSD has almost no free space (~4 GB). It may be used for **fast upload/staging only**. Finished BRAW and job outputs must live on the NAS.

## Storage layout

| Role | Path |
|---|---|
| Permanent inbox | `/Volumes/Studio Files/AUTOEDITING FORGE Inbox` |
| Permanent jobs | `/Volumes/Studio Files/AUTOEDITING FORGE Jobs` |
| Fast Mac staging | `~/Movies/AUTOEDITING FORGE Staging` |
| Legacy (drained) | `~/Movies/AUTOEDITING FORGE Inbox`, `~/Movies/AutoEdit Inbox` |

```
Camera USB SSD (BRAW)
        │  Camera Forge pull (fast → Mac SSD)
        ▼
~/Movies/AUTOEDITING FORGE Staging/<session>/
        │  AUTOEDITING FORGE drain (every ~30s when settled)
        ▼
/Volumes/Studio Files/AUTOEDITING FORGE Inbox/<session>/
        │  session.json { kind:braw, engine:resolve, … }
        ▼
Review → Resolve edit → Jobs on Studio Files
```

If the NAS is offline, ingest **refuses** to keep new BRAW on the Mac as permanent storage.

## What Camera Forge already has

App Support desk:  
`~/Library/Application Support/Camera Forge/camera-desk/`

- `scripts/download-braw.sh` — curl list + download from camera USB
- `scripts/desk_server.py` — pull API + progress jobs
- `hosts.env` → `BRAW_DEST=~/Movies/AUTOEDITING FORGE Staging`
- Camera: Micro Studio 4K G2 @ `192.168.1.63`
- Zowie: `192.168.1.243` RTSP — live monitor only

## Phase status

### Phase 1 — Drop-folder + NAS permanent storage — **DONE**

1. Camera Forge `BRAW_DEST` → Mac staging (fast)
2. AUTOEDITING FORGE drains staging → Studio Files inbox
3. Jobs/renders → Studio Files jobs folder
4. `ui/ingest.json` — empty `sources`, staging + NAS watch dirs
5. Restart Camera Forge / desk agent after changing `hosts.env`

### Phase 2 — One-click from either app

- Camera Forge notify AutoEdit after pull, or AutoEdit trigger Camera Forge pull API.

### Phase 3 — Multi-cam + audio

- Per-camera `CAM*_date` folders; BRAW audio via Resolve extract (Stage B).

## What NOT to do

- Do not treat ZowieBox RTSP/MP4 as edit masters.
- Do not park permanent BRAW on the Mac SSD / Desktop.
- Do not scrape `/mounts/usb/A001` from AutoEdit — that is Camera Forge’s job.

## Config sketch

**Camera Forge `hosts.env`**
```bash
BRAW_DEST=~/Movies/AUTOEDITING FORGE Staging
```

**AUTOEDITING FORGE `ui/ingest.json`**
```json
{
  "sources": [],
  "camera_forge": {
    "enabled": true,
    "desk_url": "http://127.0.0.1:8790",
    "watch_dirs": [
      "/Volumes/Studio Files/AUTOEDITING FORGE Inbox",
      "~/Movies/AUTOEDITING FORGE Staging"
    ],
    "auto_backend": "resolve"
  }
}
```

## Acceptance

- Pull in Camera Forge → files appear in Mac staging → within one poll cycle they land on Studio Files inbox.  
- Mac free space does not keep growing with finished BRAW.  
- NAS offline → clear critical health; no silent Mac fill-up.  
- Zowie offline does not block pull/edit.  
