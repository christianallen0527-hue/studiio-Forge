"""Optional silence removal (an IntelliCut-style pass).

Given the per-window silent mask from switch.decide_segments, build the list of
time ranges to cut, then subtract them from the camera segments so the final
concat closes the gaps.
"""

from __future__ import annotations

from .switch import Segment


def silent_cut_intervals(
    silent_mask: list[bool],
    window_sec: float,
    min_gap_sec: float = 1.5,
    keep_pad_sec: float = 0.3,
) -> list[tuple[float, float]]:
    """Return (start, end) ranges of dead air long enough to remove."""
    cuts: list[tuple[float, float]] = []
    i, n = 0, len(silent_mask)
    while i < n:
        if not silent_mask[i]:
            i += 1
            continue
        j = i
        while j < n and silent_mask[j]:
            j += 1
        gap = (j - i) * window_sec
        if gap >= min_gap_sec:
            start = i * window_sec + keep_pad_sec
            end = j * window_sec - keep_pad_sec
            if end > start:
                cuts.append((start, end))
        i = j
    return cuts


def subtract_intervals(
    segments: list[Segment], cuts: list[tuple[float, float]]
) -> list[Segment]:
    """Remove `cuts` from `segments`, splitting/trimming as needed."""
    if not cuts:
        return segments
    cuts = sorted(cuts)
    out: list[Segment] = []
    for seg in segments:
        pieces = [(seg.start, seg.end)]
        for cs, ce in cuts:
            new_pieces = []
            for ps, pe in pieces:
                if ce <= ps or cs >= pe:          # no overlap
                    new_pieces.append((ps, pe))
                    continue
                if cs > ps:                       # keep left part
                    new_pieces.append((ps, cs))
                if ce < pe:                       # keep right part
                    new_pieces.append((ce, pe))
            pieces = new_pieces
        for ps, pe in pieces:
            if pe - ps > 1e-3:
                out.append(Segment(start=ps, end=pe, angle=seg.angle))
    return out


def prune_short_segments(
    segments: list[Segment], min_sec: float = 0.12
) -> list[Segment]:
    """Drop fragments too short for a clean join (after silence/filler cuts).

    Tiny leftovers make ffmpeg xfade/acrossfade clamp to hard-cuts and can
    produce clicky one-frame flashes. Pure helper — wire in pipeline after
    subtract_intervals if desired:
        segments = silence.prune_short_segments(segments)
    """
    if min_sec <= 0:
        return segments
    return [s for s in segments if (s.end - s.start) >= min_sec]
