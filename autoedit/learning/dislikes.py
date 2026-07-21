"""Contextual dislike memory — never repeat a mistake in the same situation.

Whenever the human says they don't like something, we store:
  * what they said
  * situation / category (sponsor, podcast, shorts, …)
  * tags + freeform context
  * a machine rule the editor checks before delivering
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from .store import OBSIDIAN, load_store, recompute_priors

# Map natural language → durable rule codes the QC / apply layers honor
RULE_PATTERNS = [
    (r"shak|wobbl|handheld", "no_shaky_tails",
     "Never deliver shaky handheld tails; stabilize or re-cut."),
    (r"hard.?loop|music stop|restart again|music seam|\bseam\b", "seamless_music_only",
     "Music beds must crossfade-loop with no audible restart."),
    (r"\btyping\b|\bclicks?\b|clicky|whoosh spam", "no_click_sfx",
     "No typing/click/UI SFX beds — clean music only unless asked."),
    (r"80s|dated|navy|gold|bank card|corporate card", "no_dated_cards",
     "No navy/gold 80s bank title cards; use modern kinetic type over live footage."),
    (r"jump.?cut", "no_jump_cuts",
     "Prefer smooth dissolves; avoid jump-cutty speech joins."),
    (r"too loud|clipping|hot audio", "no_hot_audio",
     "Keep program loudness near -14 LUFS; no clipping peaks."),
    (r"too quiet|silent ad|no music", "require_music_on_sponsor",
     "Sponsor spots need a real music bed."),
    (r"after the title|sponsor too early", "sponsor_midroll",
     "Place sponsor mid-roll, not immediately after the title."),
]


def remember_dislike(
    text: str,
    *,
    situation: str = "general",
    context: dict | None = None,
    source: str = "human",
    log=print,
) -> dict:
    """Save a contextual dislike so the system does not repeat it."""
    store = load_store()
    text = text.strip()
    rules = _rules_from_text(text)
    tags = [r["code"] for r in rules]
    event = {
        "at": time.time(),
        "situation": situation,
        "text": text,
        "tags": tags,
        "rules": rules,
        "context": context or {},
        "source": source,
    }
    store.dislikes.append(event)
    store.stats["dislikes_count"] = int(store.stats.get("dislikes_count") or 0) + 1

    # Activate rules globally + per situation
    active = store.active_rules.setdefault("global", {})
    sit = store.active_rules.setdefault(situation, {})
    for r in rules:
        active[r["code"]] = r["instruction"]
        sit[r["code"]] = r["instruction"]

    # Mirror into classic feedback only when not already coming from feedback()
    if source != "feedback":
        store.feedback.append({
            "at": event["at"],
            "subject": situation,
            "sentiment": "not_okay",
            "text": text,
            "tags": tags,
        })
    recompute_priors(store)
    store.save()
    _append_obsidian(event)
    log(f"  dislike saved [{situation}] → rules={tags or ['note_only']}")
    return event


def active_rules_for(situation: str = "general", store=None) -> dict[str, str]:
    """Merged global + situation rules (situation wins on conflict)."""
    store = store or load_store()
    out = dict((store.active_rules or {}).get("global") or {})
    out.update((store.active_rules or {}).get(situation) or {})
    return out


def violations_for_report(report: dict, situation: str = "sponsor") -> list[str]:
    """Compare a QC/feature report against active dislike rules."""
    rules = active_rules_for(situation)
    hits = []
    codes = {i.get("code") for i in (report.get("issues") or [])}
    mapping = {
        "shake": "no_shaky_tails",
        "music_seam": "seamless_music_only",
        "sfx_spam": "no_click_sfx",
        "dated_card": "no_dated_cards",
        "silence": "require_music_on_sponsor",
    }
    for issue_code, rule_code in mapping.items():
        if issue_code in codes and rule_code in rules:
            hits.append(rules[rule_code])
    return hits


def _rules_from_text(text: str) -> list[dict]:
    low = text.lower()
    found = []
    for pat, code, instruction in RULE_PATTERNS:
        if re.search(pat, low):
            found.append({"code": code, "instruction": instruction})
    if not found:
        found.append({
            "code": "custom_" + re.sub(r"[^a-z0-9]+", "_", low)[:40].strip("_"),
            "instruction": f"Do not repeat: {text}",
        })
    # dedupe by code
    seen = set()
    out = []
    for r in found:
        if r["code"] in seen:
            continue
        seen.add(r["code"])
        out.append(r)
    return out


def _append_obsidian(event: dict) -> None:
    path = OBSIDIAN / "Never Again.md"
    OBSIDIAN.mkdir(parents=True, exist_ok=True)
    day = time.strftime("%Y-%m-%d")
    rules = ", ".join(r["code"] for r in event.get("rules") or [])
    line = (
        f"- {day} · **{event['situation']}**: {event['text']} "
        f"`{rules}`"
    )
    if path.exists():
        text = path.read_text()
        if event["text"] in text:
            return
        path.write_text(text.rstrip() + "\n" + line + "\n")
    else:
        path.write_text(
            "# Never Again\n\n"
            "Contextual dislike memory. The editor checks these before delivery.\n\n"
            "## Log (newest at bottom)\n\n" + line + "\n"
        )
