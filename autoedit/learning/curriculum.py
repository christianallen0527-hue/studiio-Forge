"""Category curricula — top podcasts, talking heads, long-form, shorts.

Each day the learner pulls fresh public examples per category via yt-dlp search
and studies them into the growing store. Categories keep *separate* priors so
the editor can specialize.
"""

from __future__ import annotations

CATEGORIES = {
    "podcast": {
        "label": "Top podcasts",
        "goal": "Multi-speaker pacing, clean switches, natural pauses, mid-roll feel.",
        # yt-dlp search queries (public discovery — refreshes over time)
        "searches": [
            "ytsearch5:best podcast interview full episode",
            "ytsearch5:top podcast clips 2024",
            "ytsearch3:Joe Rogan style long podcast excerpt",
            "ytsearch3:business podcast interview studio",
        ],
        "priors_key": "podcast",
        "labels": ["podcast", "multi_speaker"],
    },
    "talking_head": {
        "label": "Top talking-head shows",
        "goal": "Single-speaker clarity, punchy open, B-roll rhythm, retain attention.",
        "searches": [
            "ytsearch5:best talking head youtube essay",
            "ytsearch5:top creator talking head video",
            "ytsearch3:educational talking head high retention",
            "ytsearch3:commentary youtube well edited",
        ],
        "priors_key": "talking_head",
        "labels": ["talking_head", "single_speaker"],
    },
    "long_form": {
        "label": "Top long-form",
        "goal": "Chaptering, cold open, sustained pacing, music beds, act structure.",
        "searches": [
            "ytsearch5:best long form youtube documentary",
            "ytsearch5:high retention long form video essay",
            "ytsearch3:longform interview masterclass editing",
        ],
        "priors_key": "long_form",
        "labels": ["long_form"],
    },
    "shorts": {
        "label": "Top shorts",
        "goal": "Hook in 1s, vertical framing energy, caption timing, loopability.",
        "searches": [
            "ytsearch5:best youtube shorts 2024",
            "ytsearch5:viral short form vertical video",
            "ytsearch3:top tiktok style youtube shorts editing",
        ],
        "priors_key": "shorts",
        "labels": ["shorts", "vertical"],
    },
}


def all_category_ids() -> list[str]:
    return list(CATEGORIES.keys())


def category_spec(cat_id: str) -> dict:
    if cat_id not in CATEGORIES:
        raise KeyError(f"Unknown category '{cat_id}'. Choose from {all_category_ids()}")
    return CATEGORIES[cat_id]
