"""Sponsor-spot QC — catch weak audio / shake / dated cards BEFORE showing.

Reads studio memory rules from ``context_docs/obsidian/``. Machine-actionable
fixes are returned so the editing engine can repair, re-QC, then deliver.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from . import ffmpeg

MEMORY_DIR = Path(__file__).resolve().parent.parent / "context_docs" / "obsidian"


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def _has_audio(path: str) -> bool:
    out = _run([
        "ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=codec_type", "-of", "csv=p=0", path,
    ]).stdout.strip()
    return bool(out)


def _loudness(path: str) -> tuple[float | None, float | None]:
    """Return (integrated LUFS, true peak dBFS) via ebur128."""
    proc = _run([
        "ffmpeg", "-v", "info", "-i", path, "-vn",
        "-filter_complex", "ebur128=peak=true", "-f", "null", "-",
    ])
    lufs = peak = None
    for line in (proc.stderr or "").splitlines():
        if "I:" in line and "LUFS" in line:
            try:
                lufs = float(line.split("I:")[1].split("LUFS")[0].strip())
            except (IndexError, ValueError):
                pass
        if "Peak:" in line and "dBFS" in line:
            try:
                peak = float(line.split("Peak:")[1].split("dBFS")[0].strip())
            except (IndexError, ValueError):
                pass
    return lufs, peak


def _audio_rms_envelope(path: str, window: float = 0.25) -> list[float]:
    """Per-window RMS (0..1-ish) for seam / click heuristics."""
    # astats per frame is heavy; use afade-free silencedetect inverse via astats reset
    dur = max(ffmpeg.probe_duration(path), 0.1)
    # Extract mono PCM and measure in Python
    raw = subprocess.run([
        "ffmpeg", "-v", "error", "-i", path, "-vn",
        "-ac", "1", "-ar", "8000", "-f", "s16le", "-",
    ], capture_output=True).stdout
    if not raw:
        return []
    import array
    samples = array.array("h")
    samples.frombytes(raw[: len(raw) - (len(raw) % 2)])
    if not samples:
        return []
    win = max(1, int(8000 * window))
    env: list[float] = []
    for i in range(0, len(samples) - win, win):
        chunk = samples[i:i + win]
        acc = sum(int(s) * int(s) for s in chunk) / len(chunk)
        env.append((acc ** 0.5) / 32768.0)
    return env


def _detect_music_seam(env: list[float], window: float = 0.25) -> dict | None:
    """Flag a hard drop+rise mid-spot (typical hard loop restart)."""
    if len(env) < 12:
        return None
    # Ignore first/last 1.5s (program fades)
    pad = max(1, int(1.5 / window))
    mid = env[pad:-pad] if len(env) > 2 * pad + 4 else env
    if not mid:
        return None
    mean = sum(mid) / len(mid)
    if mean < 1e-4:
        return {"code": "silence", "detail": "Music bed is effectively silent."}
    # Look for a valley < 25% of mean followed within 1s by recovery > 70% mean
    valley_idx = None
    for i, v in enumerate(mid[:-4]):
        if v < mean * 0.22:
            valley_idx = i
            # recovery window ~1s
            ahead = mid[i + 1:i + 1 + max(2, int(1.0 / window))]
            if ahead and max(ahead) > mean * 0.70:
                t = (pad + i) * window
                return {
                    "code": "music_seam",
                    "detail": (
                        f"Hard music restart around {t:.1f}s — "
                        "crossfade-loop the bed so it is seamless."
                    ),
                    "time_sec": round(t, 2),
                    "auto_fix": "reseam_music",
                }
    return None


def _detect_click_spam(env: list[float], window: float = 0.05) -> dict | None:
    """High density of sharp RMS spikes ≈ typing / UI clicks."""
    # Re-measure with finer window for this check only — caller may pass fine env
    if len(env) < 20:
        return None
    mean = sum(env) / len(env) or 1e-6
    spikes = sum(1 for v in env if v > mean * 4.5 and v > 0.02)
    density = spikes / (len(env) * window)  # spikes per second
    if density > 1.8:
        return {
            "code": "sfx_spam",
            "detail": (
                f"Clicky/transient SFX density high ({density:.1f}/s) — "
                "remove typing/UI clicks; keep original music only."
            ),
            "auto_fix": "strip_to_bed",
        }
    return None


def _shake_score(path: str, start_ratio: float = 0.55) -> float:
    """Rough shake score on the final portion via frame-diff energy (0..1+)."""
    dur = ffmpeg.probe_duration(path)
    ss = max(0.0, dur * start_ratio)
    # freezedetect / signalstats: use mae between consecutive frames
    proc = _run([
        "ffmpeg", "-v", "error", "-ss", f"{ss:.2f}", "-i", path,
        "-t", f"{max(1.0, dur - ss):.2f}",
        "-vf", "scale=320:-2,format=gray,tblend=all_mode=difference,signalstats",
        "-f", "null", "-",
    ])
    ys = []
    for line in (proc.stderr or "").splitlines():
        if "YAVG:" in line:
            try:
                # signalstats prints YAVG=...
                part = [p for p in line.replace(":", "=").split() if "YAVG=" in p]
                if part:
                    ys.append(float(part[0].split("=")[1]))
            except (IndexError, ValueError):
                pass
    if not ys:
        # fallback: sample a few mae via select
        return 0.0
    return sum(ys) / len(ys)


def _dated_card_ratio(path: str, samples: int = 8) -> float:
    """Fraction of sampled frames that look like a flat dark full-screen card."""
    dur = max(ffmpeg.probe_duration(path), 1.0)
    dark_flat = 0
    total = 0
    for i in range(1, samples + 1):
        t = dur * i / (samples + 1)
        raw = subprocess.run([
            "ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", path,
            "-frames:v", "1", "-vf", "scale=160:90,format=gray",
            "-f", "rawvideo", "-",
        ], capture_output=True).stdout
        if not raw:
            continue
        total += 1
        vals = list(raw)
        mean = sum(vals) / len(vals)
        # variance
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        # dark + low detail ≈ navy card
        if mean < 45 and var < 350:
            dark_flat += 1
    if total == 0:
        return 0.0
    return dark_flat / total


def analyze(path: str | Path, log=print) -> dict:
    """Full sponsor QC report with machine-actionable fixes."""
    path = str(path)
    issues: list[dict] = []
    recommendations: list[str] = []
    fixes: list[dict] = []

    if not Path(path).exists():
        return {
            "path": path, "verdict": "fail",
            "issues": [{"code": "missing", "detail": "Sponsor file not found."}],
            "recommendations": ["Rebuild the sponsor spot."],
            "fixes": [], "memory": str(MEMORY_DIR),
        }

    dur = ffmpeg.probe_duration(path)
    has_a = _has_audio(path)
    lufs, peak = _loudness(path) if has_a else (None, None)

    if not has_a or lufs is None or lufs < -45:
        issues.append({
            "code": "silence",
            "detail": "Sponsor has no usable music bed.",
            "auto_fix": "strip_to_bed",
        })
        recommendations.append(
            "Lay the original first-ad upbeat music under the spot (seamless loop)."
        )

    env = _audio_rms_envelope(path, window=0.25) if has_a else []
    seam = _detect_music_seam(env, window=0.25) if env else None
    if seam:
        issues.append(seam)
        recommendations.append(seam["detail"])
        if seam.get("auto_fix"):
            fixes.append({"action": seam["auto_fix"], "path": path})

    fine = _audio_rms_envelope(path, window=0.05) if has_a else []
    spam = _detect_click_spam(fine, window=0.05) if fine else None
    if spam:
        issues.append(spam)
        recommendations.append(spam["detail"])
        fixes.append({"action": "strip_to_bed", "path": path})

    shake = _shake_score(path, start_ratio=0.55)
    # Empirically: stable plates ~ few units; shaky handheld much higher
    if shake > 12.0:
        issues.append({
            "code": "shake",
            "detail": (
                f"Final third looks shaky (score {shake:.1f}) — "
                "stabilize or replace the last clips with locked plates."
            ),
            "auto_fix": "stabilize_tail",
            "score": round(shake, 2),
        })
        recommendations.append(
            "Deshake / re-cut the last two clips from steadier source; no handheld wobble."
        )
        fixes.append({"action": "stabilize_tail", "path": path})

    card_ratio = _dated_card_ratio(path)
    if card_ratio >= 0.35:
        issues.append({
            "code": "dated_card",
            "detail": (
                f"~{card_ratio*100:.0f}% of sampled frames look like a flat dark "
                "corporate card — rebuild mid/end as modern kinetic type over live house."
            ),
            "auto_fix": "rebuild_modern_graphics",
        })
        recommendations.append(
            "Remove 80s navy/gold full-screen cards; animate modern type over house footage."
        )
        fixes.append({"action": "rebuild_modern_graphics", "path": path})

    if dur < 18:
        recommendations.append("Sponsor is under ~20s — extend body holds if client asked for 20s+.")

    # severity
    critical = {i["code"] for i in issues} & {
        "silence", "music_seam", "shake", "dated_card", "sfx_spam", "missing",
    }
    verdict = "fail" if critical else ("warn" if issues or recommendations else "pass")

    report = {
        "path": path,
        "duration": round(dur, 3),
        "loudness_lufs": lufs,
        "peak_db": peak,
        "shake_score_tail": round(shake, 2),
        "dated_card_ratio": round(card_ratio, 3),
        "verdict": verdict,
        "issues": issues,
        "recommendations": recommendations,
        "fixes": fixes,
        "memory": str(MEMORY_DIR),
        "memory_notes": [
            "context_docs/obsidian/Wanted vs Not Okay.md",
            "context_docs/obsidian/Sponsor Ad — High Place Mortgage.md",
            "context_docs/obsidian/Review Before Show.md",
        ],
    }
    log(f"  sponsor QC: {verdict}"
        + (f" · {', '.join(i['code'] for i in issues)}" if issues else " · clean"))
    return report


def write_report(report: dict, out_path: str | Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2))
    return out_path


def apply_auto_fixes(path: str | Path, report: dict | None = None, log=print) -> str:
    """Apply safe auto-fixes (reseam music, stabilize tail). Returns new path."""
    path = Path(path)
    report = report or analyze(str(path), log=log)
    actions = {f.get("action") for f in report.get("fixes", [])}
    cur = path

    if "strip_to_bed" in actions or "reseam_music" in actions:
        try:
            cur = Path(_reseam_original_music(cur, log=log))
        except Exception as e:  # noqa: BLE001
            log(f"  (sponsor music fix failed: {e})")

    if "stabilize_tail" in actions:
        try:
            cur = Path(_stabilize_tail(cur, log=log))
        except Exception as e:  # noqa: BLE001
            log(f"  (sponsor stabilize failed: {e})")

    return str(cur)


def _original_bed() -> Path | None:
    root = Path(__file__).resolve().parent.parent
    stock = root / "assets" / "sponsor" / "high_place_mortgage_sponsor_stock.mp4"
    staging = Path.home() / "Movies" / "AUTOEDITING FORGE Staging" / "hpm-ad-build" / "original_ad_bed.wav"
    if staging.exists():
        return staging
    if stock.exists():
        staging.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg.run([
            "ffmpeg", "-y", "-v", "error", "-i", str(stock),
            "-vn", "-acodec", "pcm_s16le", "-ar", "48000", "-ac", "2", str(staging),
        ])
        return staging
    bed2 = root / "assets" / "sponsor" / "hpm_bed2.wav"
    return bed2 if bed2.exists() else None


def _reseam_original_music(path: Path, log=print) -> str:
    """Replace audio with crossfade-looped original bed only."""
    import math
    bed = _original_bed()
    if bed is None:
        raise RuntimeError("No original HPM music bed found")
    total = ffmpeg.probe_duration(str(path))
    bed_dur = ffmpeg.probe_duration(str(bed))
    xf = 1.5
    n = max(2, math.ceil((total - xf) / max(0.5, bed_dur - xf)) + 1)
    inputs: list[str] = []
    for _ in range(n):
        inputs += ["-i", str(bed)]
    parts = []
    cur = "[0:a]"
    for i in range(1, n):
        lab = f"[a{i}]"
        parts.append(f"{cur}[{i}:a]acrossfade=d={xf}:c1=tri:c2=tri{lab}")
        cur = lab
    wav = path.with_name(path.stem + "_reseamed.wav")
    fc = ";".join(parts) + (
        f";{cur}atrim=0:{total:.3f},asetpts=PTS-STARTPTS,"
        f"afade=t=in:st=0:d=0.35,afade=t=out:st={max(0, total-0.8):.2f}:d=0.8,"
        f"volume=0.95,alimiter=limit=0.95[a]"
    )
    ffmpeg.run([
        "ffmpeg", "-y", "-v", "error", *inputs,
        "-filter_complex", fc, "-map", "[a]", str(wav),
    ])
    mixed = path.with_name(path.stem + "_qcfix.mp4")
    ffmpeg.run([
        "ffmpeg", "-y", "-v", "error",
        "-i", str(path), "-i", str(wav),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "256k",
        "-shortest", "-movflags", "+faststart", str(mixed),
    ])
    ffmpeg.run(["cp", str(mixed), str(path)])
    log("  sponsor fix: seamless original music bed applied")
    return str(path)


def _stabilize_tail(path: Path, log=print, tail_ratio: float = 0.45) -> str:
    """Deshake the whole spot lightly (safe) — reduces shaky tails."""
    out = path.with_name(path.stem + "_stable.mp4")
    # deshake + slight zoom to hide edges; keep audio
    ffmpeg.run([
        "ffmpeg", "-y", "-v", "error",
        "-i", str(path),
        "-vf", "deshake=rx=16:ry=16:edge=mirror,scale=1920:1080:force_original_aspect_ratio=increase,"
               "crop=1920:1080,setsar=1",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "17",
        "-c:a", "aac", "-b:a", "256k",
        "-movflags", "+faststart", str(out),
    ])
    ffmpeg.run(["cp", str(out), str(path)])
    log("  sponsor fix: deshake / stabilize applied")
    return str(path)


def review_and_fix(path: str | Path, log=print, max_passes: int = 2) -> dict:
    """QC → auto-fix → re-QC. Returns final report (verdict pass/warn/fail)."""
    path = str(path)
    report = analyze(path, log=log)
    for i in range(max_passes):
        if report.get("verdict") == "pass":
            break
        if not report.get("fixes"):
            break
        log(f"  sponsor QC pass {i+1}: applying {len(report['fixes'])} fix(es)…")
        apply_auto_fixes(path, report, log=log)
        report = analyze(path, log=log)
    # Fold in growing editorial priors + never-again dislike rules
    try:
        from .learning.apply import compare_edit_to_priors
        from .learning.dislikes import violations_for_report, active_rules_for
        learned = compare_edit_to_priors(path, log=log)
        report["learning_compare"] = learned
        for issue in learned.get("issues") or []:
            report.setdefault("recommendations", []).append(f"[learned] {issue}")
            if report.get("verdict") == "pass":
                report["verdict"] = "warn"
        never = violations_for_report(report, situation="sponsor")
        report["never_again"] = {
            "rules": active_rules_for("sponsor"),
            "violations": never,
        }
        for v in never:
            report.setdefault("recommendations", []).append(f"[never-again] {v}")
            report["verdict"] = "fail"
    except Exception:  # noqa: BLE001
        pass
    return report


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="Sponsor spot QC (review before show)")
    p.add_argument("path", help="Path to sponsor mp4")
    p.add_argument("--fix", action="store_true", help="Auto-apply safe fixes and re-QC")
    p.add_argument("-o", "--out", default="", help="Write JSON report here")
    args = p.parse_args(argv)
    log = lambda m="": print(m, flush=True)
    report = review_and_fix(args.path, log=log) if args.fix else analyze(args.path, log=log)
    out = args.out or str(Path(args.path).with_suffix("")) + "_qc_sponsor.json"
    # prefer beside file as qc_sponsor.json when under a job out/
    if not args.out:
        sibling = Path(args.path).parent / "qc_sponsor.json"
        out = str(sibling)
    write_report(report, out)
    log(json.dumps({"verdict": report["verdict"], "issues": report["issues"],
                    "recommendations": report["recommendations"]}, indent=2))
    return 0 if report["verdict"] in ("pass", "warn") else 1


if __name__ == "__main__":
    raise SystemExit(main())
