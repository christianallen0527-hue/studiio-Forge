"""Study public YouTube videos for editorial lessons.

Uses yt-dlp when available to pull *public* metadata, auto-captions, and a
short low-res sample for pacing analysis. Nothing private is accessed.
This is observational learning (features → priors), not neural fine-tuning.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from pathlib import Path

from .features import extract_features
from .store import LearningStore, load_store, recompute_priors

SAMPLE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "learning" / "samples"


def _ytdlp() -> str | None:
    for cand in ("yt-dlp", shutil.which("yt-dlp"),
                 str(Path.home() / ".local/bin/yt-dlp")):
        if cand and Path(str(cand)).exists() if "/" in str(cand) else shutil.which(str(cand)):
            w = shutil.which("yt-dlp") if cand == "yt-dlp" else str(cand)
            if w:
                return w
    # try venv pip module
    return None


def ensure_ytdlp(log=print) -> str:
    """Return yt-dlp executable, installing into the active env if needed."""
    w = shutil.which("yt-dlp")
    if w:
        return w
    # Prefer module form if already installed
    mod = subprocess.run(
        [__import__("sys").executable, "-c", "import yt_dlp; print('ok')"],
        capture_output=True, text=True,
    )
    if mod.returncode == 0:
        return f"{__import__('sys').executable} -m yt_dlp"
    log("  installing yt-dlp (public YouTube study only)…")
    try:
        subprocess.run(
            [__import__("sys").executable, "-m", "pip", "install", "-q", "yt-dlp"],
            check=True, timeout=120,
        )
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
        raise RuntimeError(
            "yt-dlp is required for YouTube study. Install with: "
            "pip install yt-dlp"
        ) from e
    w = shutil.which("yt-dlp")
    if w:
        return w
    return f"{__import__('sys').executable} -m yt_dlp"


def study_youtube(
    url: str,
    *,
    labels: list[str] | None = None,
    notes: str = "",
    download_sample: bool = True,
    store: LearningStore | None = None,
    log=print,
) -> dict:
    """Study one public YouTube URL and fold lessons into the store."""
    store = store or load_store()
    ytdlp = ensure_ytdlp(log=log)
    labels = labels or ["reference"]

    log(f"  studying public video… {url}")
    meta = _fetch_metadata(ytdlp, url, log=log)
    title = meta.get("title") or ""
    channel = meta.get("channel") or meta.get("uploader") or ""
    features: dict = {
        "duration_sec": meta.get("duration"),
        "view_count": meta.get("view_count"),
        "average_rating": meta.get("average_rating"),
        "categories": meta.get("categories") or [],
        "tags": (meta.get("tags") or [])[:20],
        "description_head": (meta.get("description") or "")[:400],
        "chapter_count": len(meta.get("chapters") or []),
        "caption_langs": list((meta.get("subtitles") or {}).keys())[:8],
    }

    # Caption pacing hints (words / sec) from auto-subs when present
    caps = _fetch_captions_text(ytdlp, url, log=log)
    if caps:
        features["caption_words"] = len(caps.split())
        if meta.get("duration"):
            features["words_per_sec"] = round(
                features["caption_words"] / max(1.0, float(meta["duration"])), 3)

    sample_path = None
    if download_sample:
        sample_path = _download_sample(ytdlp, url, log=log)
        if sample_path and Path(sample_path).exists():
            local = extract_features(sample_path, log=log)
            features.update({k: v for k, v in local.items() if v is not None})
            features["sample_path"] = sample_path

    # Auto labels from features
    auto = list(labels)
    if features.get("median_shot_sec") and float(features["median_shot_sec"]) >= 2.2:
        auto.append("good_pacing")
    if features.get("shake_score") is not None and float(features["shake_score"]) > 14:
        auto.append("shaky_example")
    if features.get("dark_card_ratio") and float(features["dark_card_ratio"]) > 0.4:
        auto.append("static_cards")
    if features.get("loudness_lufs") and -20 <= float(features["loudness_lufs"]) <= -10:
        auto.append("clean_audio")

    labels_final = sorted(set(auto))
    store.references.append({
        "source": url,
        "title": title,
        "channel": channel,
        "studied_at": time.time(),
        "features": features,
        "labels": labels_final,
        "notes": notes,
    })
    recompute_priors(store)
    store.save()
    log(f"  learned from “{title or url}” · priors confidence={store.priors.get('confidence')}")
    return {"meta": {"title": title, "channel": channel}, "features": features,
            "labels": labels_final, "priors": store.priors}


def study_local(path: str | Path, *, labels: list[str] | None = None,
                notes: str = "", store: LearningStore | None = None, log=print) -> dict:
    """Study a local reference edit the same way."""
    store = store or load_store()
    path = str(path)
    features = extract_features(path, log=log)
    lesson = {
        "source": path,
        "title": Path(path).name,
        "channel": "local",
        "studied_at": time.time(),
        "features": features,
        "labels": labels or ["local_reference"],
        "notes": notes,
    }
    store.references.append(lesson)
    recompute_priors(store)
    store.save()
    return lesson


def _fetch_metadata(ytdlp: str, url: str, log=print) -> dict:
    cmd = _ytdlp_cmd(ytdlp) + ["--dump-single-json", "--skip-download", "--no-warnings", url]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "yt-dlp metadata failed")
    return json.loads(proc.stdout)


def _fetch_captions_text(ytdlp: str, url: str, log=print) -> str:
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    outtmpl = str(SAMPLE_DIR / "caps.%(ext)s")
    cmd = _ytdlp_cmd(ytdlp) + [
        "--skip-download", "--write-auto-sub", "--sub-lang", "en",
        "--sub-format", "vtt/srt/best", "--convert-subs", "srt",
        "-o", outtmpl, "--no-warnings", url,
    ]
    subprocess.run(cmd, capture_output=True, text=True)
    texts = []
    for p in SAMPLE_DIR.glob("caps*.srt"):
        raw = p.read_text(errors="ignore")
        # strip srt indexes/timestamps
        lines = [ln for ln in raw.splitlines()
                 if ln.strip() and not ln.strip().isdigit()
                 and "-->" not in ln]
        texts.append(" ".join(lines))
        p.unlink(missing_ok=True)
    for p in SAMPLE_DIR.glob("caps*.vtt"):
        p.unlink(missing_ok=True)
    return re.sub(r"\s+", " ", " ".join(texts)).strip()


def _download_sample(ytdlp: str, url: str, log=print) -> str | None:
    """Download ≤90s low-res sample for pacing / shake analysis."""
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    # sanitize id
    out = SAMPLE_DIR / "sample.mp4"
    cmd = _ytdlp_cmd(ytdlp) + [
        "-f", "worstvideo[height<=360]+worstaudio/worst[height<=360]/worst",
        "--download-sections", "*0:00-1:30",
        "--force-keyframes-at-cuts",
        "-o", str(out),
        "--no-playlist", "--no-warnings",
        "--merge-output-format", "mp4",
        url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if out.exists() and out.stat().st_size > 1000:
        return str(out)
    # fallback without sections
    cmd = _ytdlp_cmd(ytdlp) + [
        "-f", "worst[height<=360]/worst",
        "-o", str(out), "--no-playlist", "--no-warnings", url,
    ]
    subprocess.run(cmd, capture_output=True, text=True)
    return str(out) if out.exists() else None


def _ytdlp_cmd(ytdlp: str) -> list[str]:
    if " -m " in ytdlp:
        return ytdlp.split()
    return [ytdlp]
