"""Align every camera and mic to a common clock via audio cross-correlation.

Every mic and every camera's built-in scratch audio hears the same room, so we
line each one up against a chosen reference mic.  Result: a per-source offset in
seconds. Assembly adds that offset when it seeks into each file.
"""

from __future__ import annotations

from pathlib import Path

from . import audiotools, ffmpeg
from .config import Config

CORRELATE_SECONDS = 180        # analyse up to the first N seconds for speed
ANALYSIS_SR = 8000


def _vid_id(name: str) -> str:
    return f"vid:{name}"


def _mic_id(name: str) -> str:
    return f"mic:{name}"


def compute(cfg: Config, workdir: Path, log=print) -> dict[str, float]:
    """Return {source_id: offset_seconds} for every video and mic."""
    ref_name = cfg.sync_reference or cfg.mic_angles()[0].name
    ref_angle = cfg.angle_by_name(ref_name)

    offsets: dict[str, float] = {}
    # Reference mic defines time zero.
    offsets[_mic_id(ref_name)] = cfg.manual_offsets.get(_mic_id(ref_name), 0.0)

    if not cfg.sync_enabled:
        for a in cfg.angles:
            offsets.setdefault(_vid_id(a.name),
                               cfg.manual_offsets.get(_vid_id(a.name), 0.0))
            if a.mic:
                offsets.setdefault(_mic_id(a.name),
                                   cfg.manual_offsets.get(_mic_id(a.name), 0.0))
        return offsets

    ref_wav = workdir / "sync_ref.wav"
    ffmpeg.extract_mono_wav(cfg.resolve(ref_angle.mic), ref_wav,
                            sr=ANALYSIS_SR, duration=CORRELATE_SECONDS)
    _, ref = ffmpeg.read_wav_mono(ref_wav)

    def offset_for(source_path: str, sid: str) -> float:
        if sid in cfg.manual_offsets:
            return float(cfg.manual_offsets[sid])
        tmp = workdir / (sid.replace(":", "_") + ".wav")
        try:
            ffmpeg.extract_mono_wav(cfg.resolve(source_path), tmp,
                                    sr=ANALYSIS_SR, duration=CORRELATE_SECONDS)
            _, sig = ffmpeg.read_wav_mono(tmp)
            if sig.size == 0:
                raise ValueError("no audio")
            return audiotools.find_offset_seconds(
                ref, sig, ANALYSIS_SR, cfg.sync_max_offset_sec)
        except Exception as e:                      # noqa: BLE001
            log(f"  ! could not sync {sid} ({e}); assuming 0.0s")
            return 0.0

    for a in cfg.angles:
        vid = _vid_id(a.name)
        offsets[vid] = offset_for(a.video, vid)
        if a.mic and _mic_id(a.name) not in offsets:
            mid = _mic_id(a.name)
            # Video-follows-audio: mic is the camera file itself — same clock.
            try:
                same = (Path(cfg.resolve(a.mic)).resolve()
                        == Path(cfg.resolve(a.video)).resolve())
            except OSError:
                same = a.mic == a.video
            offsets[mid] = offsets[vid] if same else offset_for(a.mic, mid)

    return offsets
