# Review Before Show

**Hard rule:** never `open` / deliver a sponsor spot or client-review episode until automated QC has run and critical issues are fixed.

## Sponsor spot checklist (`autoedit/sponsor_qc.py`)

| Check | Fail if |
|-------|---------|
| `music_seam` | Hard loop restart / abrupt bed drop mid-spot |
| `shake` | High motion jitter in final third (shaky tail clips) |
| `dated_card` | Long near-static dark full-frame card (80s bank slate) |
| `silence` | No usable audio / near-silent mix |
| `sfx_spam` | Excessive transient click density (typing-like) |

## Flow

1. Build / edit
2. `sponsor_qc.analyze(path)` → `qc_sponsor.json`
3. If `verdict != pass` → apply `fixes[]` (stabilize, reseam music, rebuild mid card) 
4. Re-run QC
5. Only then show the human

## Episode pipeline

`pipeline.run` already writes `qc_vision.json` after assemble. Also write `qc_sponsor.json` when a sponsor file is used, and log recommendations into `review.json` under `sponsor`.
