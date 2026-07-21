"""Thin wrappers around the ffmpeg / ffprobe command-line tools."""

from __future__ import annotations

import json
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np


class FFmpegError(RuntimeError):
    pass


def require_ffmpeg() -> None:
    """Raise a friendly error if ffmpeg/ffprobe are not installed."""
    missing = [t for t in ("ffmpeg", "ffprobe") if shutil.which(t) is None]
    if missing:
        raise FFmpegError(
            "Missing required tool(s): "
            + ", ".join(missing)
            + "\n\nInstall the free ffmpeg package first:\n"
            + "    brew install ffmpeg\n"
        )


def run(cmd: list[str], quiet: bool = True) -> None:
    """Run an ffmpeg command, raising FFmpegError with stderr on failure."""
    proc = subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL if quiet else None,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").splitlines()[-20:])
        raise FFmpegError(f"Command failed ({' '.join(cmd[:3])} …):\n{tail}")


def probe_duration(path: str | Path) -> float:
    """Return the duration of a media file in seconds."""
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise FFmpegError(f"Could not read {path}:\n{out.stderr}")
    return float(json.loads(out.stdout)["format"]["duration"])


def extract_mono_wav(
    src: str | Path,
    dst: str | Path,
    sr: int = 8000,
    start: float = 0.0,
    duration: float | None = None,
) -> None:
    """Extract a mono PCM wav (for analysis) from any media file."""
    cmd = ["ffmpeg", "-y", "-v", "error"]
    if start:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(src)]
    if duration is not None:
        cmd += ["-t", f"{duration:.3f}"]
    cmd += ["-ac", "1", "-ar", str(sr), "-vn",
            "-acodec", "pcm_s16le", "-f", "wav", str(dst)]
    run(cmd)


def read_wav_mono(path: str | Path) -> tuple[int, np.ndarray]:
    """Read a 16-bit mono wav into a float32 array in [-1, 1]."""
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        n = w.getnframes()
        raw = w.readframes(n)
    data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    return sr, data
