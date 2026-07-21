"""Pick highlight moments and render vertical (9:16) shorts with captions.

Captions are burned in with Pillow-rendered PNG overlays (this ffmpeg has no
subtitles/drawtext filter), composited via the `overlay` filter.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import ffmpeg, textgen
from .config import Config
from .transcribe import Cue

_W, _H = 1080, 1920


@dataclass
class Highlight:
    start: float
    end: float
    cues: list[Cue]
    score: float


def pick_highlights(
    cues: list[Cue], min_sec: float, max_sec: float, count: int
) -> list[Highlight]:
    ideal = (min_sec + max_sec) / 2.0
    candidates: list[Highlight] = []
    for i in range(len(cues)):
        j = i
        while j < len(cues) and (cues[j].end - cues[i].start) <= max_sec:
            dur = cues[j].end - cues[i].start
            if dur >= min_sec:
                subset = cues[i:j + 1]
                text = " ".join(c.text for c in subset)
                words = len(text.split())
                score = words + (6 if "?" in text else 0) - 0.5 * abs(dur - ideal)
                candidates.append(Highlight(cues[i].start, cues[j].end, subset, score))
            j += 1

    candidates.sort(key=lambda h: h.score, reverse=True)
    chosen: list[Highlight] = []
    for cand in candidates:
        if any(not (cand.end <= c.start or cand.start >= c.end) for c in chosen):
            continue
        chosen.append(cand)
        if len(chosen) >= count:
            break
    chosen.sort(key=lambda h: h.start)
    return chosen


def render_short(
    cfg: Config,
    long_form: Path,
    hl: Highlight,
    out_path: Path,
    workdir: Path,
    captions: bool,
) -> Path:
    dur = hl.end - hl.start
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cap_dir = workdir / "caps"
    cap_dir.mkdir(parents=True, exist_ok=True)

    inputs = ["-ss", f"{hl.start:.3f}", "-t", f"{dur:.3f}", "-i", str(long_form)]
    filters = [f"[0:v]scale={_W}:{_H}:force_original_aspect_ratio=increase,"
               f"crop={_W}:{_H},format=yuv420p[base]"]
    label = "base"
    idx = 1
    if captions and hl.cues:
        for i, c in enumerate(hl.cues):
            s, e = c.start - hl.start, c.end - hl.start
            if e <= 0 or s >= dur:
                continue
            s, e = max(0.0, s), min(dur, e)
            png, ph = textgen.caption_png(c.text, _W,
                                          cap_dir / f"{out_path.stem}_{i}.png")
            inputs += ["-loop", "1", "-i", str(png)]
            y = _H - ph - int(_H * 0.12)
            filters.append(
                f"[{label}][{idx}:v]overlay=(W-w)/2:{y}:"
                f"enable='between(t,{s:.3f},{e:.3f})'[c{idx}]")
            label = f"c{idx}"
            idx += 1

    ffmpeg.run([
        "ffmpeg", "-y", "-v", "error", *inputs,
        "-filter_complex", ";".join(filters),
        "-map", f"[{label}]", "-map", "0:a", "-t", f"{dur:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart", str(out_path),
    ])
    return out_path
