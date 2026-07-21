"""Ollama-based visual reviewer — additive semantic layer for footage & edits.

Pre-edit (``review_visual`` / ``review_session_visual``):
  blur, composition, obstruction, exposure cues, talking-head vs b-roll,
  orientation confirmation, usability, natural-language recommendations.

Post-edit (``qc_edit``):
  jump-cut roughness, awkward silence cues, title/transition issues,
  caption occlusion, pacing / professional feel.

This never replaces the deterministic review in ``review.py`` (LUFS, YuNet
orientation, blackdetect). When Ollama is down or disabled, every public API
returns a skipped/unknown result — never raises into the deterministic path.

Golden rule (encoded in prompts):
  DO recommend rotate-if-upside-down, trim/reject bad segments, flag blur /
  out-of-frame / obstruction.
  DO NOT recommend color grade or creative reframing/crop/punch-in.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

# ── defaults ──────────────────────────────────────────────────────────────────
DEFAULT_MODEL = "moondream"
DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_TIMEOUT_SEC = 45.0
DEFAULT_SAMPLES = 3
DEFAULT_QC_SAMPLES = 5
DEFAULT_SCALE = 512          # max width for sampled stills
MAX_RETRIES = 1              # one retry after the first failure
ENSURE_WAIT_SEC = 45.0       # how long to wait for ollama serve to come up
ENSURE_POLL_SEC = 0.5

# Issue codes the model is steered toward (schema also accepts free-form).
PRE_EDIT_CODES = frozenset({
    "upside_down", "blurry", "soft_focus", "out_of_frame", "poor_composition",
    "obstruction", "overexposed", "underexposed", "unusable", "broll",
    "talking_head", "unknown",
})
QC_CODES = frozenset({
    "jump_cut", "awkward_silence", "title_issue", "transition_issue",
    "caption_occlusion", "pacing", "rough_edit", "unknown",
})

LogFn = Callable[[str], None]

_ENSURE_LOCK = threading.Lock()
_SERVE_PROC: subprocess.Popen | None = None


class VisionEngineError(RuntimeError):
    """Ollama vision engine could not be started or reached."""


# ── enablement ────────────────────────────────────────────────────────────────
def resolve_enabled(explicit: bool | str | None = None) -> str:
    """Return ``"on"`` or ``"off"``.

    Vision is **hardwired on** for AUTOEDITING FORGE. Only an explicit
    ``enabled="off"`` / ``AUTOEDIT_VISION=0`` turns it off (self-tests).
    Legacy ``auto`` is treated as ``on`` (we start Ollama ourselves).
    """
    if explicit is not None:
        return _norm_enabled(explicit)
    env = os.environ.get("AUTOEDIT_VISION")
    if env is not None and str(env).strip() != "":
        return _norm_enabled(env)
    return "on"


def _norm_enabled(value: bool | str) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    s = str(value).strip().lower()
    if s in ("0", "false", "no", "off", "disabled"):
        return "off"
    # on / auto / required / true / 1 → on (hardwired)
    return "on"


def find_ollama_bin() -> str | None:
    """Locate the ollama CLI (PATH, Homebrew, or the macOS app bundle)."""
    for cand in (
        shutil.which("ollama"),
        "/usr/local/bin/ollama",
        "/opt/homebrew/bin/ollama",
        "/Applications/Ollama.app/Contents/Resources/ollama",
    ):
        if cand and Path(cand).is_file() and os.access(cand, os.X_OK):
            return str(cand)
    return None


def ollama_tags(
    base_url: str = DEFAULT_BASE_URL,
    timeout_sec: float = 2.0,
) -> dict | None:
    """Return ``/api/tags`` JSON, or None if unreachable."""
    try:
        req = urllib.request.Request(
            f"{base_url.rstrip('/')}/api/tags",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout_sec) as r:
            if r.status != 200:
                return None
            return json.loads(r.read().decode("utf-8") or "{}")
    except Exception:                                  # noqa: BLE001
        return None


def ollama_available(
    base_url: str = DEFAULT_BASE_URL,
    timeout_sec: float = 2.0,
) -> bool:
    """Cheap liveness check against ``GET /api/tags``."""
    return ollama_tags(base_url=base_url, timeout_sec=timeout_sec) is not None


def model_installed(
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
) -> bool:
    """True if ``model`` (or ``model:tag``) is present in the local Ollama library."""
    tags = ollama_tags(base_url=base_url, timeout_sec=3.0)
    if not tags:
        return False
    want = model.strip()
    want_base = want.split(":")[0]
    for m in tags.get("models") or []:
        name = str(m.get("name") or m.get("model") or "")
        if name == want or name.startswith(want_base + ":") or name == want_base:
            return True
    return False


def _start_ollama_serve(bin_path: str, log: LogFn | None = None) -> bool:
    """Launch ``ollama serve`` detached if nothing is listening yet."""
    global _SERVE_PROC
    _log = log or (lambda _m: None)
    if ollama_available():
        return True
    # Prefer the macOS app if present (keeps menu-bar lifecycle).
    app = Path("/Applications/Ollama.app")
    if app.is_dir() and sys_platform_is_darwin():
        try:
            subprocess.Popen(
                ["open", "-a", "Ollama"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            _log("  vision: launching Ollama.app…")
        except OSError:
            pass
    try:
        _SERVE_PROC = subprocess.Popen(
            [bin_path, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        _log(f"  vision: started `{bin_path} serve` (pid {_SERVE_PROC.pid})")
        return True
    except OSError as e:
        _log(f"  vision: failed to start ollama serve: {e}")
        return False


def sys_platform_is_darwin() -> bool:
    return os.uname().sysname == "Darwin"


def _wait_until_up(
    base_url: str = DEFAULT_BASE_URL,
    timeout_sec: float = ENSURE_WAIT_SEC,
) -> bool:
    deadline = time.monotonic() + max(1.0, timeout_sec)
    while time.monotonic() < deadline:
        if ollama_available(base_url=base_url, timeout_sec=1.5):
            return True
        time.sleep(ENSURE_POLL_SEC)
    return False


def pull_model(
    model: str = DEFAULT_MODEL,
    bin_path: str | None = None,
    log: LogFn | None = None,
    timeout_sec: float = 600.0,
) -> bool:
    """``ollama pull <model>`` if missing. Returns True when installed."""
    _log = log or (lambda _m: None)
    if model_installed(model):
        return True
    bin_path = bin_path or find_ollama_bin()
    if not bin_path:
        return False
    _log(f"  vision: pulling model `{model}` (one-time)…")
    try:
        r = subprocess.run(
            [bin_path, "pull", model],
            capture_output=True, text=True, timeout=timeout_sec,
        )
        ok = r.returncode == 0 and model_installed(model)
        if not ok:
            _log(f"  vision: pull failed: {(r.stderr or r.stdout or '')[:300]}")
        return ok
    except (OSError, subprocess.SubprocessError) as e:
        _log(f"  vision: pull error: {e}")
        return False


def ensure_ollama(
    *,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    pull: bool = True,
    log: LogFn | None = None,
    wait_sec: float = ENSURE_WAIT_SEC,
) -> dict:
    """Make Ollama + vision model available. Safe to call repeatedly.

    Returns ``{ok, available, model_ready, bin, detail, started}``.
    """
    _log = log or (lambda _m: None)
    with _ENSURE_LOCK:
        started = False
        bin_path = find_ollama_bin()
        if ollama_available(base_url=base_url):
            ready = (not pull) or model_installed(model, base_url=base_url)
            if ready:
                return {
                    "ok": True, "available": True, "model_ready": True,
                    "bin": bin_path, "detail": "ready", "started": False,
                    "model": model, "base_url": base_url,
                }
            if pull and bin_path and pull_model(model, bin_path, log=_log):
                return {
                    "ok": True, "available": True, "model_ready": True,
                    "bin": bin_path, "detail": "model pulled", "started": False,
                    "model": model, "base_url": base_url,
                }
            return {
                "ok": False, "available": True, "model_ready": False,
                "bin": bin_path, "detail": f"model `{model}` missing",
                "started": False, "model": model, "base_url": base_url,
            }

        if not bin_path:
            return {
                "ok": False, "available": False, "model_ready": False,
                "bin": None,
                "detail": "ollama binary not found — install from https://ollama.com",
                "started": False, "model": model, "base_url": base_url,
            }

        _start_ollama_serve(bin_path, log=_log)
        started = True
        if not _wait_until_up(base_url=base_url, timeout_sec=wait_sec):
            return {
                "ok": False, "available": False, "model_ready": False,
                "bin": bin_path,
                "detail": "ollama did not become ready after start",
                "started": started, "model": model, "base_url": base_url,
            }

        model_ready = True
        if pull and not model_installed(model, base_url=base_url):
            model_ready = pull_model(model, bin_path, log=_log)
        return {
            "ok": bool(model_ready),
            "available": True,
            "model_ready": bool(model_ready),
            "bin": bin_path,
            "detail": "ready" if model_ready else f"model `{model}` missing",
            "started": started,
            "model": model,
            "base_url": base_url,
        }


def require_ollama(
    *,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    log: LogFn | None = None,
) -> dict:
    """Like :func:`ensure_ollama` but raises :class:`VisionEngineError` on failure."""
    status = ensure_ollama(model=model, base_url=base_url, pull=True, log=log)
    if not status.get("ok"):
        raise VisionEngineError(
            f"AUTOEDITING FORGE requires Ollama vision ({status.get('detail')}). "
            f"Install Ollama, then re-open the app."
        )
    return status


def should_run_vision(
    explicit: bool | str | None = None,
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
    log: LogFn | None = None,
) -> tuple[bool, str | None]:
    """Decide whether to call Ollama. Hardwired on: auto-starts the engine."""
    mode = resolve_enabled(explicit)
    if mode == "off":
        return False, "vision disabled"
    status = ensure_ollama(model=model, base_url=base_url, pull=True, log=log)
    if status.get("ok"):
        return True, None
    return False, status.get("detail") or "ollama unavailable"


# ── frame sampling ────────────────────────────────────────────────────────────
def sample_times(duration: float, n: int) -> list[float]:
    """Sparse interior sample times (avoids first/last frame)."""
    dur = max(float(duration or 0.0), 0.1)
    n = max(1, int(n))
    if n == 1:
        return [round(dur * 0.4, 3)]
    return [round(dur * i / (n + 1), 3) for i in range(1, n + 1)]


def frame_cache_dir(path: str, workdir: str | Path | None = None) -> Path:
    """Temp frame cache under workdir (or beside the media file)."""
    if workdir:
        root = Path(workdir) / "vision_frames" / Path(path).stem
    else:
        root = Path(path).parent / ".autoedit_vision" / Path(path).stem
    root.mkdir(parents=True, exist_ok=True)
    return root


def extract_frame(
    path: str,
    t: float,
    dest: Path,
    scale: int = DEFAULT_SCALE,
) -> Path | None:
    """Seek-extract one JPEG still. Returns dest on success, else None."""
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and dest.stat().st_size > 0:
            return dest
        cmd = [
            "ffmpeg", "-y", "-v", "error",
            "-ss", f"{t:.3f}", "-i", path,
            "-frames:v", "1",
            "-vf", f"scale={int(scale)}:-2",
            str(dest),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 or not dest.exists() or dest.stat().st_size == 0:
            return None
        return dest
    except Exception:                                  # noqa: BLE001
        return None


def sample_frames(
    path: str,
    n: int = DEFAULT_SAMPLES,
    workdir: str | Path | None = None,
    scale: int = DEFAULT_SCALE,
    duration: float | None = None,
) -> list[dict]:
    """Extract sparse stills; each item is ``{t, path}`` for successful frames."""
    if duration is None:
        try:
            from . import ffmpeg as ff
            duration = ff.probe_duration(path)
        except Exception:                              # noqa: BLE001
            duration = 10.0
    cache = frame_cache_dir(path, workdir)
    out: list[dict] = []
    for t in sample_times(duration, n):
        dest = cache / f"t{t:.2f}.jpg"
        got = extract_frame(path, t, dest, scale=scale)
        if got is not None:
            out.append({"t": t, "path": str(got)})
    return out


# ── prompts ───────────────────────────────────────────────────────────────────
PRE_EDIT_SYSTEM = """You are a footage reviewer for YouTube / podcast / talking-head / shorts.
Judge whether a still from a clip is GOOD or BAD for editorial use.

GOOD footage: subject readable and in frame, reasonably sharp, usable exposure,
clear talking-head OR intentional b-roll, upright orientation.
BAD footage: upside-down, badly blurry/soft, subject mostly out of frame,
lens/hand obstruction, extreme over/under exposure, dead/unusable frame.

ALLOWED recommendations ONLY:
- rotate 180° if upside-down
- trim or reject unusable segments
- flag blur, out-of-frame, obstruction, extreme exposure
- note talking-head vs b-roll

FORBIDDEN (never recommend):
- color grade / LUT / look changes
- creative reframing, crop, punch-in, face-track reframing

Reply with ONLY a JSON object matching the schema. If unsure, use null/unknown
and lower confidence — do not invent certainty."""

PRE_EDIT_SCHEMA_HINT = """{
  "description": "one short sentence of what is visible",
  "content": "talking_head" | "broll" | "unusable" | "unknown",
  "orientation": "upright" | "upside_down" | "unknown",
  "usable": true | false | null,
  "scores": {
    "sharpness": 0.0-1.0,
    "composition": 0.0-1.0,
    "exposure": 0.0-1.0,
    "obstruction_free": 0.0-1.0,
    "overall": 0.0-1.0,
    "confidence": 0.0-1.0
  },
  "issues": [{"code": "blurry|out_of_frame|obstruction|overexposed|underexposed|upside_down|unusable|soft_focus|poor_composition", "severity": "short", "confidence": 0.0-1.0, "severity": "low|medium|high"}],
  "recommendations": ["plain-language editorial fix only"]
}"""

QC_SYSTEM = """You are a post-edit QC reviewer for YouTube / podcast / talking-head / shorts.
Judge whether sampled frames from a FINISHED edit look professionally cut.

Look for: jump-cut roughness between shots, awkward empty/silent-looking holds,
broken or colliding titles/transitions, burned-in captions covering faces/mouths,
overall pacing and professional feel.

ALLOWED recommendations ONLY:
- re-cut rough joins, tighten awkward holds, fix title/caption placement,
  adjust pacing — editorial fixes only.

FORBIDDEN (never recommend):
- color grade / LUT / look changes
- creative reframing, crop, punch-in

Reply with ONLY a JSON object. If the stills are insufficient to judge a
category, mark that score null and note uncertainty — do not invent certainty."""

QC_SCHEMA_HINT = """{
  "description": "one short sentence overall impression",
  "verdict": "good" | "needs_work" | "poor" | "unknown",
  "scores": {
    "cut_smoothness": 0.0-1.0 or null,
    "silence_feel": 0.0-1.0 or null,
    "title_quality": 0.0-1.0 or null,
    "caption_clarity": 0.0-1.0 or null,
    "pacing": 0.0-1.0 or null,
    "professional_feel": 0.0-1.0 or null,
    "overall": 0.0-1.0 or null,
    "confidence": 0.0-1.0
  },
  "issues": [{"code": "jump_cut|awkward_silence|title_issue|transition_issue|caption_occlusion|pacing|rough_edit", "severity": "short", "confidence": 0.0-1.0, "severity": "low|medium|high"}],
  "recommendations": ["plain-language editorial fix only"]
}"""


def _pre_edit_prompt() -> str:
    return (
        f"{PRE_EDIT_SYSTEM}\n\n"
        f"Return JSON only, shape:\n{PRE_EDIT_SCHEMA_HINT}"
    )


def _qc_prompt() -> str:
    return (
        f"{QC_SYSTEM}\n\n"
        f"Return JSON only, shape:\n{QC_SCHEMA_HINT}"
    )


# ── Ollama HTTP ───────────────────────────────────────────────────────────────
def _encode_image(path: str | Path) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode("ascii")


def _generate(
    prompt: str,
    images: list[str],
    *,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
) -> str | None:
    """Call ``/api/generate`` with optional images. Retries once. None on failure."""
    url = f"{base_url.rstrip('/')}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "images": images,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1},
    }
    data = json.dumps(payload).encode("utf-8")
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout_sec) as r:
                body = json.loads(r.read().decode("utf-8", errors="replace"))
            text = (body.get("response") or "").strip()
            if text:
                return text
            last_err = RuntimeError("empty ollama response")
        except Exception as e:                         # noqa: BLE001
            last_err = e
            if attempt < MAX_RETRIES:
                time.sleep(0.4 * (attempt + 1))
                continue
    _ = last_err
    return None


# ── JSON repair + schema ──────────────────────────────────────────────────────
def repair_json(text: str) -> dict | None:
    """Parse model JSON; strip fences / trailing junk; return dict or None."""
    if not text or not str(text).strip():
        return None
    s = str(text).strip()
    # Strip markdown fences
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.I)
        s = re.sub(r"\s*```$", "", s)
    # First object-looking span
    if not s.startswith("{"):
        m = re.search(r"\{.*\}", s, flags=re.S)
        if not m:
            return None
        s = m.group(0)
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    # Trailing-comma repair
    fixed = re.sub(r",\s*([}\]])", r"\1", s)
    try:
        obj = json.loads(fixed)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def _clamp01(v: Any, default: float | None = None) -> float | None:
    if v is None:
        return default
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if x != x:  # NaN
        return default
    return max(0.0, min(1.0, x))


def _as_bool(v: Any) -> bool | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    if s in ("true", "yes", "1", "usable", "good"):
        return True
    if s in ("false", "no", "0", "unusable", "bad"):
        return False
    return None


def _norm_issue(raw: Any, allowed: frozenset[str]) -> dict | None:
    if not isinstance(raw, dict):
        return None
    code = str(raw.get("code") or "unknown").strip().lower().replace(" ", "_")
    if code not in allowed:
        code = "unknown"
    sev = str(raw.get("severity") or "medium").strip().lower()
    if sev not in ("low", "medium", "high"):
        sev = "medium"
    conf = _clamp01(raw.get("confidence"), 0.5)
    detail = str(raw.get("detail") or raw.get("message") or "").strip()
    return {
        "code": code,
        "detail": detail[:400],
        "confidence": conf if conf is not None else 0.5,
        "severity": sev,
    }


def _norm_recs(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        items = [raw]
    elif isinstance(raw, list):
        items = raw
    else:
        return []
    out: list[str] = []
    for item in items:
        s = str(item or "").strip()
        if not s:
            continue
        # Soft filter: drop grade / reframe suggestions if the model slips
        low = s.lower()
        if any(bad in low for bad in (
            "color grade", "colour grade", "lut", "reframe", "punch-in",
            "punch in", "crop the", "face-track", "face track", "zoom in on",
        )):
            continue
        out.append(s[:300])
    return out


def normalize_pre_edit(raw: dict | None) -> dict:
    """Validate / default a pre-edit vision result (pure, no I/O)."""
    raw = raw if isinstance(raw, dict) else {}
    content = str(raw.get("content") or "unknown").strip().lower().replace("-", "_")
    content_map = {
        "talking": "talking_head", "talkinghead": "talking_head",
        "person": "talking_head", "host": "talking_head",
        "b-roll": "broll", "b_roll": "broll",
        "dead": "unusable", "black": "unusable",
    }
    content = content_map.get(content, content)
    if content not in ("talking_head", "broll", "unusable", "unknown"):
        content = "unknown"

    orient = str(raw.get("orientation") or "unknown").strip().lower().replace("-", "_")
    orient_map = {
        "up": "upright", "normal": "upright", "correct": "upright",
        "inverted": "upside_down", "upside": "upside_down", "180": "upside_down",
        "rotated": "upside_down",
    }
    orient = orient_map.get(orient, orient)
    if orient not in ("upright", "upside_down", "unknown"):
        orient = "unknown"

    scores_in = raw.get("scores") if isinstance(raw.get("scores"), dict) else {}
    if "obstruction_free" in scores_in:
        obstruction_free = _clamp01(scores_in.get("obstruction_free"))
    elif "obstruction" in scores_in:
        # Model may report "how obstructed" (higher = worse) — invert to free-ness.
        ob = _clamp01(scores_in.get("obstruction"))
        obstruction_free = None if ob is None else round(1.0 - ob, 3)
    else:
        obstruction_free = None
    scores = {
        "sharpness": _clamp01(scores_in.get("sharpness")),
        "composition": _clamp01(scores_in.get("composition")),
        "exposure": _clamp01(scores_in.get("exposure")),
        "obstruction_free": obstruction_free,
        "overall": _clamp01(scores_in.get("overall")),
        "confidence": _clamp01(scores_in.get("confidence"), 0.0) or 0.0,
    }

    issues = []
    for item in (raw.get("issues") or []):
        ni = _norm_issue(item, PRE_EDIT_CODES)
        if ni:
            issues.append(ni)

    usable = _as_bool(raw.get("usable"))
    if usable is None and content == "unusable":
        usable = False

    desc = str(raw.get("description") or "").strip()[:500]
    recs = _norm_recs(raw.get("recommendations"))

    return {
        "description": desc,
        "content": content,
        "orientation": orient,
        "usable": usable,
        "scores": scores,
        "issues": issues,
        "recommendations": recs,
    }


def normalize_qc(raw: dict | None) -> dict:
    """Validate / default a post-edit QC result (pure, no I/O)."""
    raw = raw if isinstance(raw, dict) else {}
    verdict = str(raw.get("verdict") or "unknown").strip().lower().replace(" ", "_")
    if verdict in ("ok", "pass", "clean"):
        verdict = "good"
    if verdict in ("fail", "bad"):
        verdict = "poor"
    if verdict in ("fix", "warn", "needswork"):
        verdict = "needs_work"
    if verdict not in ("good", "needs_work", "poor", "unknown"):
        verdict = "unknown"

    scores_in = raw.get("scores") if isinstance(raw.get("scores"), dict) else {}
    keys = (
        "cut_smoothness", "silence_feel", "title_quality", "caption_clarity",
        "pacing", "professional_feel", "overall", "confidence",
    )
    scores = {k: _clamp01(scores_in.get(k)) for k in keys}
    if scores["confidence"] is None:
        scores["confidence"] = 0.0

    issues = []
    for item in (raw.get("issues") or []):
        ni = _norm_issue(item, QC_CODES)
        if ni:
            issues.append(ni)

    return {
        "description": str(raw.get("description") or "").strip()[:500],
        "verdict": verdict,
        "scores": scores,
        "issues": issues,
        "recommendations": _norm_recs(raw.get("recommendations")),
    }


def empty_pre_edit(*, skipped: bool, reason: str | None = None) -> dict:
    return {
        "ok": False,
        "available": False,
        "skipped": skipped,
        "skip_reason": reason,
        "frames": [],
        "description": "",
        "content": "unknown",
        "orientation": "unknown",
        "usable": None,
        "scores": {
            "sharpness": None, "composition": None, "exposure": None,
            "obstruction_free": None, "overall": None, "confidence": 0.0,
        },
        "issues": [],
        "recommendations": [],
    }


def empty_qc(*, skipped: bool, reason: str | None = None) -> dict:
    return {
        "ok": False,
        "available": False,
        "skipped": skipped,
        "skip_reason": reason,
        "frames": [],
        "description": "",
        "verdict": "unknown",
        "scores": {
            "cut_smoothness": None, "silence_feel": None, "title_quality": None,
            "caption_clarity": None, "pacing": None, "professional_feel": None,
            "overall": None, "confidence": 0.0,
        },
        "issues": [],
        "recommendations": [],
    }


# ── public APIs ───────────────────────────────────────────────────────────────
def review_visual(
    path: str,
    *,
    enabled: bool | str | None = None,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    samples: int = DEFAULT_SAMPLES,
    workdir: str | Path | None = None,
    duration: float | None = None,
    log: LogFn | None = None,
) -> dict:
    """Pre-edit visual review of one clip. Auto-starts Ollama when hardwired on."""
    _log = log or (lambda _m: None)
    run, reason = should_run_vision(
        enabled, base_url=base_url, model=model, log=_log)
    if not run:
        out = empty_pre_edit(skipped=True, reason=reason)
        out["required_failed"] = resolve_enabled(enabled) == "on"
        return out

    try:
        frames = sample_frames(
            path, n=samples, workdir=workdir, duration=duration)
        if not frames:
            out = empty_pre_edit(skipped=True, reason="no frames extracted")
            out["available"] = True
            return out

        # Use up to 3 frames; moondream handles multi-image best with few stills
        use = frames[: min(3, len(frames))]
        images = [_encode_image(f["path"]) for f in use]
        times = ", ".join(f"{f['t']:.2f}" for f in use)
        prompt = (
            f"{_pre_edit_prompt()}\n\n"
            f"Clip: {Path(path).name}. Sample times (sec): {times}."
        )
        text = _generate(
            prompt, images,
            model=model, base_url=base_url, timeout_sec=timeout_sec,
        )
        if not text:
            out = empty_pre_edit(skipped=True, reason="ollama generate failed")
            out["available"] = True
            out["frames"] = [{"t": f["t"], "path": f["path"]} for f in use]
            return out

        parsed = repair_json(text)
        norm = normalize_pre_edit(parsed)
        result = {
            "ok": True,
            "available": True,
            "skipped": False,
            "skip_reason": None,
            "frames": [{"t": f["t"], "path": f["path"]} for f in use],
            **norm,
            "raw_text": text[:2000] if parsed is None else None,
        }
        if parsed is None:
            # Keep a prose fallback description so callers still get something
            result["ok"] = False
            result["description"] = text.strip()[:500]
            result["skip_reason"] = "json parse failed"
            _log(f"  vision: JSON parse failed for {Path(path).name}")
        return result
    except Exception as e:                             # noqa: BLE001
        _log(f"  vision: error on {Path(path).name}: {e}")
        return empty_pre_edit(skipped=True, reason=f"vision error: {e}")


def review_session_visual(
    paths: list[str],
    *,
    log: LogFn | None = None,
    **kwargs: Any,
) -> dict:
    """Run :func:`review_visual` across many clips."""
    _log = log or print
    clips = []
    for p in paths:
        _log(f"  vision-review {Path(p).name}…")
        clips.append(review_visual(p, log=_log, **kwargs))
    ok_n = sum(1 for c in clips if c.get("ok"))
    flagged = sum(1 for c in clips if c.get("issues"))
    return {
        "clips": clips,
        "total": len(clips),
        "ok": ok_n,
        "flagged": flagged,
        "skipped": sum(1 for c in clips if c.get("skipped")),
    }


def qc_edit(
    path: str,
    *,
    enabled: bool | str | None = None,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    samples: int = DEFAULT_QC_SAMPLES,
    workdir: str | Path | None = None,
    duration: float | None = None,
    log: LogFn | None = None,
) -> dict:
    """Post-edit QC of a finished episode (or intermediate render)."""
    _log = log or (lambda _m: None)
    run, reason = should_run_vision(
        enabled, base_url=base_url, model=model, log=_log)
    if not run:
        out = empty_qc(skipped=True, reason=reason)
        out["required_failed"] = resolve_enabled(enabled) == "on"
        return out

    try:
        frames = sample_frames(
            path, n=samples, workdir=workdir, duration=duration)
        if not frames:
            out = empty_qc(skipped=True, reason="no frames extracted")
            out["available"] = True
            return out

        use = frames[: min(5, len(frames))]
        images = [_encode_image(f["path"]) for f in use]
        times = ", ".join(f"{f['t']:.2f}" for f in use)
        prompt = (
            f"{_qc_prompt()}\n\n"
            f"Finished edit: {Path(path).name}. Sample times (sec): {times}."
        )
        text = _generate(
            prompt, images,
            model=model, base_url=base_url, timeout_sec=timeout_sec,
        )
        if not text:
            out = empty_qc(skipped=True, reason="ollama generate failed")
            out["available"] = True
            out["frames"] = [{"t": f["t"], "path": f["path"]} for f in use]
            return out

        parsed = repair_json(text)
        norm = normalize_qc(parsed)
        result = {
            "ok": True,
            "available": True,
            "skipped": False,
            "skip_reason": None,
            "frames": [{"t": f["t"], "path": f["path"]} for f in use],
            **norm,
            "raw_text": text[:2000] if parsed is None else None,
        }
        if parsed is None:
            result["ok"] = False
            result["description"] = text.strip()[:500]
            result["skip_reason"] = "json parse failed"
            _log(f"  qc: JSON parse failed for {Path(path).name}")
        return result
    except Exception as e:                             # noqa: BLE001
        _log(f"  qc: error on {Path(path).name}: {e}")
        return empty_qc(skipped=True, reason=f"vision error: {e}")


# ── merge helpers (for review.py) ─────────────────────────────────────────────
def merge_vision_into_review(clip: dict, vision: dict) -> dict:
    """Additively attach vision findings onto a deterministic ``analyze()`` dict.

    Never removes existing keys. May append recommendations / flags. May nudge
    ``content`` only when deterministic content is a weak default and vision is
    confident. Never changes ``orientation`` from YuNet/metadata — only adds a
    confirming note when vision also suspects upside-down.
    """
    if not vision or vision.get("skipped"):
        if vision:
            clip.setdefault("vision", vision)
        return clip

    clip["vision"] = vision

    # Append editorial recommendations (dedupe)
    existing = list(clip.get("recommendations") or [])
    seen = {r.lower() for r in existing}
    for rec in vision.get("recommendations") or []:
        if rec.lower() not in seen:
            existing.append(rec)
            seen.add(rec.lower())
    for issue in vision.get("issues") or []:
        detail = issue.get("detail") or issue.get("code")
        if not detail:
            continue
        line = f"Vision: {detail}"
        if line.lower() not in seen:
            existing.append(line)
            seen.add(line.lower())
    clip["recommendations"] = existing

    flags = list(clip.get("flags") or [])
    for issue in vision.get("issues") or []:
        code = issue.get("code")
        conf = float(issue.get("confidence") or 0)
        if code and conf >= 0.55 and code not in ("talking_head", "broll", "unknown"):
            label = code.replace("_", " ")
            if label not in flags:
                flags.append(label)
    clip["flags"] = flags

    # Soft content nudge: only if deterministic said talking/broll from audio heuristic
    v_content = vision.get("content")
    v_conf = float((vision.get("scores") or {}).get("confidence") or 0)
    if v_conf >= 0.6 and v_content in ("talking_head", "broll", "unusable"):
        mapped = {
            "talking_head": "talking",
            "broll": "broll",
            "unusable": "unusable",
        }[v_content]
        # Don't override a hard unusable from blackdetect; do allow talking↔broll
        if clip.get("content") != "unusable":
            if mapped == "unusable" and v_conf >= 0.75:
                clip["content"] = "unusable"
                clip["usable"] = False
            elif mapped in ("talking", "broll"):
                clip["content"] = mapped

    # Orientation confirm only — never override deterministic rotation
    if (
        vision.get("orientation") == "upside_down"
        and v_conf >= 0.6
        and (clip.get("orientation") or 0) == 0
        and "no face to confirm" in str(clip.get("orientation_note") or "").lower()
    ):
        note = "Vision also suspects upside-down — confirm rotate 180°."
        if note not in clip["recommendations"]:
            clip["recommendations"].append(note)
        if "vision upside-down?" not in flags:
            clip["flags"].append("vision upside-down?")

    return clip


def settings_from_config(cfg: Any | None) -> dict:
    """Pull vision kwargs from a Config-like object (missing attrs → defaults)."""
    model = os.environ.get("AUTOEDIT_VISION_MODEL") or DEFAULT_MODEL
    base_url = os.environ.get("AUTOEDIT_VISION_URL") or DEFAULT_BASE_URL
    timeout = DEFAULT_TIMEOUT_SEC
    samples = DEFAULT_SAMPLES
    workdir = None
    enabled = resolve_enabled(None)
    if cfg is not None:
        enabled = resolve_enabled(getattr(cfg, "vision_enabled", None))
        model = (
            os.environ.get("AUTOEDIT_VISION_MODEL")
            or getattr(cfg, "vision_model", None)
            or DEFAULT_MODEL
        )
        base_url = (
            os.environ.get("AUTOEDIT_VISION_URL")
            or getattr(cfg, "vision_base_url", None)
            or DEFAULT_BASE_URL
        )
        timeout = float(
            getattr(cfg, "vision_timeout_sec", DEFAULT_TIMEOUT_SEC)
            or DEFAULT_TIMEOUT_SEC
        )
        samples = int(getattr(cfg, "vision_samples", DEFAULT_SAMPLES) or DEFAULT_SAMPLES)
        workdir = getattr(cfg, "vision_workdir", None)
    return {
        "enabled": enabled,
        "model": model,
        "base_url": base_url,
        "timeout_sec": timeout,
        "samples": samples,
        "workdir": workdir,
    }
