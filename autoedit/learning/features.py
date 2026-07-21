"""Extract editorial features from a local video (pacing, loudness, shake)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .. import ffmpeg


def extract_features(path: str | Path, log=print) -> dict:
    """Lightweight, deterministic editorial fingerprint."""
    path = str(path)
    dur = ffmpeg.probe_duration(path)
    feat: dict = {
        "duration_sec": round(dur, 3),
        "has_audio": _has_audio(path),
        "median_shot_sec": None,
        "cut_count_est": None,
        "loudness_lufs": None,
        "shake_score": None,
        "dark_card_ratio": None,
        "uses_dissolves": None,
    }
    try:
        feat["loudness_lufs"] = _lufs(path)
    except Exception:  # noqa: BLE001
        pass
    try:
        shots = _estimate_cuts(path, dur)
        feat["cut_count_est"] = shots["count"]
        feat["median_shot_sec"] = shots["median_sec"]
    except Exception as e:  # noqa: BLE001
        log(f"  (cut estimate skipped: {e})")
    try:
        from .. import sponsor_qc
        feat["shake_score"] = round(sponsor_qc._shake_score(path, start_ratio=0.0), 2)
        feat["dark_card_ratio"] = round(sponsor_qc._dated_card_ratio(path), 3)
    except Exception:  # noqa: BLE001
        pass
    # Heuristic: many soft joins if cut count low relative to duration
    if feat["median_shot_sec"] and feat["median_shot_sec"] >= 2.5:
        feat["uses_dissolves"] = True
    return feat


def _has_audio(path: str) -> bool:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=codec_type", "-of", "csv=p=0", path],
        capture_output=True, text=True,
    ).stdout.strip()
    return bool(out)


def _lufs(path: str) -> float | None:
    proc = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", path, "-vn",
         "-filter_complex", "ebur128", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    for line in (proc.stderr or "").splitlines():
        if "I:" in line and "LUFS" in line:
            try:
                return float(line.split("I:")[1].split("LUFS")[0].strip())
            except (IndexError, ValueError):
                return None
    return None


def _estimate_cuts(path: str, dur: float) -> dict:
    """Scene-change estimate via ffmpeg select+score (fast, approximate)."""
    # lavfi freezedetect won't give cuts; use select='gt(scene,0.35)'
    proc = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", path,
         "-vf", "select='gt(scene,0.32)',showinfo", "-vsync", "vfr",
         "-f", "null", "-"],
        capture_output=True, text=True,
    )
    times: list[float] = []
    for line in (proc.stderr or "").splitlines():
        if "pts_time:" in line:
            try:
                t = float(line.split("pts_time:")[1].split()[0])
                times.append(t)
            except (IndexError, ValueError):
                pass
    # Build shot lengths from scene boundaries
    bounds = [0.0] + times + [dur]
    lengths = [max(0.05, bounds[i + 1] - bounds[i]) for i in range(len(bounds) - 1)]
    lengths = [x for x in lengths if x < dur * 0.95] or [dur]
    lengths.sort()
    median = lengths[len(lengths) // 2]
    return {"count": max(0, len(times)), "median_sec": round(median, 2)}
