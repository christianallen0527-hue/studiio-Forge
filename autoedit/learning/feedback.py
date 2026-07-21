"""Human feedback → lasting memory (store + Obsidian Wanted vs Not Okay)."""

from __future__ import annotations

import re
import time
from pathlib import Path

from .store import OBSIDIAN, load_store, recompute_priors

TAG_MAP = [
    (r"shak|wobbl|handheld", "shake"),
    (r"hard.?loop|loop restart|music stop|restart again|music seam|\bseam\b", "music_seam"),
    (r"\btyping\b|\bclicks?\b|clicky|whoosh spam|\bsfx spam\b", "sfx"),
    (r"80s|dated|navy|gold|bank card|corporate card", "dated"),
    (r"smooth|dissolve", "smooth"),
    (r"modern|kinetic|animated|\bfun\b|engag", "modern"),
    (r"jump.?cut", "jump_cut"),
    (r"upbeat|clean music|original.*music|first.?ad.*music", "good_music"),
]


def _tags_from_text(text: str) -> list[str]:
    tags = []
    low = text.lower()
    for pat, tag in TAG_MAP:
        if re.search(pat, low):
            tags.append(tag)
    return sorted(set(tags))


def record_feedback(
    text: str,
    *,
    sentiment: str,
    subject: str = "general",
    tags: list[str] | None = None,
    log=print,
) -> dict:
    """Record wanted / not_okay feedback and refresh priors + Obsidian note."""
    sentiment = sentiment.strip().lower().replace(" ", "_")
    if sentiment in ("bad", "eww", "no", "not_ok", "notokay"):
        sentiment = "not_okay"
    if sentiment in ("good", "love", "yes", "ok", "wanted"):
        sentiment = "wanted"
    if sentiment not in ("wanted", "not_okay"):
        raise ValueError("sentiment must be 'wanted' or 'not_okay'")

    store = load_store()
    auto_tags = _tags_from_text(text)
    all_tags = sorted(set(auto_tags) | set(tags or []))
    event = {
        "at": time.time(),
        "subject": subject,
        "sentiment": sentiment,
        "text": text.strip(),
        "tags": all_tags,
    }
    store.feedback.append(event)
    recompute_priors(store)
    store.save()
    _append_obsidian(event)
    if sentiment == "not_okay":
        try:
            from .dislikes import remember_dislike
            remember_dislike(text, situation=subject, source="feedback", log=log)
        except Exception:  # noqa: BLE001
            pass
    log(f"  feedback recorded ({sentiment}) tags={all_tags or ['—']} "
        f"· confidence={store.priors.get('confidence')}")
    return event


def _append_obsidian(event: dict) -> None:
    path = OBSIDIAN / "Wanted vs Not Okay.md"
    if not path.exists():
        return
    day = time.strftime("%Y-%m-%d")
    line = (
        f"- {day}: [{event['sentiment']}] ({event['subject']}) {event['text']} "
        f"`{', '.join(event['tags']) or '—'}`"
    )
    text = path.read_text()
    marker = "## Feedback log (newest first)"
    if marker in text:
        parts = text.split(marker, 1)
        # insert after marker line
        rest = parts[1]
        # keep header then new line then previous
        nl = rest.find("\n")
        head, tail = rest[:nl + 1], rest[nl + 1:]
        path.write_text(parts[0] + marker + head + line + "\n" + tail)
    else:
        path.write_text(text.rstrip() + f"\n\n{marker}\n\n{line}\n")
