# AUTOEDITING FORGE — Memory Vault (Obsidian)

Living memory + **editorial learning brain**. Agents must read this before building ads or client cuts.

## Index

| Note | Purpose |
|------|---------|
| [[Sponsor Ad — High Place Mortgage]] | Locked creative rules for the HPM spot |
| [[Wanted vs Not Okay]] | Global do / don't from real feedback |
| [[Never Again]] | Contextual dislike rules — do not repeat |
| [[Review Before Show]] | QC gate — never show until green |
| [[Editorial Learning]] | Growing brain — stats, priors, ratings |
| [[Daily Learning Journal]] | What was studied each day |

## The learning brain (major subsystem)

Always learning from:

1. **Top public YouTube** — podcasts · talking heads · long-form · shorts (`daily`)
2. **Your ratings** — every edit scored **-1 (bad) → 20 (perfect)** (target **18+**)
3. **Dislikes** — every “I don’t like X” becomes a never-again rule for that situation
4. **Its own jobs** — rate the episode it just cut so priors improve

```bash
# Every day (or launchd at 6:30 — see scripts/com.autoeditingforge.dailylearning.plist)
.venv/bin/python -m autoedit.learning daily

# Rate an edit the system made
.venv/bin/python -m autoedit.learning rate "/path/to/episode.mp4" 16 --category podcast --notes "smooth but cold open weak"

# Never again (contextual)
.venv/bin/python -m autoedit.learning dislike "shaky last clips" --situation sponsor

.venv/bin/python -m autoedit.learning show
```

UI APIs: `GET /api/learning` · `POST /api/learning/rate` · `POST /api/learning/dislike` · `POST /api/learning/daily`

Store: `data/learning/store.json`

## How to use (creative)

1. Before changing HPM ad, open [[Sponsor Ad — High Place Mortgage]] + [[Never Again]].
2. Any “eww” → `dislike` **and** update [[Wanted vs Not Okay]] same turn.
3. Run sponsor QC before `open` / delivery.
4. After every client cut → rate it (-1…20).

## Related engine docs

- `context_docs/Footage Review Engine.md`
- `context_docs/Editorial Smoothness.md`
- `CURSOR_START_HERE.md`
