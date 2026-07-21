"""Cinematic bits generated with ffmpeg: title cards + the mixed master audio."""

from __future__ import annotations

from pathlib import Path

from . import ffmpeg, textgen


def make_title_card(
    title: str,
    subtitle: str,
    out_path: str | Path,
    width: int,
    height: int,
    fps: int,
    duration: float = 4.0,
    fade: float = 0.6,
) -> Path:
    """Render a clean, fading title card (Pillow PNG -> ffmpeg clip w/ silent audio)."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    png = out_path.with_suffix(".png")
    textgen.title_card_png(title, subtitle, width, height, png)

    # Clamp so short title cards don't dissolve into nothing.
    fade = min(max(0.0, fade), max(0.0, duration / 2.0))
    fout = max(0.0, duration - fade)
    if fade >= 0.02:
        vf = (f"fps={fps},format=yuv420p,"
              f"fade=t=in:st=0:d={fade:.3f},fade=t=out:st={fout:.3f}:d={fade:.3f}")
    else:
        vf = f"fps={fps},format=yuv420p"
    ffmpeg.run([
        "ffmpeg", "-y", "-v", "error",
        "-loop", "1", "-i", str(png),
        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
        "-t", f"{duration:.3f}",
        "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", str(fps),
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", str(out_path),
    ])
    return out_path


def mix_master_audio(
    mic_paths: list[str],
    offsets_sec: list[float],
    out_wav: str | Path,
    gains_db: list[float] | None = None,
) -> Path:
    """Mix all mics (delay-aligned) into one stereo wav — used for captions
    and as the timeline's audio track."""
    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for p in mic_paths:
        cmd += ["-i", str(p)]
    gains_db = gains_db or [0.0] * len(mic_paths)
    if len(gains_db) != len(mic_paths):
        raise ValueError("gains_db must match mic_paths")
    parts = []
    for i, off in enumerate(offsets_sec):
        d = max(0, int(round(off * 1000)))
        gain = float(gains_db[i])
        volume = f",volume={gain:.1f}dB" if abs(gain) >= 0.05 else ""
        parts.append(
            f"[{i}:a]aresample=48000,adelay={d}|{d}{volume}[a{i}]"
        )
    labels = "".join(f"[a{i}]" for i in range(len(mic_paths)))
    fc = (";".join(parts) + ";" + labels +
          f"amix=inputs={len(mic_paths)}:normalize=0,dynaudnorm=f=250:g=15[a]")
    cmd += ["-filter_complex", fc, "-map", "[a]",
            "-ac", "2", "-ar", "48000", "-acodec", "pcm_s16le", str(out_wav)]
    ffmpeg.run(cmd)
    return out_wav
