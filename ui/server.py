"""Local AUTOEDITING FORGE web app — no terminal, no YAML.

Runs entirely on this Mac (127.0.0.1). Serves the UI, scans folders for footage,
launches edit.py per job, streams progress, and serves the finished video +
shorts back for preview.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml
from flask import Flask, abort, jsonify, request, send_file, session

ROOT = Path(__file__).resolve().parent.parent          # auto-edit-forge/
UI_DIR = Path(__file__).resolve().parent

_venv_py = ROOT / ".venv" / "bin" / "python"
PY = str(_venv_py) if _venv_py.exists() else sys.executable

RESOLVE_ENV = {
    "RESOLVE_SCRIPT_API": "/Library/Application Support/Blackmagic Design/"
                          "DaVinci Resolve/Developer/Scripting",
    "RESOLVE_SCRIPT_LIB": "/Applications/DaVinci Resolve/DaVinci Resolve.app/"
                          "Contents/Libraries/Fusion/fusionscript.so",
}

VIDEO_EXT = {".mov", ".mp4", ".braw", ".mxf", ".m4v", ".avi", ".mts"}
AUDIO_EXT = {".wav", ".aif", ".aiff", ".m4a", ".mp3", ".flac"}

JOBS: dict[str, dict] = {}
REVIEWS: dict[str, dict] = {}
STATE_LOCK = threading.RLock()
app = Flask(__name__, static_folder=str(UI_DIR), static_url_path="")

# Authentication is deliberately opt-in for the loopback-only local app. When
# enabled, Flask signs (but does not encrypt) the small session cookie.
_AUTH_PASSWORD = os.environ.get("AUTOEDITING_FORGE_PASSWORD", "")
AUTH_ENABLED = bool(_AUTH_PASSWORD)
app.config.update(
    SECRET_KEY=(os.environ.get("AUTOEDITING_FORGE_SECRET_KEY")
                or secrets.token_hex(32)),
    SESSION_COOKIE_NAME="autoediting_forge_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Strict",
    # localhost is HTTP by default. Deployments terminating HTTPS can opt in.
    SESSION_COOKIE_SECURE=os.environ.get(
        "AUTOEDITING_FORGE_SECURE_COOKIE", "").lower() in {"1", "true", "yes"},
    PERMANENT_SESSION_LIFETIME=12 * 60 * 60,
    SESSION_REFRESH_EACH_REQUEST=False,
)

_PUBLIC_API_ENDPOINTS = {"session_status", "login", "logout"}
_SECRET_FIELD_RE = re.compile(
    r"(?i)\b(password|secret|token|api[_-]?key|authorization)"
    r"(\s*[:=]\s*)([^\s,;]+)"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_message(value, limit: int = 1000) -> str:
    """Bound and redact process/user text before returning it through an API."""
    text = str(value).replace("\x00", "")
    if _AUTH_PASSWORD:
        text = text.replace(_AUTH_PASSWORD, "[REDACTED]")
    text = _BEARER_RE.sub("Bearer [REDACTED]", text)
    text = _SECRET_FIELD_RE.sub(r"\1\2[REDACTED]", text)
    return text if len(text) <= limit else text[:limit] + "…"


def _safe_json(value):
    """Recursively redact strings while preserving existing response shapes."""
    if isinstance(value, dict):
        return {str(k): _safe_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe_json(v) for v in value]
    if isinstance(value, tuple):
        return [_safe_json(v) for v in value]
    if isinstance(value, str):
        return _safe_message(value, 4000)
    return value


@app.before_request
def require_api_authentication():
    if (not AUTH_ENABLED or not request.path.startswith("/api/")
            or request.endpoint in _PUBLIC_API_ENDPOINTS):
        return None
    if session.get("authenticated") is True:
        return None
    return jsonify(error="authentication required", authenticated=False), 401


@app.after_request
def secure_api_responses(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    if request.path.startswith("/api/") and response.mimetype == "application/json":
        response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/api/session")
def session_status():
    studio_forge = os.environ.get("STUDIO_FORGE", "").strip() in {"1", "true", "yes"}
    return jsonify(
        authentication_required=AUTH_ENABLED,
        authenticated=(not AUTH_ENABLED or session.get("authenticated") is True),
        brand=("Studio Forge" if studio_forge else "AUTOEDITING FORGE"),
        brand_tagline=("Desktop editing control" if studio_forge else "The automated editor"),
        product=("studio_forge" if studio_forge else "autoediting_forge"),
    )


@app.route("/api/login", methods=["POST"])
def login():
    if not AUTH_ENABLED:
        return jsonify(authentication_required=False, authenticated=True)
    data = request.get_json(silent=True) or {}
    candidate = data.get("password", "")
    if not isinstance(candidate, str):
        candidate = ""
    expected_digest = hashlib.sha256(_AUTH_PASSWORD.encode()).digest()
    candidate_digest = hashlib.sha256(candidate.encode()).digest()
    if not hmac.compare_digest(candidate_digest, expected_digest):
        session.clear()
        return jsonify(error="invalid credentials", authenticated=False), 401
    session.clear()
    session["authenticated"] = True
    session.permanent = True
    return jsonify(authentication_required=True, authenticated=True)


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify(authentication_required=AUTH_ENABLED,
                   authenticated=not AUTH_ENABLED)

# ── background ingest ─────────────────────────────────────────────────────────
# Permanent storage = Studio Files NAS. Mac SSD is fast staging only.
# ZowieBox is monitor-only — leave "sources" empty. Optional SSD side door
# via ingest.json watch_braw_volumes (off by default).
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from autoedit import ingest as ingest_mod          # noqa: E402


def _resolve_jobs_dir() -> Path:
    """Job renders / thumbs live on Studio Files (Mac SSD is nearly full)."""
    if ingest_mod.studio_files_available():
        d = ingest_mod.DEFAULT_JOBS
        d.mkdir(parents=True, exist_ok=True)
        return d
    # Boot fallback only — do not park BRAW / finished masters here.
    d = UI_DIR / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


JOBS_DIR = _resolve_jobs_dir()
THUMBS_DIR = JOBS_DIR / "_thumbs"
THUMBS_DIR.mkdir(parents=True, exist_ok=True)

INGEST_CFG = UI_DIR / "ingest.json"
INGEST_LOG: list[str] = []


def _ingest_config() -> dict:
    if INGEST_CFG.exists():
        try:
            return json.loads(INGEST_CFG.read_text()) or {}
        except json.JSONDecodeError:
            pass
    return {}


def _ingest_sources() -> list[Path]:
    return [Path(s) for s in _ingest_config().get("sources", [])]


def _camera_forge_dirs() -> list[Path]:
    cfg = _ingest_config().get("camera_forge") or {}
    if cfg.get("enabled") is False:
        return []
    dirs = cfg.get("watch_dirs") or [
        str(ingest_mod.DEFAULT_INBOX),
        str(ingest_mod.LOCAL_STAGING),
        str(ingest_mod.DEFAULT_CAMERA_FORGE_DROP),
    ]
    return [ingest_mod.expand_path(s) for s in dirs]


def _staging_dirs() -> list[Path]:
    cfg = _ingest_config().get("camera_forge") or {}
    dirs = cfg.get("staging_dirs") or [
        str(ingest_mod.LOCAL_STAGING),
        str(ingest_mod.LEGACY_INBOX_RENAME),
        str(ingest_mod.LEGACY_INBOX),
        str(ingest_mod.DEFAULT_CAMERA_FORGE_DROP),
    ]
    return [ingest_mod.expand_path(s) for s in dirs]


def _ingest_loop():
    baseline = {v.name for v in ingest_mod.mounted_volumes()}

    def log(msg):  # keep a short in-memory tail for the UI
        INGEST_LOG.append(msg)
        del INGEST_LOG[:-80]

    if ingest_mod.studio_files_available():
        ingest_mod.DEFAULT_INBOX.mkdir(parents=True, exist_ok=True)
        ingest_mod.LOCAL_STAGING.mkdir(parents=True, exist_ok=True)
        log(f"Ingest: permanent storage → {ingest_mod.DEFAULT_INBOX}")
        log(f"Ingest: Mac staging (fast pull) → {ingest_mod.LOCAL_STAGING}")
    else:
        log("Ingest: Studio Files NAS OFFLINE — refusing Mac permanent storage")
    log("ZowieBox is monitor-only (not a footage source)")

    while True:
        try:
            cfg = _ingest_config()
            watch_vols = bool(cfg.get("watch_braw_volumes"))
            new_vols = []
            if watch_vols:
                new_vols = [v for v in ingest_mod.mounted_volumes()
                            if v.name not in baseline]
            ingest_mod.ingest_pass(
                _ingest_sources(),
                inbox=ingest_mod.DEFAULT_INBOX,
                camera_forge_dirs=_camera_forge_dirs(),
                staging_dirs=_staging_dirs(),
                watch_braw_volumes=watch_vols,
                braw_volumes=new_vols if watch_vols else None,
                log=log,
            )
        except Exception as e:                      # noqa: BLE001
            INGEST_LOG.append(f"ingest error: {e}")
        time.sleep(30)


threading.Thread(target=_ingest_loop, daemon=True).start()


@app.route("/api/inbox")
def inbox():
    sessions = ingest_mod.list_sessions(limit=40)
    return jsonify(
        sessions=_safe_json(sessions[:20]),
        log=_safe_json(INGEST_LOG[-10:]),
        inbox=str(ingest_mod.DEFAULT_INBOX),
        staging=str(ingest_mod.LOCAL_STAGING),
        studio_files=ingest_mod.studio_files_available(),
        jobs=str(JOBS_DIR),
    )


# ── pages ─────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return app.send_static_file("index.html")


# ── dashboard / operational health ────────────────────────────────────────────
_HEALTH_CACHE: dict = {"checked_at": 0.0, "value": None}


def _tool_version(command: str) -> dict:
    executable = shutil.which(command)
    if not executable:
        return {"available": False, "status": "unavailable", "version": None}
    version = None
    try:
        result = subprocess.run([executable, "-version"], capture_output=True,
                                text=True, timeout=2)
        first_line = (result.stdout or result.stderr).splitlines()
        if first_line:
            version = _safe_message(first_line[0], 180)
    except (OSError, subprocess.SubprocessError):
        pass
    return {"available": True, "status": "healthy", "version": version}


def _resolve_health() -> dict:
    app_path = Path("/Applications/DaVinci Resolve/DaVinci Resolve.app")
    installed = app_path.exists()
    running = False
    if installed:
        try:
            check = subprocess.run(
                ["pgrep", "-f", "/DaVinci Resolve.app/Contents/MacOS/Resolve"],
                capture_output=True, timeout=1)
            running = check.returncode == 0
        except (OSError, subprocess.SubprocessError):
            pass
    return {
        "installed": installed,
        "running": running,
        "available": installed and running,
        "status": "healthy" if running else ("stopped" if installed else "unavailable"),
        "optional": True,
    }


def _ollama_health() -> dict:
    """Ollama is a hardwired dependency — auto-start + report as critical if down."""
    try:
        from autoedit import vision as vision_mod
        status = vision_mod.ensure_ollama(pull=True, log=lambda m: None)
        ok = bool(status.get("ok"))
        return {
            "available": ok,
            "status": "healthy" if ok else "critical",
            "optional": False,
            "model": status.get("model"),
            "model_ready": bool(status.get("model_ready")),
            "detail": status.get("detail"),
            "bin": status.get("bin"),
        }
    except Exception as e:                                 # noqa: BLE001
        return {
            "available": False,
            "status": "critical",
            "optional": False,
            "detail": str(e),
        }


def _product_name() -> str:
    if os.environ.get("STUDIO_FORGE", "").strip().lower() in {"1", "true", "yes"}:
        return "Studio Forge"
    return "AUTOEDITING FORGE"


def _boot_vision_engine() -> None:
    """Start Ollama + vision model in the background so the UI can bind immediately."""
    from autoedit import vision as vision_mod
    name = _product_name()

    def run() -> None:
        print(f"{name} — ensuring Ollama vision engine…", flush=True)
        try:
            status = vision_mod.ensure_ollama(pull=True, log=print)
            if status.get("ok"):
                print(f"  ✓ Ollama ready ({status.get('model')})", flush=True)
            else:
                print(f"  ✗ Ollama NOT ready: {status.get('detail')}", flush=True)
                print("    Install from https://ollama.com — vision review will keep retrying.",
                      flush=True)
        except Exception as e:                             # noqa: BLE001
            print(f"  ✗ Ollama boot error: {e}", flush=True)

    threading.Thread(target=run, name="ollama-boot", daemon=True).start()


def _vision_watchdog(interval_sec: float = 60.0) -> None:
    """Background thread: if Ollama dies, bring it back."""
    from autoedit import vision as vision_mod

    def loop() -> None:
        while True:
            time.sleep(interval_sec)
            try:
                vision_mod.ensure_ollama(pull=True, log=lambda _m: None)
            except Exception:                              # noqa: BLE001
                pass

    t = threading.Thread(target=loop, name="ollama-watchdog", daemon=True)
    t.start()


def _system_health() -> dict:
    """Cheap health probes, cached because the dashboard may poll frequently."""
    now = time.monotonic()
    with STATE_LOCK:
        if (_HEALTH_CACHE["value"] is not None
                and now - _HEALTH_CACHE["checked_at"] < 15):
            return _HEALTH_CACHE["value"]

    ffmpeg = _tool_version("ffmpeg")
    nas_ok = ingest_mod.studio_files_available()
    disk_root = ingest_mod.STUDIO_FILES if nas_ok else Path.home()
    disk = shutil.disk_usage(disk_root)
    free_percent = round((disk.free / disk.total) * 100, 1) if disk.total else 0
    disk_status = "healthy"
    if not nas_ok:
        disk_status = "critical"
    elif disk.free < 5 * 1024 ** 3 or free_percent < 5:
        disk_status = "critical"
    elif disk.free < 20 * 1024 ** 3 or free_percent < 15:
        disk_status = "warning"
    mac = shutil.disk_usage(Path.home())
    mac_free_pct = round((mac.free / mac.total) * 100, 1) if mac.total else 0
    ollama = _ollama_health()
    health = {
        "status": ("critical" if (not ffmpeg["available"] or disk_status == "critical"
                                  or not ollama["available"])
                   else "degraded" if disk_status == "warning" else "healthy"),
        "ffmpeg": ffmpeg,
        "ollama": ollama,
        "python": {
            "available": True,
            "status": "healthy",
            "version": ".".join(str(n) for n in sys.version_info[:3]),
        },
        "resolve": _resolve_health(),
        "studio_files": {
            "available": nas_ok,
            "status": "healthy" if nas_ok else "critical",
            "path": str(ingest_mod.STUDIO_FILES),
            "inbox": str(ingest_mod.DEFAULT_INBOX),
            "jobs": str(JOBS_DIR),
            "staging": str(ingest_mod.LOCAL_STAGING),
        },
        "disk": {
            "status": disk_status,
            "path": str(disk_root),
            "free_bytes": disk.free,
            "total_bytes": disk.total,
            "free_percent": free_percent,
            "mac_free_bytes": mac.free,
            "mac_free_percent": mac_free_pct,
        },
        "checked_at": _utcnow(),
    }
    with STATE_LOCK:
        _HEALTH_CACHE.update(checked_at=now, value=health)
    return health


def _progress(state: str, stage_line: str) -> dict:
    if state == "done":
        return {"current": 1, "total": 1, "percent": 100}
    match = re.match(r"\s*\[(\d+)\s*/\s*(\d+)\]", stage_line or "")
    if not match:
        return {"current": 0, "total": 0, "percent": 0}
    current, total = int(match.group(1)), int(match.group(2))
    percent = round(min(current, total) / total * 100) if total else 0
    return {"current": current, "total": total, "percent": percent}


def _job_summary(job_id: str, job: dict) -> dict:
    return {
        "id": job_id,
        "title": _safe_message(job.get("title", "Episode"), 160),
        "state": job.get("state", "unknown"),
        "stage_line": _safe_message(job.get("stage_line", ""), 240),
        "progress": _progress(job.get("state", ""),
                              job.get("stage_line", "")),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "completed_at": job.get("completed_at"),
    }


def _review_summary(review_id: str, review: dict) -> dict:
    total = int(review.get("total", 0) or 0)
    reviewed = int(review.get("reviewed", 0) or 0)
    return {
        "id": review_id,
        "state": review.get("state", "unknown"),
        "current": _safe_message(review.get("current", ""), 200),
        "reviewed": reviewed,
        "total": total,
        "progress": round(min(reviewed, total) / total * 100) if total else 0,
        "created_at": review.get("created_at"),
        "updated_at": review.get("updated_at"),
        "completed_at": review.get("completed_at"),
    }


def _recent_issues(jobs: list[tuple[str, dict]],
                   reviews: list[tuple[str, dict]]) -> list[dict]:
    issues = []
    issue_pattern = re.compile(r"\b(error|exception|failed|warning)\b", re.I)
    for job_id, job in jobs:
        matches = [line for line in job.get("log", []) if issue_pattern.search(line)]
        if job.get("state") == "error" and not matches:
            matches = ["Job exited with an error."]
        for line in matches[-3:]:
            issues.append({
                "source": "job", "id": job_id,
                "severity": "error" if job.get("state") == "error" else "warning",
                "message": _safe_message(line, 500),
                "timestamp": job.get("updated_at") or job.get("created_at"),
            })
    for review_id, review in reviews:
        if review.get("state") == "error" or review.get("error"):
            issues.append({
                "source": "review", "id": review_id, "severity": "error",
                "message": _safe_message(review.get("error") or "Review failed.", 500),
                "timestamp": review.get("updated_at") or review.get("created_at"),
            })
    for line in INGEST_LOG[-20:]:
        if issue_pattern.search(line):
            issues.append({
                "source": "ingest", "id": None,
                "severity": "error" if "error" in line.lower() else "warning",
                "message": _safe_message(line, 500), "timestamp": None,
            })
    issues.sort(key=lambda issue: issue.get("timestamp") or "", reverse=True)
    return issues[:20]


@app.route("/api/dashboard")
def dashboard():
    with STATE_LOCK:
        jobs = list(JOBS.items())
        reviews = list(REVIEWS.items())
    jobs.sort(key=lambda item: item[1].get("created_at") or "", reverse=True)
    reviews.sort(key=lambda item: item[1].get("created_at") or "", reverse=True)
    job_summaries = [_job_summary(*item) for item in jobs]
    review_summaries = [_review_summary(*item) for item in reviews]
    return jsonify(
        timestamp=_utcnow(),
        health=_system_health(),
        jobs={
            "active": [j for j in job_summaries if j["state"] == "running"],
            "recent": job_summaries[:25],
            "counts": {
                "running": sum(j["state"] == "running" for j in job_summaries),
                "done": sum(j["state"] == "done" for j in job_summaries),
                "error": sum(j["state"] == "error" for j in job_summaries),
            },
        },
        reviews={
            "active": [r for r in review_summaries if r["state"] == "running"],
            "recent": review_summaries[:25],
        },
        issues=_recent_issues(jobs[:25], reviews[:25]),
    )


# ── footage browsing ──────────────────────────────────────────────────────────
@app.route("/api/home")
def home():
    """Sensible starting places to browse for footage."""
    roots = []
    for p in [ingest_mod.DEFAULT_INBOX, Path("/Volumes/Studio Files"),
              Path.home() / "Desktop", Path.home() / "Movies", Path("/Volumes")]:
        if p.exists():
            roots.append({"name": p.name or str(p), "path": str(p)})
    return jsonify(roots=roots)


@app.route("/api/scan")
def scan():
    d = request.args.get("dir", "")
    p = Path(d).expanduser()
    if not p.is_dir():
        return jsonify(error="That folder can't be opened."), 400
    dirs, videos, audios = [], [], []
    try:
        for c in sorted(p.iterdir(), key=lambda x: x.name.lower()):
            if c.name.startswith("."):
                continue
            if c.is_dir():
                dirs.append({"name": c.name, "path": str(c)})
            elif c.suffix.lower() in VIDEO_EXT:
                videos.append({"name": c.name, "path": str(c)})
            elif c.suffix.lower() in AUDIO_EXT:
                audios.append({"name": c.name, "path": str(c)})
    except PermissionError:
        return jsonify(error="No permission to read that folder."), 400
    return jsonify(dir=str(p), parent=str(p.parent),
                   dirs=dirs, videos=videos, audios=audios)


# ── running an edit ───────────────────────────────────────────────────────────
def _build_yaml(cfg: dict, out_dir: Path) -> dict:
    # Golden rule: editorial only — never grade, reframe, or run the AI operator.
    if cfg.get("mode") == "operator" or cfg.get("grade") or cfg.get("face"):
        raise ValueError(
            "AUTOEDITING FORGE keeps look and framing as shot — "
            "color grade, face-track, and operator mode are disabled.")
    straight = cfg.get("mode") == "edit"     # shot-ready footage: keep framing, just edit
    # Podcast / multicam default: cut to whoever is talking using each
    # camera's embedded audio (no separate mic files required).
    vfa = bool(cfg.get("video_follows_audio", True))

    wide_name = cfg.get("wide") or None
    angles = []
    for a in cfg.get("angles", []):
        entry = {"name": a["name"], "video": a["video"]}
        mic = a.get("mic")
        is_wide = wide_name and a["name"] == wide_name
        if not mic and (straight or (vfa and not is_wide)):
            mic = a["video"]        # listen to the footage's own audio
        if mic:
            entry["mic"] = mic
        rot = int(a.get("rotate") or 0)
        if rot in (0, 180):
            entry["rotate"] = rot
        angles.append(entry)

    # Smooth podcast switching when VFA is on; keep snappier defaults otherwise.
    min_shot = float(cfg.get("min_shot_sec", 2.5 if vfa else 1.5))
    switch = {
        "video_follows_audio": vfa,
        "overlap_to_wide": bool(cfg.get("overlap_to_wide", True)),
        "fallback": cfg.get("fallback", "wide"),
        "min_shot_sec": min_shot,
        "activation_db": float(cfg.get("activation_db", -35.0)),
        "relative_activation_db": cfg.get("relative_activation_db", 8.0),
        "switch_margin_db": float(cfg.get("switch_margin_db", 2.0 if vfa else 0.0)),
    }
    # Client-facing defaults: smooth dissolves, no jump cuts.
    smooth = bool(cfg.get("smooth_transitions", True))
    y: dict = {
        "angles": angles,
        "wide": wide_name,
        "switch": switch,
        "sync": {"enabled": bool(cfg.get("sync", True))},
        "silence": {"remove": bool(cfg.get("silence", False)),
                    "min_gap_sec": float(cfg.get("silence_gap", 1.5))},
        "refine": {
            "remove_fillers": bool(cfg.get("remove_fillers", True)),
            "remove_pauses": bool(cfg.get("remove_pauses", True)),
            "pause_sec": float(cfg.get("pause_sec", 0.6)),
        },
        "title": {
            "text": cfg.get("title", ""),
            "subtitle": cfg.get("subtitle", ""),
            "duration": float(cfg.get("title_duration", 4)),
        },
        "finish": {
            "transitions": True,
            "transition_sec": float(cfg.get("transition_sec", 0.6)),
            "speech_transition_sec": float(
                cfg.get("speech_transition_sec", 0.4 if smooth else 0.0)),
            "fade_sec": float(cfg.get("fade_sec", 0.75)),
            "audio_normalize": True,
        },
        "transcribe": {"enabled": bool(cfg.get("transcribe", True)),
                       "model": cfg.get("model", "base")},
        "shorts": {"enabled": bool(cfg.get("shorts", True)),
                   "count": int(cfg.get("shorts_count", 5))},
        "output": {
            "dir": "out",
            "backend": cfg.get("backend", "resolve"),
            "render": bool(cfg.get("render", True)),
            "grade": False,   # hard-off: camera LUT / god-eye owns the look
            "project_name": cfg.get("project_name", "AUTOEDITING FORGE"),
            "width": 1920, "height": 1080, "fps": 30,
        },
    }
    if cfg.get("intro"):
        y["intro"] = {"video": cfg["intro"]}
    if cfg.get("sponsor"):
        y["sponsor"] = {
            "video": cfg["sponsor"],
            "placement": cfg.get("sponsor_placement", "midroll"),
        }
    if cfg.get("outro"):
        y["outro"] = {"video": cfg["outro"]}
    else:
        y["outro"] = {"placeholder": bool(cfg.get("outro_placeholder", True))}
    return y


def _run_job(job: str, ypath: Path):
    env = {**os.environ, **RESOLVE_ENV}
    try:
        proc = subprocess.Popen(
            [PY, str(ROOT / "edit.py"), str(ypath)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env=env, cwd=str(ypath.parent), bufsize=1)
        for line in proc.stderr:
            line = _safe_message(line.rstrip(), 2000)
            with STATE_LOCK:
                JOBS[job]["log"].append(line)
                del JOBS[job]["log"][:-1000]
                if line.startswith("[") and "]" in line:  # "[3/6] Mixing…"
                    JOBS[job]["stage_line"] = line
                JOBS[job]["updated_at"] = _utcnow()
        proc.wait()
        out = proc.stdout.read()
        try:
            result = _safe_json(json.loads(out))
        except json.JSONDecodeError:
            # Keep the legacy "raw" result key, but never return unbounded
            # process output or credentials accidentally printed by a tool.
            result = {"raw": _safe_message(out, 4000)}
        with STATE_LOCK:
            JOBS[job]["result"] = result
            JOBS[job]["state"] = "done" if proc.returncode == 0 else "error"
            JOBS[job]["updated_at"] = _utcnow()
            JOBS[job]["completed_at"] = JOBS[job]["updated_at"]
    except Exception as e:                                 # noqa: BLE001
        with STATE_LOCK:
            JOBS[job]["log"].append(_safe_message(f"ERROR: {e}", 2000))
            JOBS[job]["state"] = "error"
            JOBS[job]["updated_at"] = _utcnow()
            JOBS[job]["completed_at"] = JOBS[job]["updated_at"]


@app.route("/api/run", methods=["POST"])
def run():
    cfg = request.get_json(force=True)
    if not cfg.get("angles"):
        return jsonify(error="Add at least one camera before building."), 400
    if cfg.get("mode") == "operator":
        return jsonify(error="Operator / reframe mode is disabled — "
                             "AUTOEDITING FORGE keeps framing as shot."), 400
    # Multicam: either separate mic files OR video-follows-audio (embedded).
    vfa = bool(cfg.get("video_follows_audio", True))
    if (cfg.get("mode") != "edit" and not vfa
            and not any(a.get("mic") for a in cfg["angles"])):
        return jsonify(error="Attach mic files, or turn on Video follows audio "
                             "(uses each camera's embedded sound)."), 400
    job = uuid.uuid4().hex[:8]
    out_dir = JOBS_DIR / job
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        yml = _build_yaml(cfg, out_dir)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    ypath = out_dir / "project.yaml"
    ypath.write_text(yaml.safe_dump(yml, sort_keys=False))
    now = _utcnow()
    with STATE_LOCK:
        JOBS[job] = {
            "state": "running", "log": [], "stage_line": "", "result": None,
            "out_dir": str(out_dir), "title": cfg.get("title", "Episode"),
            "created_at": now, "updated_at": now, "completed_at": None,
        }
    threading.Thread(target=_run_job, args=(job, ypath), daemon=True).start()
    return jsonify(job=job)


def _outputs(out_dir: Path) -> dict:
    o = out_dir / "out"
    episode = None
    for cand in sorted(o.glob("episode*.*")):
        if cand.suffix.lower() in {".mp4", ".mov", ".m4v"}:
            episode = str(cand)
            break
    shorts = [str(p) for p in sorted((o / "shorts").glob("*.mp4"))]
    gb = o / "grade_before.jpg"
    ga = o / "grade_after.jpg"
    return {"episode": episode, "shorts": shorts,
            "editlist": str(o / "editlist.json") if (o / "editlist.json").exists() else None,
            "grade_before": str(gb) if gb.exists() else None,
            "grade_after": str(ga) if ga.exists() else None,
            "srt": str(o / "episode.srt") if (o / "episode.srt").exists() else None}


_STAT_PATTERNS = [
    ("words", re.compile(r"transcript:\s*(\d+)\s*words")),
    ("caption_lines", re.compile(r"(\d+)\s*caption lines")),
    ("trim_spots", re.compile(r"trimmed\s*(\d+)\s*filler/pause")),
    ("seconds_cut", re.compile(r"\(([\d.]+)s removed\)")),
    ("shots", re.compile(r"(\d+)\s*operated shots")),
    ("cuts", re.compile(r"(\d+)\s*raw shots")),
    ("face_cov", re.compile(r"locked on subject \((\d+)% coverage\)")),
    ("grade_black", re.compile(r"blacks\s*([\d.]+)")),
    ("grade_white", re.compile(r"whites\s*([\d.]+)")),
]


def _stats(log: list[str]) -> dict:
    """Distil the run log into headline numbers the UI can celebrate."""
    text = "\n".join(log)
    out: dict = {}
    for key, pat in _STAT_PATTERNS:
        m = pat.search(text)
        if m:
            out[key] = float(m.group(1)) if "." in m.group(1) else int(m.group(1))
    out["graded"] = "grade_black" in out
    out["face_locked"] = "face_cov" in out
    if "no face found" in text:
        out["face_locked"] = False
    return out


@app.route("/api/job/<job>")
def job_status(job):
    with STATE_LOCK:
        j = JOBS.get(job)
    if not j:
        return jsonify(error="unknown job"), 404
    outs = _outputs(Path(j["out_dir"]))
    shotmap = []
    if outs.get("editlist"):
        try:
            shotmap = json.loads(Path(outs["editlist"]).read_text())
        except Exception:                              # noqa: BLE001
            shotmap = []
    return jsonify(state=j["state"], log=_safe_json(j["log"]),
                   stage_line=_safe_message(j["stage_line"]),
                   result=_safe_json(j["result"]), outputs=outs,
                   shotmap=_safe_json(shotmap), stats=_stats(j["log"]),
                   title=_safe_message(j["title"]),
                   created_at=j.get("created_at"), updated_at=j.get("updated_at"),
                   completed_at=j.get("completed_at"),
                   progress=_progress(j["state"], j["stage_line"]))


@app.route("/api/media")
def media():
    p = Path(request.args.get("path", "")).resolve()
    try:
        p.relative_to(JOBS_DIR.resolve())
    except ValueError:
        abort(403)
    # Serve only artifacts that the pipeline reports as outputs. This keeps
    # project.yaml, logs, and any unrelated file under ui/jobs inaccessible.
    allowed = set()
    with STATE_LOCK:
        output_dirs = [Path(j["out_dir"]) for j in JOBS.values()]
    for out_dir in output_dirs:
        outputs = _outputs(out_dir)
        for key in ("episode", "grade_before", "grade_after", "srt"):
            if outputs.get(key):
                allowed.add(Path(outputs[key]).resolve())
        allowed.update(Path(short).resolve() for short in outputs["shorts"])
    if p not in allowed or not p.is_file():
        abort(403)
    return send_file(str(p))


# ── footage review (the "watch before it edits" step) ─────────────────────────
# Deterministic per-clip analysis (orientation / loudness / content) via
# autoedit.review. It's heavy on 4K footage, so each request runs in a
# background thread and the UI polls GET /api/review/<id> — same pattern as jobs.
def _run_review(rid: str, paths: list[str]):
    from autoedit import review as review_mod

    def log(msg):
        s = _safe_message(msg, 2000)
        with STATE_LOCK:
            r = REVIEWS.get(rid)
            if not r:
                return
            r["log"].append(s)
            del r["log"][:-60]
            r["updated_at"] = _utcnow()
            m = re.search(r"reviewing\s+(.+?)(?:…|\.\.\.)", s)
            if m:
                if r["current"]:
                    r["reviewed"] += 1
                r["current"] = m.group(1).strip()

    try:
        # Ollama vision is additive (auto/on/off via AUTOEDIT_VISION / config);
        # deterministic LUFS/YuNet/blackdetect always runs. ollama=True lets
        # review.py attach vision when available.
        res = review_mod.review_session(paths, log=log, ollama=True)
        with STATE_LOCK:
            r = REVIEWS.get(rid, {})
            r.update(state="done",
                     clips=_safe_json(res.get("clips", [])),
                     usable=res.get("usable", 0),
                     total=res.get("total", len(paths)),
                     fixes=res.get("fixes", 0),
                     reviewed=res.get("total", len(paths)),
                     current="", updated_at=_utcnow())
            r["completed_at"] = r["updated_at"]
    except Exception as e:                                 # noqa: BLE001
        with STATE_LOCK:
            r = REVIEWS.get(rid, {})
            r["state"] = "error"
            r["error"] = _safe_message(e, 1000)
            r["log"].append(_safe_message(f"review error: {e}", 2000))
            r["updated_at"] = _utcnow()
            r["completed_at"] = r["updated_at"]


@app.route("/api/review", methods=["POST"])
def review_start():
    try:
        data = request.get_json(force=True) or {}
    except Exception:                                      # noqa: BLE001
        data = {}
    paths = data.get("paths")
    if not paths:
        paths = [a.get("video") for a in data.get("angles", []) if a.get("video")]
    paths = [p for p in (paths or []) if p]
    if not paths:
        return jsonify(error="No footage to review — pick a clip first."), 400
    rid = uuid.uuid4().hex[:8]
    now = _utcnow()
    with STATE_LOCK:
        REVIEWS[rid] = {
            "state": "running", "clips": [], "usable": 0,
            "total": len(paths), "fixes": 0, "current": "",
            "reviewed": 0, "log": [], "error": None,
            "created_at": now, "updated_at": now, "completed_at": None,
        }
    threading.Thread(target=_run_review, args=(rid, paths), daemon=True).start()
    return jsonify(review=rid, state="running", total=len(paths))


@app.route("/api/review/<rid>")
def review_status(rid):
    with STATE_LOCK:
        r = REVIEWS.get(rid)
    if not r:
        return jsonify(error="unknown review"), 404
    return jsonify(state=r["state"], clips=_safe_json(r["clips"]),
                   usable=r["usable"],
                   total=r["total"], fixes=r["fixes"], reviewed=r["reviewed"],
                   current=_safe_message(r["current"]),
                   log=_safe_json(r["log"][-12:]),
                   error=_safe_message(r["error"]) if r.get("error") else None,
                   created_at=r.get("created_at"), updated_at=r.get("updated_at"),
                   completed_at=r.get("completed_at"))


# ── Editorial learning brain ─────────────────────────────────────────────────
@app.route("/api/learning")
def learning_status():
    """Growing editor brain: priors, ratings, never-again rules, daily due."""
    try:
        from autoedit.learning.store import load_store, recompute_priors
        from autoedit.learning.ratings import rating_summary
        from autoedit.learning.daily import due_for_daily
        from autoedit.learning.dislikes import active_rules_for
        store = load_store()
        recompute_priors(store)
        return jsonify(
            stats=store.stats,
            priors=store.priors,
            category_priors=store.category_priors,
            ratings=rating_summary(store),
            never_again=active_rules_for("general"),
            daily_due_today=due_for_daily(store),
            rating_scale={"min": -1, "max": 20, "target": 18,
                          "help": "-1 = bad · 10 = okay · 20 = perfect"},
        )
    except Exception as e:  # noqa: BLE001
        return jsonify(error=str(e)), 500


@app.route("/api/learning/rate", methods=["POST"])
def learning_rate():
    """Rate a finished edit. Body: {path, score (-1..20), category?, notes?, job?}"""
    data = request.get_json(force=True, silent=True) or {}
    path = data.get("path") or ""
    if not path:
        return jsonify(error="path required"), 400
    try:
        score = float(data.get("score"))
    except (TypeError, ValueError):
        return jsonify(error="score must be a number from -1 to 20"), 400
    from autoedit.learning.ratings import rate_edit, rating_summary
    ev = rate_edit(
        path, score,
        category=str(data.get("category") or "general"),
        notes=str(data.get("notes") or ""),
        job_id=str(data.get("job") or ""),
        context={"via": "ui"},
    )
    return jsonify(ok=True, event=ev, summary=rating_summary())


@app.route("/api/learning/dislike", methods=["POST"])
def learning_dislike():
    """Never-again memory. Body: {text, situation?}"""
    data = request.get_json(force=True, silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify(error="text required"), 400
    from autoedit.learning.dislikes import remember_dislike, active_rules_for
    sit = str(data.get("situation") or "general")
    ev = remember_dislike(text, situation=sit, source="ui")
    return jsonify(ok=True, event=ev, rules=active_rules_for(sit))


@app.route("/api/learning/daily", methods=["POST"])
def learning_daily():
    """Kick off daily study of top podcasts / talking heads / long-form / shorts."""
    data = request.get_json(force=True, silent=True) or {}
    from autoedit.learning.daily import run_daily
    import threading

    def _run():
        try:
            run_daily(
                per_category=int(data.get("per_category") or 3),
                download_sample=bool(data.get("with_samples")),
                log=lambda m="": print(f"[learning] {m}", flush=True),
            )
        except Exception as e:  # noqa: BLE001
            print(f"[learning] daily failed: {e}", flush=True)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify(ok=True, started=True,
                   message="Daily learning started in background")


@app.route("/api/thumb")
def thumb():
    """A single representative frame for a review card. Optional, best-effort:
    any failure returns 404 and the UI just hides the image."""
    raw = request.args.get("path", "")
    rot = request.args.get("rot", "0")
    t = request.args.get("t", "1")
    p = Path(raw).expanduser()
    if not p.is_file() or p.suffix.lower() not in VIDEO_EXT:
        abort(404)
    try:
        seek = max(0.0, float(t))
    except ValueError:
        seek = 1.0
    key = hashlib.md5(f"{p}|{rot}|{seek:.1f}".encode()).hexdigest()[:16]
    out = THUMBS_DIR / f"{key}.jpg"
    if not out.exists():
        vf = "scale=560:-2"
        if rot == "180":
            vf += ",hflip,vflip"
        elif rot == "90":
            vf = "transpose=1," + vf
        elif rot == "270":
            vf = "transpose=2," + vf
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-ss", f"{seek:.2f}", "-i", str(p),
                 "-frames:v", "1", "-vf", vf, "-q:v", "4", str(out)],
                capture_output=True, timeout=30)
        except Exception:                                  # noqa: BLE001
            pass
    if not out.exists():
        abort(404)
    return send_file(str(out))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8765"))
    _boot_vision_engine()
    _vision_watchdog(60.0)
    print(f"{_product_name()} — UI on http://127.0.0.1:{port}", flush=True)
    app.run(host="127.0.0.1", port=port, threaded=True)
