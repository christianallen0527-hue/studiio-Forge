"""Edit quality ratings — scale -1 (bad) … 20 (perfect).

Every finished forge job can be scored. High scores reinforce knobs used;
low scores push priors away from that pattern and create dislike memories.
"""

from __future__ import annotations

import time
from pathlib import Path

from .store import load_store, recompute_priors

RATING_MIN = -1
RATING_MAX = 20


def clamp_rating(n: float | int) -> int:
    return int(max(RATING_MIN, min(RATING_MAX, round(float(n)))))


def rate_edit(
    path: str | Path,
    rating: float | int,
    *,
    category: str = "general",
    notes: str = "",
    context: dict | None = None,
    job_id: str = "",
    log=print,
) -> dict:
    """Record a human rating for an edit the system produced (or a reference)."""
    rating = clamp_rating(rating)
    store = load_store()
    event = {
        "at": time.time(),
        "path": str(path),
        "job_id": job_id,
        "rating": rating,
        "category": category,
        "notes": notes.strip(),
        "context": context or {},
    }
    store.ratings.append(event)
    store.stats["ratings_count"] = int(store.stats.get("ratings_count") or 0) + 1
    store.stats["rating_sum"] = float(store.stats.get("rating_sum") or 0) + rating
    n = max(1, int(store.stats["ratings_count"]))
    store.stats["rating_avg"] = round(float(store.stats["rating_sum"]) / n, 2)

    # Reinforce / punish category priors
    cat_priors = store.category_priors.setdefault(category, {})
    hist = cat_priors.setdefault("rating_history", [])
    hist.append(rating)
    cat_priors["rating_history"] = hist[-50:]
    cat_priors["rating_avg"] = round(sum(hist[-50:]) / len(hist[-50:]), 2)

    if rating <= 4:
        # Bad edit — extract notes into dislike memory automatically
        from .dislikes import remember_dislike
        why = notes or f"Rated {rating}/20 — do not repeat this pattern"
        remember_dislike(
            why,
            situation=category,
            context={"path": str(path), "rating": rating, **(context or {})},
            source="rating",
            log=log,
        )
        store.priors["push_harder"] = True
    elif rating >= 16:
        store.priors.setdefault("style_tags", [])
        tags = set(store.priors.get("style_tags") or [])
        tags |= {"high_rated", category}
        store.priors["style_tags"] = sorted(tags)
        store.priors["last_high_rating"] = rating

    recompute_priors(store)
    store.save()
    log(f"  rated {Path(path).name}: {rating}/20 ({_label(rating)}) · "
        f"avg={store.stats.get('rating_avg')} · category={category}")
    return event


def _label(r: int) -> str:
    if r <= 0:
        return "bad"
    if r <= 5:
        return "poor"
    if r <= 10:
        return "okay"
    if r <= 15:
        return "good"
    if r <= 18:
        return "great"
    return "perfect"


def rating_summary(store=None) -> dict:
    store = store or load_store()
    return {
        "scale": {"min": RATING_MIN, "max": RATING_MAX,
                  "help": "-1 = bad · 10 = solid · 20 = perfect"},
        "count": store.stats.get("ratings_count", 0),
        "average": store.stats.get("rating_avg"),
        "recent": list(reversed(store.ratings[-12:])),
        "by_category": {
            k: {"avg": v.get("rating_avg"), "n": len(v.get("rating_history") or [])}
            for k, v in (store.category_priors or {}).items()
        },
    }
