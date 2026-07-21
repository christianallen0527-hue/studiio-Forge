"""Daily learning job — always learning from top public content.

Run every day (launchd/cron or UI button):
  python -m autoedit.learning daily

Pulls fresh public examples for podcast / talking_head / long_form / shorts,
studies them (metadata-first; optional samples), updates category priors, and
writes a daily journal into Obsidian.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from .curriculum import CATEGORIES, all_category_ids
from .store import OBSIDIAN, DEFAULT_DIR, load_store, recompute_priors
from .youtube_study import ensure_ytdlp, study_youtube, _ytdlp_cmd


def run_daily(
    *,
    categories: list[str] | None = None,
    per_category: int = 3,
    download_sample: bool = False,
    log=print,
) -> dict:
    """Study top public videos across categories. Safe to run unattended."""
    cats = categories or all_category_ids()
    store = load_store()
    ytdlp = ensure_ytdlp(log=log)
    day = time.strftime("%Y-%m-%d")
    journal: dict = {
        "day": day,
        "started_at": time.time(),
        "categories": {},
        "errors": [],
    }

    seen_urls = {r.get("source") for r in store.references}

    for cat_id in cats:
        spec = CATEGORIES[cat_id]
        log(f"\n══ Daily learn · {spec['label']} ══")
        urls = _discover_urls(ytdlp, spec["searches"], limit=per_category * 2, log=log)
        studied = []
        for url in urls:
            if url in seen_urls:
                continue
            if len(studied) >= per_category:
                break
            try:
                result = study_youtube(
                    url,
                    labels=list(spec["labels"]) + ["daily", day],
                    notes=f"daily:{cat_id}",
                    download_sample=download_sample,
                    store=store,
                    log=log,
                )
                # tag category on the last reference
                if store.references:
                    store.references[-1]["category"] = cat_id
                studied.append({
                    "url": url,
                    "title": (result.get("meta") or {}).get("title"),
                    "labels": result.get("labels"),
                })
                seen_urls.add(url)
                _update_category_priors(store, cat_id, result.get("features") or {})
            except Exception as e:  # noqa: BLE001
                msg = f"{cat_id}: {e}"
                journal["errors"].append(msg)
                log(f"  (skip) {msg}")
        journal["categories"][cat_id] = {
            "goal": spec["goal"],
            "studied": studied,
            "count": len(studied),
        }

    store.stats["daily_runs"] = int(store.stats.get("daily_runs") or 0) + 1
    store.stats["last_daily_at"] = time.time()
    store.stats["last_daily_day"] = day
    recompute_priors(store)
    store.save()

    journal["finished_at"] = time.time()
    journal["confidence"] = store.priors.get("confidence")
    journal["stats"] = store.stats
    _write_journal(journal)
    path = DEFAULT_DIR / "daily" / f"{day}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(journal, indent=2))
    log(f"\nDaily learning complete → {path}")
    return journal


def _discover_urls(ytdlp: str, searches: list[str], limit: int, log=print) -> list[str]:
    """Resolve yt-dlp search queries to unique video URLs."""
    urls: list[str] = []
    for q in searches:
        if len(urls) >= limit:
            break
        cmd = _ytdlp_cmd(ytdlp) + [
            "--flat-playlist", "--dump-single-json", "--no-warnings", q,
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
            if proc.returncode != 0:
                log(f"  (search failed) {q}: {proc.stderr[:160]}")
                continue
            data = json.loads(proc.stdout)
            entries = data.get("entries") or [data]
            for ent in entries:
                if not ent:
                    continue
                vid = ent.get("id") or ent.get("url")
                if not vid:
                    continue
                if str(vid).startswith("http"):
                    url = str(vid)
                else:
                    url = f"https://www.youtube.com/watch?v={vid}"
                if url not in urls:
                    urls.append(url)
        except Exception as e:  # noqa: BLE001
            log(f"  (search error) {q}: {e}")
    return urls[:limit]


def _update_category_priors(store, cat_id: str, features: dict) -> None:
    bucket = store.category_priors.setdefault(cat_id, {
        "samples": 0, "median_shot_secs": [], "shake_scores": [],
    })
    bucket["samples"] = int(bucket.get("samples") or 0) + 1
    if features.get("median_shot_sec"):
        arr = list(bucket.get("median_shot_secs") or [])
        arr.append(float(features["median_shot_sec"]))
        bucket["median_shot_secs"] = arr[-40:]
        bucket["median_shot_sec"] = round(
            sorted(bucket["median_shot_secs"])[len(bucket["median_shot_secs"]) // 2], 2)
    if features.get("shake_score") is not None:
        arr = list(bucket.get("shake_scores") or [])
        arr.append(float(features["shake_score"]))
        bucket["shake_scores"] = arr[-40:]
    store.category_priors[cat_id] = bucket


def _write_journal(journal: dict) -> None:
    OBSIDIAN.mkdir(parents=True, exist_ok=True)
    path = OBSIDIAN / "Daily Learning Journal.md"
    lines = [
        f"## {journal['day']}",
        "",
        f"Confidence: **{journal.get('confidence')}** · "
        f"errors: {len(journal.get('errors') or [])}",
        "",
    ]
    for cat_id, block in (journal.get("categories") or {}).items():
        lines.append(f"### {cat_id} ({block.get('count', 0)})")
        lines.append(f"_{block.get('goal', '')}_")
        for item in block.get("studied") or []:
            title = item.get("title") or item.get("url")
            lines.append(f"- [{title}]({item.get('url')})")
        lines.append("")
    header = (
        "# Daily Learning Journal\n\n"
        "Auto-written by `python -m autoedit.learning daily`.\n\n"
    )
    if path.exists():
        prev = path.read_text()
        # newest first
        if prev.startswith("# Daily"):
            # insert after header
            idx = prev.find("\n## ")
            if idx == -1:
                path.write_text(prev.rstrip() + "\n\n" + "\n".join(lines))
            else:
                path.write_text(prev[:idx] + "\n" + "\n".join(lines) + prev[idx:])
        else:
            path.write_text(header + "\n".join(lines) + "\n" + prev)
    else:
        path.write_text(header + "\n".join(lines))


def due_for_daily(store=None, now: float | None = None) -> bool:
    """True if we have not successfully run daily learning today."""
    store = store or load_store()
    now = now or time.time()
    last = store.stats.get("last_daily_day")
    return last != time.strftime("%Y-%m-%d", time.localtime(now))
