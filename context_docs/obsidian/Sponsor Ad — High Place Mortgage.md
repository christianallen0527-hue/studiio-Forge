# Sponsor Ad — High Place Mortgage

## Locked deliverable

`assets/sponsor/high_place_mortgage_sponsor.mp4`

## Creative lock

| Element | Rule |
|---------|------|
| Length | ≥ 20 seconds |
| Structure | Intro → house body → modern message beat → house → end |
| Music | **Only** the original first-ad upbeat bed. Crossfade-loop if needed. No other beds/SFX unless human asks. |
| Graphics | Ultra-modern kinetic type over **live** house footage. Coral/mint accents OK. No navy+gold bank cards. |
| Camera | Steady. Deshake or pick stable segments. Never deliver shaky tails. |
| Audio QC | Seamless music; no clicks/typing; no hard loop. |

## Source assets (safe)

- House plate: `assets/sponsor/raw/pexels_house_7578552.mp4` (prefer over old card-ridden `hpm_picture.mp4`)
- Original music extract: staging `original_ad_bed.wav` from `high_place_mortgage_sponsor_stock.mp4`
- Avoid using `hpm_s1/s2/s3.png` / navy endcards as full-screen mid plates

## Build / QC

```bash
.venv/bin/python -m autoedit.sponsor_qc assets/sponsor/high_place_mortgage_sponsor.mp4
# exit 0 + verdict pass → allowed to open for human
```

Pipeline must call sponsor QC when `sponsor.video` is set; auto-fix seamless bed when possible; block “show” until pass (or write `qc_sponsor.json` with fails).
