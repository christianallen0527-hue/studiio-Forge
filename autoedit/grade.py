"""Automatic cinematic color grade.

Analyses the footage (black point, white point, colour cast), then builds a
corrective grade: stretch the washed-out contrast back to full range, neutralise
the cast, add a filmic mid-curve and a touch of saturation.

The *same* transform is emitted two ways so both engines match:
  * `ffmpeg_filter()` — a filter chain for the ffmpeg operator/assemble path.
  * `write_cube()`    — a 3D .cube LUT for the Resolve render path (SetLUT).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from . import ffmpeg


def analyze(video: str, n: int = 20, w: int = 160, h: int = 90) -> dict:
    """Sample the video and measure levels + colour balance."""
    dur = max(ffmpeg.probe_duration(video), 1.0)
    fps = max(0.05, n / dur)
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"fps={fps},scale={w}:{h}",
         "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
        capture_output=True).stdout
    px = (len(raw) // (w * h * 3)) * (w * h * 3)
    a = np.frombuffer(raw[:px], np.uint8).reshape(-1, 3).astype(np.float32)
    if a.size == 0:
        return {"black": 0.0, "white": 1.0, "wb": [1.0, 1.0, 1.0]}
    lum = a[:, 0] * 0.299 + a[:, 1] * 0.587 + a[:, 2] * 0.114
    black = float(np.percentile(lum, 2)) / 255.0
    white = float(np.percentile(lum, 98)) / 255.0
    means = a.mean(axis=0)
    gray = float(means.mean())
    # partial white balance (blend 60%) toward neutral, clamped
    wb = [float(np.clip(1 + 0.6 * (gray / max(m, 1e-3) - 1), 0.8, 1.25)) for m in means]
    return {"black": black, "white": max(white, black + 0.2), "wb": wb}


def _curve_points(black: float, white: float):
    """Piecewise film curve: stretch black/white + gentle S in the mids."""
    span = max(white - black, 0.25)
    return [
        (0.0, 0.0),
        (black, 0.015),
        (black + span * 0.35, 0.32),     # lift lower-mids a touch
        (black + span * 0.65, 0.72),     # hold upper-mids (contrast)
        (white, 0.985),
        (1.0, 1.0),
    ]


def ffmpeg_filter(g: dict, saturation: float = 1.18, contrast: float = 1.06) -> str:
    pts = " ".join(f"{max(0,min(1,x)):.3f}/{y:.3f}" for x, y in _curve_points(g["black"], g["white"]))
    wr, wg, wb = g["wb"]
    return (f"colorchannelmixer=rr={wr:.3f}:gg={wg:.3f}:bb={wb:.3f},"
            f"curves=all='{pts}',"
            f"eq=saturation={saturation:.2f}:contrast={contrast:.2f}")


def write_cube(g: dict, path: str, size: int = 33,
               saturation: float = 1.18, contrast: float = 1.06) -> Path:
    """Emit a .cube LUT applying the same WB + tone-curve + saturation."""
    pts = _curve_points(g["black"], g["white"])
    xs = np.array([p[0] for p in pts]); ys = np.array([p[1] for p in pts])
    wb = np.array(g["wb"], np.float32)

    grid = np.linspace(0, 1, size)
    lines = ["TITLE \"AutoGrade\"", f"LUT_3D_SIZE {size}"]
    for b in grid:                      # cube order: R fastest, then G, then B
        for gch in grid:
            for r in grid:
                rgb = np.clip(np.array([r, gch, b], np.float32) * wb, 0, 1)
                rgb = np.interp(rgb, xs, ys)                # tone curve
                rgb = np.clip((rgb - 0.5) * contrast + 0.5, 0, 1)
                luma = rgb[0] * 0.299 + rgb[1] * 0.587 + rgb[2] * 0.114
                rgb = np.clip(luma + (rgb - luma) * saturation, 0, 1)
                lines.append(f"{rgb[0]:.5f} {rgb[1]:.5f} {rgb[2]:.5f}")
    Path(path).write_text("\n".join(lines) + "\n")
    return Path(path)
