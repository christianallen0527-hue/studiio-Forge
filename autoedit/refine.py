"""Transcript-driven smoothing: remove filler words and long pauses.

Produces a list of time intervals to cut out of the master timeline. Those are
then subtracted from the camera segments so the final edit tightens up — the
"um / uh / and", the dead air, and the run-on gaps disappear as clean jump cuts.

Pure logic (no whisper needed here) — unit-tested in selftest.py.
"""

from __future__ import annotations

import re

from .transcribe import Word

# Conservative defaults. "and / so / like / you know" are aggressive — they're
# often legitimate speech — so they live in the config, easy to dial back.
DEFAULT_FILLERS = [
    "um", "uh", "uhm", "erm", "er", "ah", "eh", "hmm", "mmm", "mm",
]


def _norm(text: str) -> str:
    return re.sub(r"[^a-z']", "", text.lower())


def filler_intervals(
    words: list[Word], fillers: list[str], pad: float = 0.02
) -> list[tuple[float, float]]:
    """Time ranges of filler words to cut. Handles multi-word fillers too."""
    filler_set = {f.lower().strip() for f in fillers}
    multi = [f.split() for f in filler_set if " " in f]
    single = {f for f in filler_set if " " not in f}

    norms = [_norm(w.text) for w in words]
    cuts: list[tuple[float, float]] = []
    i = 0
    n = len(words)
    while i < n:
        matched = False
        # Try multi-word phrases first (longest first).
        for phrase in sorted(multi, key=len, reverse=True):
            k = len(phrase)
            if i + k <= n and norms[i:i + k] == phrase:
                cuts.append((words[i].start - pad, words[i + k - 1].end + pad))
                i += k
                matched = True
                break
        if matched:
            continue
        if norms[i] in single:
            cuts.append((words[i].start - pad, words[i].end + pad))
        i += 1
    return cuts


def pause_intervals(
    words: list[Word], max_gap: float = 0.6, keep_pad: float = 0.15
) -> list[tuple[float, float]]:
    """Time ranges of over-long gaps between words to cut (leaving a small pad).

    keep_pad leaves breathing room on each side so the eventual speech join
    (hard cut + micro acrossfade in assemble) does not clip consonants.
    """
    cuts: list[tuple[float, float]] = []
    # Never let pad eat the whole gap (would create a zero/negative cut).
    pad = max(0.0, min(keep_pad, max_gap / 2.0))
    for a, b in zip(words, words[1:]):
        gap = b.start - a.end
        if gap > max_gap:
            start = a.end + pad
            end = b.start - pad
            if end > start:
                cuts.append((start, end))
    return cuts


def merge_intervals(
    intervals: list[tuple[float, float]], join: float = 0.05
) -> list[tuple[float, float]]:
    """Sort and merge overlapping/adjacent cut intervals."""
    ivs = sorted((a, b) for a, b in intervals if b > a)
    if not ivs:
        return []
    out = [list(ivs[0])]
    for a, b in ivs[1:]:
        if a <= out[-1][1] + join:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def build_removals(
    words: list[Word],
    remove_fillers: bool = True,
    fillers: list[str] | None = None,
    remove_pauses: bool = True,
    max_gap: float = 0.6,
    keep_pad: float = 0.15,
) -> list[tuple[float, float]]:
    """Combined, merged list of intervals to remove from the timeline."""
    cuts: list[tuple[float, float]] = []
    if remove_fillers:
        cuts += filler_intervals(words, fillers or DEFAULT_FILLERS)
    if remove_pauses:
        cuts += pause_intervals(words, max_gap, keep_pad)
    return merge_intervals(cuts)
