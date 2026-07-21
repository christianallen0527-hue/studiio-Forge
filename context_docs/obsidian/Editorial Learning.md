# Editorial Learning

Major subsystem. Grows **every day** from top podcasts / talking heads / long-form / shorts, from every rated edit (-1…20), and from every dislike.

## Stats

- References studied: **1**
- Feedback events: **13**
- Edit ratings: **1** (avg 18.0)
- Dislikes (never-again): **5**
- Daily runs: **0** (last `—`)
- Prior confidence: **0.98**
- Rating target: **18/20**

## Category priors

- **sponsor**: samples=0 · median_shot=None · rating_avg=18.0

## Active never-again rules

### global
- `no_shaky_tails` — Never deliver shaky handheld tails; stabilize or re-cut.
- `seamless_music_only` — Music beds must crossfade-loop with no audible restart.
- `no_click_sfx` — No typing/click/UI SFX beds — clean music only unless asked.
- `no_dated_cards` — No navy/gold 80s bank title cards; use modern kinetic type over live footage.
- `no_jump_cuts` — Prefer smooth dissolves; avoid jump-cutty speech joins.
### sponsor
- `no_shaky_tails` — Never deliver shaky handheld tails; stabilize or re-cut.
- `seamless_music_only` — Music beds must crossfade-loop with no audible restart.
- `no_click_sfx` — No typing/click/UI SFX beds — clean music only unless asked.
- `no_dated_cards` — No navy/gold 80s bank title cards; use modern kinetic type over live footage.
### general
- `no_jump_cuts` — Prefer smooth dissolves; avoid jump-cutty speech joins.

## Global priors

```json
{
  "min_shot_sec": 4.0,
  "speech_transition_sec": 0.45,
  "transition_sec": 0.65,
  "fade_sec": 0.8,
  "music_required_on_sponsor": true,
  "music_must_be_seamless": true,
  "forbid_shaky_tails": true,
  "forbid_dated_title_cards": true,
  "forbid_click_sfx": true,
  "prefer_smooth_dissolves": true,
  "target_lufs": -14.0,
  "avg_cut_sec": 10.21,
  "cold_open_sec": 8.0,
  "sponsor_min_sec": 20.0,
  "confidence": 0.98,
  "style_tags": [
    "clean",
    "high_rated",
    "learned",
    "modern",
    "smooth",
    "sponsor"
  ],
  "rating_target": 18,
  "push_harder": true,
  "last_high_rating": 18,
  "rating_avg": 18.0
}
```

## Recent ratings (-1 bad … 20 perfect)

- **18/20** · sponsor · high_place_mortgage_sponsor_stock.mp4 — first loved ad — reference quality
