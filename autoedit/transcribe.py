"""Optional local transcription via faster-whisper (free, offline).

Returns both sentence-level cues (for captions) and word-level timings (for
filler/pause removal). If faster-whisper isn't installed, the caller skips the
stages that need it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Cue:
    start: float
    end: float
    text: str


@dataclass
class Transcript:
    cues: list[Cue] = field(default_factory=list)
    words: list[Word] = field(default_factory=list)


class WhisperUnavailable(RuntimeError):
    pass


def transcribe(media_path: str | Path, model_size: str = "base") -> Transcript:
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:                       # noqa: BLE001
        raise WhisperUnavailable(
            "faster-whisper is not installed. Install it with:\n"
            "    pip install faster-whisper\n"
            "(or disable transcription in the config)"
        ) from e

    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(media_path), vad_filter=True,
                                   word_timestamps=True)
    cues: list[Cue] = []
    words: list[Word] = []
    for s in segments:
        text = s.text.strip()
        if text:
            cues.append(Cue(s.start, s.end, text))
        for w in (s.words or []):
            t = w.word.strip()
            if t:
                words.append(Word(w.start, w.end, t))
    return Transcript(cues=cues, words=words)


def _ts(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms == 1000:
        ms, s = 0, s + 1
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(cues: list[Cue], path: str | Path, offset: float = 0.0) -> None:
    """Write cues to an .srt, shifting times by -offset (for clip-local subs)."""
    lines = []
    n = 1
    for c in cues:
        start, end = c.start - offset, c.end - offset
        if end <= 0:
            continue
        lines.append(str(n))
        lines.append(f"{_ts(max(0, start))} --> {_ts(end)}")
        lines.append(c.text)
        lines.append("")
        n += 1
    Path(path).write_text("\n".join(lines), encoding="utf-8")
