"""Footage Review — watch the clips before editing.

Deterministic analysis (precise, no guessing):
  * audio loudness (EBU R128 integrated LUFS + true peak) → too loud / quiet / silent
  * orientation (container rotate tag, else YuNet face vote at 0° vs 180°) → upside-down
  * black / frozen / silent detection → unusable ranges
  * a simple content read (talking-head vs b-roll vs unusable)

Optional semantic layer: a local Ollama vision model, if one is installed.

Everything degrades gracefully — a missing tool just drops that finding.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

from . import ffmpeg

TARGET_LUFS = -14.0          # YouTube / podcast loudness target
MAX_GAIN_DB = 24.0           # avoid turning near-silence/noise into dangerous levels
EDGE_TOLERANCE_SEC = 0.5     # black detection may land on a nearby keyframe
MIN_EDGE_TRIM_SEC = 0.25     # ignore flashes and uncertain one-frame detections

# Set AUTOEDIT_PROFILE=1 to print per-phase timings from analyze().
_PROFILE = bool(os.environ.get("AUTOEDIT_PROFILE"))


def _timed(label: str, fn):
    """Run fn(); if profiling is on, print how long it took."""
    if not _PROFILE:
        return fn()
    t = time.perf_counter()
    out = fn()
    print(f"    [{time.perf_counter() - t:6.2f}s] {label}")
    return out


# ── audio ─────────────────────────────────────────────────────────────────────
def _has_audio(path: str) -> bool:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
         "stream=codec_type", "-of", "csv=p=0", path],
        capture_output=True, text=True).stdout
    return "audio" in out


def _loudness(path: str):
    """Integrated LUFS + true-peak dBFS via ebur128. (None, None) if no audio."""
    r = subprocess.run(
        ["ffmpeg", "-nostats", "-hide_banner", "-i", path, "-t", "180",
         "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True).stderr
    lufs = peak = None
    mi = re.findall(r"I:\s*(-?\d+(?:\.\d+)?)\s*LUFS", r)
    if mi:
        lufs = float(mi[-1])
    mp = re.findall(r"Peak:\s*(-?\d+(?:\.\d+)?)\s*dBFS", r)
    if mp:
        peak = float(mp[-1])
    return lufs, peak


def _audio_verdict(has_audio, lufs, peak):
    if not has_audio or lufs is None or lufs < -70:
        return "silent", "No audio — add calm background music (b-roll)."
    if peak is not None and peak > -1.0:
        return "loud", f"Peaks at {peak:.1f} dBFS (clipping risk) — pull down + limit."
    if lufs > -11:
        return "loud", f"Hot at {lufs:.1f} LUFS — bring down to {TARGET_LUFS:.0f}."
    if lufs < -23:
        return "quiet", f"Low at {lufs:.1f} LUFS — lift to {TARGET_LUFS:.0f}."
    return "good", f"Clean at {lufs:.1f} LUFS."


def analyze_audio(path: str) -> dict:
    """Review an isolated microphone without attempting video-only analysis."""
    has_audio = _has_audio(path)
    lufs, peak = _loudness(path) if has_audio else (None, None)
    verdict, fix = _audio_verdict(has_audio, lufs, peak)
    return {
        "name": Path(path).name,
        "path": path,
        "has_audio": has_audio,
        "loudness_lufs": lufs,
        "peak_db": peak,
        "audio_verdict": verdict,
        "audio_fix": fix,
    }


# ── orientation ─────────────────────────────────────────────────────────────────
def _meta_rotation(path: str):
    # NOTE: use *stream*-level side data (`stream_side_data`).  The bare
    # `side_data=rotation` selector makes ffprobe walk every packet/frame,
    # which on a 4K HEVC clip fully decodes the file (~80s).  The stream-level
    # display-matrix carries the rotation and reads in a few milliseconds.
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream_tags=rotate:stream_side_data=rotation", "-of", "json", path],
        capture_output=True, text=True).stdout
    try:
        data = json.loads(out)
        for s in data.get("streams", []):
            rot = (s.get("tags", {}) or {}).get("rotate")
            if rot:
                return int(float(rot)) % 360
            for sd in s.get("side_data_list", []) or []:
                if "rotation" in sd:
                    return int(float(sd["rotation"])) % 360
    except Exception:                                  # noqa: BLE001
        pass
    return None


_DET = None


def _detector(dw, dh):
    global _DET
    import cv2
    from . import facetrack
    if _DET is None:
        _DET = cv2.FaceDetectorYN.create(facetrack._model_path(), "", (dw, dh),
                                         score_threshold=0.5)
    _DET.setInputSize((dw, dh))
    return _DET


def _face_orientation(path: str, samples: int = 3):
    """Vote 0° vs 180° by which finds more/larger plausible faces. None if undecidable.

    Frames are pulled with a fast ffmpeg keyframe seek (not a full decode), and the
    YuNet model is cached across clips.
    """
    try:
        import cv2
        import numpy as np
    except Exception:                                  # noqa: BLE001
        return None
    dur = max(ffmpeg.probe_duration(path), 1.0)
    up = down = 0.0
    for i in range(1, samples + 1):
        t = dur * i / (samples + 1)
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1",
             "-vf", "scale=640:-2", "-f", "image2pipe", "-vcodec", "mjpeg", "-"],
            capture_output=True).stdout
        if not raw:
            continue
        arr = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if arr is None:
            continue
        h, w = arr.shape[:2]
        det = _detector(w, h)
        for tag, img in (("up", arr), ("down", cv2.rotate(arr, cv2.ROTATE_180))):
            _, faces = det.detect(img)
            best = 0.0
            for f in (faces if faces is not None else []):
                fh = float(f[3]) / h
                if 0.05 <= fh <= 0.4:
                    best = max(best, fh)
            if tag == "up":
                up += best
            else:
                down += best
    if up == 0 and down == 0:
        return None
    return 180 if down > up * 1.3 else 0


def _orientation(path: str):
    rot = _meta_rotation(path)
    if rot in (90, 180, 270):
        return rot, f"Metadata says {rot}° — auto-rotate."
    face = _face_orientation(path)
    if face == 180:
        return 180, "Upside-down (faces are inverted) — rotate 180°."
    if face == 0:
        return 0, "Upright."
    return 0, "Upright (no face to confirm)."


# ── black / frozen ──────────────────────────────────────────────────────────────
def _black_ranges(path: str):
    # Decode only keyframes (huge speed-up on 4K HEVC); enough to spot dead frames.
    r = subprocess.run(
        ["ffmpeg", "-nostats", "-hide_banner", "-skip_frame", "nokey", "-i", path,
         "-an", "-vf", "scale=320:-2,blackdetect=d=0.1:pic_th=0.98", "-f", "null", "-"],
        capture_output=True, text=True).stderr
    return re.findall(r"black_start:(\d+(?:\.\d+)?)\s+black_end:(\d+(?:\.\d+)?)", r)


# ── main ────────────────────────────────────────────────────────────────────────
def analyze(path: str, ollama: bool = True) -> dict:
    name = Path(path).name
    dur = ffmpeg.probe_duration(path)
    w = h = 0
    fps = 0.0
    try:
        meta = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=width,height,r_frame_rate", "-of", "json", path],
            capture_output=True, text=True).stdout
        s = json.loads(meta)["streams"][0]
        w, h = s.get("width", 0), s.get("height", 0)
        num, den = (s.get("r_frame_rate", "0/1").split("/") + ["1"])[:2]
        fps = round(float(num) / float(den or 1), 2)
    except Exception:                                  # noqa: BLE001
        pass

    has_audio = _timed("has_audio", lambda: _has_audio(path))
    lufs, peak = _timed("loudness", lambda: _loudness(path)) if has_audio else (None, None)
    a_verdict, a_fix = _audio_verdict(has_audio, lufs, peak)
    orient, o_note = _timed("orientation", lambda: _orientation(path))
    blacks = _timed("black_ranges", lambda: _black_ranges(path))

    flags, recs = [], []
    if orient:
        flags.append(f"rotate {orient}°")
        recs.append(o_note)
    if a_verdict != "good":
        flags.append(a_verdict + " audio")
        recs.append(a_fix)
    else:
        recs.append(a_fix)
    if blacks:
        flags.append(f"{len(blacks)} black gap(s)")
        recs.append("Trim black/dead frames.")

    content = ("broll" if not has_audio else "talking")
    if len(blacks) >= 3 and dur < 4:
        content = "unusable"
    usable = content != "unusable"

    result = {
        "name": name, "path": path,
        "duration": round(dur, 1), "width": w, "height": h, "fps": fps,
        "has_audio": has_audio, "loudness_lufs": lufs, "peak_db": peak,
        "audio_verdict": a_verdict, "audio_fix": a_fix,
        "orientation": orient, "orientation_note": o_note,
        "black_ranges": [[float(a), float(b)] for a, b in blacks],
        "content": content, "usable": usable,
        "flags": flags, "recommendations": recs,
    }

    if ollama:
        # Additive semantic layer — never replaces deterministic findings above.
        # Prefer structured vision.review_visual; fall back to a one-liner describe.
        try:
            from . import vision as vision_mod
            vis = vision_mod.review_visual(
                path,
                # ollama=True means "try"; AUTOEDIT_VISION=0 can still force-off.
                enabled=("off" if vision_mod.resolve_enabled(None) == "off" else "on"),
                duration=dur,
                workdir=str(Path(path).parent / ".autoedit_vision"),
            )
            if vis and not vis.get("skipped"):
                vision_mod.merge_vision_into_review(result, vis)
            elif vis:
                result["vision"] = vis
            else:
                desc = _ollama_describe(path)
                if desc:
                    result["vision"] = {"description": desc, "ok": True, "skipped": False}
        except Exception:                              # noqa: BLE001
            desc = _ollama_describe(path)
            if desc:
                result["vision"] = {"description": desc, "ok": True, "skipped": False}
    return result


def analyze_visual(path: str, **kwargs) -> dict:
    """Deterministic analyze + structured Ollama vision (explicit opt-in helper)."""
    from . import vision as vision_mod
    base = analyze(path, ollama=False)
    vis = vision_mod.review_visual(path, duration=base.get("duration"), **kwargs)
    return vision_mod.merge_vision_into_review(base, vis)


def qc_finished_edit(path: str, **kwargs) -> dict:
    """Post-edit visual QC wrapper (delegates to ``vision.qc_edit``)."""
    from . import vision as vision_mod
    return vision_mod.qc_edit(path, **kwargs)


# ── edit decisions ───────────────────────────────────────────────────────────
def apply_review(clip_review: dict) -> dict:
    """Turn one clip's analysis (an ``analyze()`` result) into concrete edits.

    Returns a small, machine-actionable decision dict:
      * ``rotate``        – 0 or 180, degrees to spin the clip so faces sit upright
      * ``audio_gain_db`` – dB to add to hit TARGET_LUFS (-14); 0 when already
                            good or when the clip is silent (nothing to lift)
      * ``trim_ranges``   – confident black / dead head and tail spans to cut;
                            interior ranges are left for editorial review
      * ``add_music``     – True for silent b-roll (needs a music bed under it)

    Tolerant of partial dicts: missing keys fall back to safe no-op decisions.
    """
    orient = clip_review.get("orientation") or 0
    rotate = 180 if orient == 180 else 0

    verdict = clip_review.get("audio_verdict")
    lufs = clip_review.get("loudness_lufs")
    # Silent or already-good clips get no gain change; otherwise lift/pull to -14.
    # A peak-aware ceiling and a hard cap prevent a quiet/noisy source from being
    # amplified into clipping or an extreme noise floor.
    if verdict in (None, "good", "silent") or lufs is None or lufs < -70:
        audio_gain_db = 0.0
    else:
        proposed = TARGET_LUFS - float(lufs)
        peak = clip_review.get("peak_db")
        if proposed > 0 and peak is not None:
            proposed = min(proposed, -1.5 - float(peak))
        audio_gain_db = round(max(-MAX_GAIN_DB, min(MAX_GAIN_DB, proposed)), 1)

    duration = clip_review.get("duration")
    try:
        duration = float(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration = None
    trim_ranges = []
    for raw in clip_review.get("black_ranges", []) or []:
        try:
            a, b = float(raw[0]), float(raw[1])
        except (TypeError, ValueError, IndexError):
            continue
        a = max(0.0, a)
        if duration is not None:
            b = min(duration, b)
        if b - a < MIN_EDGE_TRIM_SEC:
            continue
        at_head = a <= EDGE_TOLERANCE_SEC
        at_tail = duration is not None and b >= duration - EDGE_TOLERANCE_SEC
        if at_head or at_tail:
            trim_ranges.append([a, b])

    add_music = bool(verdict == "silent" and clip_review.get("content") == "broll")

    return {
        "rotate": rotate,
        "audio_gain_db": audio_gain_db,
        "trim_ranges": trim_ranges,
        "add_music": add_music,
    }


def apply_session(session: dict) -> list[dict]:
    """Map :func:`apply_review` over every clip in a ``review_session`` result."""
    return [apply_review(c) for c in session.get("clips", [])]


def _ollama_describe(path: str, model: str = "moondream"):
    """Optional: a local vision model's one-line read of a representative frame.

    Kept as a lightweight fallback when the structured ``vision`` module path
    fails. Prefer ``vision.review_visual`` / ``analyze_visual`` for full scoring.
    """
    try:
        import base64
        import urllib.request
        from . import vision as vision_mod
        frames = vision_mod.sample_frames(path, n=1)
        if not frames:
            return None
        frame = Path(frames[0]["path"])
        b64 = base64.b64encode(frame.read_bytes()).decode()
        base_url = os.environ.get("AUTOEDIT_VISION_URL", "http://127.0.0.1:11434")
        model = os.environ.get("AUTOEDIT_VISION_MODEL", model)
        req = urllib.request.Request(
            f"{base_url.rstrip('/')}/api/generate",
            data=json.dumps({
                "model": model, "prompt":
                "In one short sentence, what is happening in this video frame? "
                "Is it a person talking to camera, b-roll, or an unusable shot?",
                "images": [b64], "stream": False}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.loads(r.read()).get("response", "").strip()
    except Exception:                                  # noqa: BLE001
        return None


def review_session(paths: list[str], log=print, ollama: bool = True) -> dict:
    clips = []
    for p in paths:
        log(f"  reviewing {Path(p).name}…")
        clips.append(analyze(p, ollama=ollama))
    usable = sum(1 for c in clips if c["usable"])
    fixes = sum(len(c["recommendations"]) for c in clips)
    return {"clips": clips, "usable": usable, "total": len(clips), "fixes": fixes}


def review_session_visual(paths: list[str], log=print, **kwargs) -> dict:
    """Session helper: deterministic review + structured vision for every clip."""
    from . import vision as vision_mod
    clips = []
    for p in paths:
        log(f"  reviewing {Path(p).name}…")
        clips.append(analyze_visual(p, log=log, **kwargs))
    usable = sum(1 for c in clips if c.get("usable"))
    fixes = sum(len(c.get("recommendations") or []) for c in clips)
    vision_ok = sum(
        1 for c in clips
        if isinstance(c.get("vision"), dict) and c["vision"].get("ok")
    )
    return {
        "clips": clips, "usable": usable, "total": len(clips), "fixes": fixes,
        "vision_ok": vision_ok,
        "vision_mode": vision_mod.resolve_enabled(kwargs.get("enabled")),
    }
