"""Persistent learning store — JSON that grows every day + every edit rating."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DIR = ROOT / "data" / "learning"
OBSIDIAN = ROOT / "context_docs" / "obsidian"


@dataclass
class LearningStore:
    version: int = 2
    updated_at: float = 0.0
    references: list[dict] = field(default_factory=list)
    feedback: list[dict] = field(default_factory=list)
    ratings: list[dict] = field(default_factory=list)          # -1 … 20
    dislikes: list[dict] = field(default_factory=list)         # never-again
    active_rules: dict = field(default_factory=dict)           # situation → {code: instruction}
    category_priors: dict = field(default_factory=dict)        # podcast/talking_head/…
    priors: dict = field(default_factory=dict)
    stats: dict = field(default_factory=lambda: {
        "references_studied": 0,
        "feedback_events": 0,
        "ratings_count": 0,
        "rating_sum": 0.0,
        "rating_avg": None,
        "dislikes_count": 0,
        "daily_runs": 0,
        "apply_count": 0,
    })

    def path(self, directory: Path | None = None) -> Path:
        d = directory or DEFAULT_DIR
        d.mkdir(parents=True, exist_ok=True)
        return d / "store.json"

    def save(self, directory: Path | None = None) -> Path:
        self.version = max(2, int(self.version or 2))
        self.updated_at = time.time()
        p = self.path(directory)
        p.write_text(json.dumps(asdict(self), indent=2, sort_keys=False))
        _sync_obsidian_summary(self)
        return p

    @classmethod
    def load(cls, directory: Path | None = None) -> "LearningStore":
        p = (directory or DEFAULT_DIR) / "store.json"
        if not p.exists():
            store = cls()
            store.priors = default_priors()
            return store
        raw = json.loads(p.read_text())
        return cls(
            version=int(raw.get("version", 2)),
            updated_at=float(raw.get("updated_at", 0)),
            references=list(raw.get("references") or []),
            feedback=list(raw.get("feedback") or []),
            ratings=list(raw.get("ratings") or []),
            dislikes=list(raw.get("dislikes") or []),
            active_rules=dict(raw.get("active_rules") or {}),
            category_priors=dict(raw.get("category_priors") or {}),
            priors=dict(raw.get("priors") or default_priors()),
            stats=dict(raw.get("stats") or {}),
        )


def load_store(directory: Path | None = None) -> LearningStore:
    return LearningStore.load(directory)


def default_priors() -> dict:
    return {
        "min_shot_sec": 2.0,
        "speech_transition_sec": 0.4,
        "transition_sec": 0.65,
        "fade_sec": 0.8,
        "music_required_on_sponsor": True,
        "music_must_be_seamless": True,
        "forbid_shaky_tails": True,
        "forbid_dated_title_cards": True,
        "forbid_click_sfx": True,
        "prefer_smooth_dissolves": True,
        "target_lufs": -14.0,
        "avg_cut_sec": 3.5,
        "cold_open_sec": 8.0,
        "sponsor_min_sec": 20.0,
        "confidence": 0.15,
        "style_tags": ["clean", "modern", "smooth"],
        "rating_target": 18,   # always push toward 18–20
        "push_harder": True,
    }


def recompute_priors(store: LearningStore) -> dict:
    """Blend defaults + refs + feedback + ratings + dislike rules."""
    p = default_priors()
    p.update(store.priors or {})

    cut_secs = []
    for ref in store.references:
        feat = ref.get("features") or {}
        if feat.get("median_shot_sec"):
            cut_secs.append(float(feat["median_shot_sec"]))
    if cut_secs:
        cut_secs.sort()
        mid = cut_secs[len(cut_secs) // 2]
        p["avg_cut_sec"] = round(0.55 * float(p.get("avg_cut_sec", mid)) + 0.45 * mid, 2)
        p["min_shot_sec"] = round(max(1.2, min(4.0, p["avg_cut_sec"] * 0.55)), 2)

    # Active dislike rules → hard priors
    global_rules = (store.active_rules or {}).get("global") or {}
    if "no_shaky_tails" in global_rules:
        p["forbid_shaky_tails"] = True
    if "seamless_music_only" in global_rules:
        p["music_must_be_seamless"] = True
    if "no_click_sfx" in global_rules:
        p["forbid_click_sfx"] = True
    if "no_dated_cards" in global_rules:
        p["forbid_dated_title_cards"] = True
    if "no_jump_cuts" in global_rules:
        p["prefer_smooth_dissolves"] = True
        p["speech_transition_sec"] = max(float(p.get("speech_transition_sec", 0.4)), 0.45)
    if "sponsor_midroll" in global_rules:
        p["sponsor_placement"] = "midroll"
    if "require_music_on_sponsor" in global_rules:
        p["music_required_on_sponsor"] = True

    for fb in store.feedback:
        tags = set(fb.get("tags") or [])
        if fb.get("sentiment") == "wanted" and ("smooth" in tags or "dissolve" in tags):
            p["prefer_smooth_dissolves"] = True

    # Ratings push target quality
    avg = store.stats.get("rating_avg")
    if avg is not None:
        p["rating_avg"] = avg
        if float(avg) < 12:
            p["push_harder"] = True
            p["speech_transition_sec"] = max(float(p.get("speech_transition_sec", 0.4)), 0.5)
            p["transition_sec"] = max(float(p.get("transition_sec", 0.6)), 0.7)

    n_ref = len(store.references)
    n_fb = len(store.feedback)
    n_rt = len(store.ratings)
    n_dl = len(store.dislikes)
    n_day = int(store.stats.get("daily_runs") or 0)
    p["confidence"] = round(min(0.98, 0.12
                                + 0.04 * n_ref
                                + 0.05 * n_fb
                                + 0.06 * n_rt
                                + 0.04 * n_dl
                                + 0.03 * n_day), 3)
    p["style_tags"] = sorted(set(p.get("style_tags") or []) | {"learned"})
    store.priors = p
    store.stats["references_studied"] = n_ref
    store.stats["feedback_events"] = n_fb
    store.stats["dislikes_count"] = n_dl
    return p


def _sync_obsidian_summary(store: LearningStore) -> None:
    OBSIDIAN.mkdir(parents=True, exist_ok=True)
    path = OBSIDIAN / "Editorial Learning.md"
    priors = store.priors or {}
    lines = [
        "# Editorial Learning",
        "",
        "Major subsystem. Grows **every day** from top podcasts / talking heads / "
        "long-form / shorts, from every rated edit (-1…20), and from every dislike.",
        "",
        "## Stats",
        "",
        f"- References studied: **{store.stats.get('references_studied', 0)}**",
        f"- Feedback events: **{store.stats.get('feedback_events', 0)}**",
        f"- Edit ratings: **{store.stats.get('ratings_count', 0)}** "
        f"(avg {store.stats.get('rating_avg')})",
        f"- Dislikes (never-again): **{store.stats.get('dislikes_count', 0)}**",
        f"- Daily runs: **{store.stats.get('daily_runs', 0)}** "
        f"(last `{store.stats.get('last_daily_day', '—')}`)",
        f"- Prior confidence: **{priors.get('confidence', 0)}**",
        f"- Rating target: **{priors.get('rating_target', 18)}/20**",
        "",
        "## Category priors",
        "",
    ]
    for cat, block in (store.category_priors or {}).items():
        lines.append(
            f"- **{cat}**: samples={block.get('samples', 0)} · "
            f"median_shot={block.get('median_shot_sec')} · "
            f"rating_avg={block.get('rating_avg')}"
        )
    if not store.category_priors:
        lines.append("_Run_ `python -m autoedit.learning daily` _to fill categories._")
    lines += [
        "",
        "## Active never-again rules",
        "",
    ]
    for sit, rules in (store.active_rules or {}).items():
        lines.append(f"### {sit}")
        for code, instr in (rules or {}).items():
            lines.append(f"- `{code}` — {instr}")
    lines += [
        "",
        "## Global priors",
        "",
        "```json",
        json.dumps(priors, indent=2),
        "```",
        "",
        "## Recent ratings (-1 bad … 20 perfect)",
        "",
    ]
    for r in (store.ratings or [])[-10:][::-1]:
        lines.append(
            f"- **{r.get('rating')}/20** · {r.get('category')} · "
            f"{Path(str(r.get('path', ''))).name} — {r.get('notes') or '—'}"
        )
    if not store.ratings:
        lines.append("_Rate edits:_ `python -m autoedit.learning rate <path> 16`")
    lines.append("")
    path.write_text("\n".join(lines))
