"""AI Camera Operator — turns one locked-off high-res camera into operated coverage.

A 4K frame contains four 1080p frames. This module plans a sequence of virtual
"shots" (wide / medium / close, framed on the subject) that cut on the natural
breaks in speech — so a single static camera reads like a multi-camera shoot with
a live operator: establish wide, settle into mediums, punch in for emphasis,
reset to wide on a new thought.

Pure planning here (unit-tested); rendering lives in the backends.
"""

from __future__ import annotations

from dataclasses import dataclass

# Fraction of the source frame each shot keeps (smaller = tighter). 16:9 preserved.
SHOT_ZOOM = {"wide": 1.00, "medium": 0.74, "close": 0.56, "punch": 0.46}


@dataclass
class Shot:
    start: float
    end: float
    kind: str                 # wide | medium | close | punch
    zoom: float               # fraction of frame kept (see SHOT_ZOOM)
    cx: float = 0.5           # subject centre, fraction of width
    cy: float = 0.44          # slightly high — leaves headroom
    push: float = 0.0         # extra zoom-in across the shot (0 = static)


def _pick_boundary(bounds, lo, hi, ideal):
    """Nearest speech boundary within [lo, hi]; else the ideal time."""
    best, bestd = None, 1e9
    for b in bounds:
        if lo <= b <= hi:
            d = abs(b - ideal)
            if d < bestd:
                best, bestd = b, d
    return best if best is not None else ideal


def plan_shots(
    duration: float,
    cues=None,
    subject=(0.5, 0.44),
    min_shot: float = 3.2,
    max_shot: float = 7.5,
    energy=None,               # optional list of (time, level0..1) for emphasis
    intensity: str = "dynamic",  # calm | dynamic | punchy
) -> list[Shot]:
    """Return an operated shot list covering [0, duration]."""
    bounds = sorted(c.end for c in (cues or []))
    q_times = [c.end for c in (cues or []) if "?" in getattr(c, "text", "")]

    if intensity == "calm":
        target, order = (max_shot + min_shot) * 0.6, ["wide", "medium", "wide", "medium"]
        allow_push = False
    elif intensity == "punchy":
        target, order = min_shot * 1.15, ["wide", "close", "medium", "punch", "close", "medium"]
        allow_push = True
    else:
        target, order = (min_shot + max_shot) / 2, ["wide", "medium", "close", "medium", "wide", "close"]
        allow_push = True

    cx, cy = subject
    shots: list[Shot] = []
    t, i = 0.0, 0
    while t < duration - 0.4:
        ideal = min(t + target, duration)
        cut = _pick_boundary(bounds, t + min_shot, min(t + max_shot, duration), ideal)
        cut = max(min(cut, duration), t + 0.8)
        kind = "wide" if i == 0 else order[i % len(order)]
        # Emphasis: if a question ends near this shot, go tight.
        if any(t <= q <= cut for q in q_times) and kind not in ("close", "punch"):
            kind = "close"
        # Never repeat the exact framing back-to-back.
        if shots and shots[-1].kind == kind and kind != "wide":
            kind = "medium" if kind != "medium" else "wide"
        z = SHOT_ZOOM[kind]
        push = 0.06 if (allow_push and kind in ("close", "punch")) else \
               0.03 if (allow_push and kind == "medium") else 0.0
        shots.append(Shot(round(t, 3), round(cut, 3), kind, z, cx, cy, push))
        t, i = cut, i + 1

    if shots:                                   # snap the tail exactly to the end
        shots[-1].end = round(duration, 3)
    return shots


def subtract_from_shots(shots: list[Shot], cuts) -> list[Shot]:
    """Remove filler/pause intervals from the shot list, preserving each framing."""
    if not cuts:
        return shots
    cuts = sorted(cuts)
    out: list[Shot] = []
    for s in shots:
        pieces = [(s.start, s.end)]
        for cs, ce in cuts:
            nxt = []
            for ps, pe in pieces:
                if ce <= ps or cs >= pe:
                    nxt.append((ps, pe))
                    continue
                if cs > ps:
                    nxt.append((ps, cs))
                if ce < pe:
                    nxt.append((ce, pe))
            pieces = nxt
        for ps, pe in pieces:
            if pe - ps > 0.05:
                out.append(Shot(round(ps, 3), round(pe, 3), s.kind, s.zoom,
                                s.cx, s.cy, s.push))
    return out


def apply_facetrack(shots: list[Shot], track_list, headroom: float = 0.08) -> list[Shot]:
    """Frame each shot ON the tracked subject with rule-of-thirds headroom.

    The face is placed a touch above centre (crop centre sits just below the face
    centre by headroom*zoom), so tighter shots get proportionally more headroom —
    the way an operator frames a talking head.
    """
    from . import facetrack
    for s in shots:
        cx, cy, fh = facetrack.subject_for(track_list, s.start, s.end)
        s.cx = min(0.85, max(0.15, cx))
        s.cy = min(0.62, max(0.28, cy + headroom * s.zoom))
    return shots


def crop_rect(shot: Shot, W: int, H: int, at: float = 0.0):
    """Even-pixel crop (w, h, x, y) for this shot; `at` in [0,1] applies the push."""
    z = shot.zoom - shot.push * max(0.0, min(1.0, at))
    z = max(0.34, z)
    cw = min(W, (round(W * z) // 2) * 2)
    ch = min(H, (round(H * z) // 2) * 2)
    x = int(round(W * shot.cx - cw / 2))
    y = int(round(H * shot.cy - ch / 2))
    x = max(0, min(W - cw, x))
    y = max(0, min(H - ch, y))
    return cw, ch, x, y
