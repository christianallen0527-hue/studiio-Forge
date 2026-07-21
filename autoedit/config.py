"""Load and validate the YAML project config."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Angle:
    name: str
    video: str
    mic: str | None = None          # None => used as a wide / group shot only
    rotate: int = 0                 # 0 or 180; 180 corrects an upside-down camera (vflip,hflip)
    audio_gain_db: float = 0.0       # isolated-mic gain; review may set this at runtime


@dataclass
class Config:
    angles: list[Angle]
    wide: str | None = None          # name of the angle used for cross-talk/silence
    base_dir: Path = field(default_factory=Path.cwd)

    # switching (video-follows-audio)
    window_sec: float = 0.1
    activation_db: float = -35.0
    min_shot_sec: float = 1.5
    overlap_to_wide: bool = True
    fallback: str = "wide"
    # When True, each angle's mic may be the camera file itself (embedded audio).
    video_follows_audio: bool = True
    # dB above per-mic noise floor to count as talking (None = absolute gate only).
    relative_activation_db: float | None = 8.0
    # Stay on current speaker unless another is this many dB louder.
    switch_margin_db: float = 2.0

    # sync
    sync_enabled: bool = True
    sync_reference: str | None = None
    sync_max_offset_sec: float = 5.0
    manual_offsets: dict = field(default_factory=dict)   # name -> seconds

    # silence
    silence_remove: bool = False
    silence_min_gap_sec: float = 1.5
    silence_keep_pad_sec: float = 0.3

    # transcript-driven smoothing (needs faster-whisper)
    refine_fillers: bool = True
    filler_words: list = field(default_factory=list)   # empty => refine.DEFAULT_FILLERS
    refine_pauses: bool = True
    pause_sec: float = 0.6
    pause_keep_pad_sec: float = 0.15

    # AI Camera Operator (single high-res camera -> operated coverage)
    operator_enabled: bool = False
    operator_intensity: str = "dynamic"   # calm | dynamic | punchy
    operator_x: float = 0.5
    operator_y: float = 0.44
    operator_face: bool = True            # face-tracked framing (cinematic)

    # cinematic: title card + intro/outro
    title_text: str = ""
    title_subtitle: str = ""
    title_duration: float = 4.0
    intro_video: str | None = None
    outro_video: str | None = None
    sponsor_video: str | None = None   # sponsor spot footage
    # after_title = after intro/title; midroll = middle of the body edit
    sponsor_placement: str = "midroll"

    # editorial finishing — baked into the ffmpeg straight-edit render
    # Client-review default: smooth dissolves on every join (no jump cuts).
    transitions: bool = True          # editorial join pass (else plain concat)
    transition_sec: float = 0.6       # visual+audio dissolve at structural boundaries
    speech_transition_sec: float = 0.4   # body→body visual dissolve (0 = hard/micro)
    speech_audio_crossfade_sec: float = 0.04  # used only when speech_transition_sec=0
    fade_sec: float = 0.75            # fade in-from-black / out-to-black length
    audio_normalize: bool = True      # loudnorm the final mix to -14 LUFS
    outro_placeholder: bool = True    # auto end-card when no outro.video

    # output
    out_dir: Path = field(default_factory=lambda: Path("out"))
    width: int = 1920
    height: int = 1080
    fps: int = 30
    backend: str = "ffmpeg"          # "ffmpeg" (free) or "resolve" (Studio)
    render: bool = True              # resolve backend: also render, or build-only
    grade: bool = False              # OFF — footage keeps its baked-in LUT (studio system owns the look)
    project_name: str = "AUTOEDITING FORGE"
    render_preset: str = "H.264 Master"

    # transcribe / shorts
    transcribe_enabled: bool = True
    whisper_model: str = "base"
    shorts_enabled: bool = True
    shorts_count: int = 5
    shorts_min_sec: float = 20.0
    shorts_max_sec: float = 60.0
    shorts_captions: bool = True

    # Hardwired Ollama vision (semantic pre-edit + post-edit QC).
    # Default ON — the app auto-starts Ollama + pulls the model. "off" is
    # only for self-tests (AUTOEDIT_VISION=0). Legacy "auto" maps to "on".
    vision_enabled: str = "on"
    vision_model: str = "moondream"
    vision_base_url: str = "http://127.0.0.1:11434"
    vision_timeout_sec: float = 45.0
    vision_samples: int = 3          # stills per clip (pre-edit)
    vision_qc_samples: int = 5       # stills for finished-edit QC
    vision_workdir: str | None = None  # frame cache root; None = beside media

    def resolve(self, p: str) -> str:
        path = Path(p)
        return str(path if path.is_absolute() else self.base_dir / path)

    def mic_angles(self) -> list[Angle]:
        return [a for a in self.angles if a.mic]

    def angle_by_name(self, name: str) -> Angle:
        for a in self.angles:
            if a.name == name:
                return a
        raise KeyError(f"No angle named '{name}'")


def _parse_optional_float(section: dict, key: str, default: float | None) -> float | None:
    """Read an optional float; explicit null/false/off disables the feature."""
    if key not in section:
        return default
    raw = section[key]
    if raw in (None, False, "", "off"):
        return None
    return float(raw)


def load(path: str | Path) -> Config:
    path = Path(path)
    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    angles = [Angle(**a) for a in raw.get("angles", [])]
    if not angles:
        raise ValueError(f"{path}: no 'angles' defined.")

    sw = raw.get("switch", {})
    sy = raw.get("sync", {})
    si = raw.get("silence", {})
    ou = raw.get("output", {})
    tr = raw.get("transcribe", {})
    sh = raw.get("shorts", {})
    rf = raw.get("refine", {})
    op = raw.get("operator", {})
    ti = raw.get("title", {})
    intro = raw.get("intro", {}) or {}
    outro = raw.get("outro", {}) or {}
    sponsor = raw.get("sponsor", {}) or {}
    fin = raw.get("finish", {}) or {}
    vi = raw.get("vision", {}) or {}

    cfg = Config(
        angles=angles,
        wide=raw.get("wide"),
        base_dir=path.resolve().parent,
        window_sec=sw.get("window_sec", 0.1),
        activation_db=sw.get("activation_db", -35.0),
        min_shot_sec=sw.get("min_shot_sec", 1.5),
        overlap_to_wide=sw.get("overlap_to_wide", True),
        fallback=sw.get("fallback", "wide"),
        video_follows_audio=bool(sw.get("video_follows_audio", True)),
        relative_activation_db=_parse_optional_float(
            sw, "relative_activation_db", default=8.0),
        switch_margin_db=float(sw.get("switch_margin_db", 2.0) or 0.0),
        sync_enabled=sy.get("enabled", True),
        sync_reference=sy.get("reference"),
        sync_max_offset_sec=sy.get("max_offset_sec", 5.0),
        manual_offsets=sy.get("manual_offsets", {}) or {},
        silence_remove=si.get("remove", False),
        silence_min_gap_sec=si.get("min_gap_sec", 1.5),
        silence_keep_pad_sec=si.get("keep_pad_sec", 0.3),
        out_dir=Path(ou.get("dir", "out")),
        width=ou.get("width", 1920),
        height=ou.get("height", 1080),
        fps=ou.get("fps", 30),
        backend=ou.get("backend", "ffmpeg"),
        render=ou.get("render", True),
        grade=ou.get("grade", False),
        project_name=ou.get("project_name", "AUTOEDITING FORGE"),
        render_preset=ou.get("render_preset", "H.264 Master"),
        transcribe_enabled=tr.get("enabled", True),
        whisper_model=tr.get("model", "base"),
        shorts_enabled=sh.get("enabled", True),
        shorts_count=sh.get("count", 5),
        shorts_min_sec=sh.get("min_sec", 20.0),
        shorts_max_sec=sh.get("max_sec", 60.0),
        shorts_captions=sh.get("captions", True),
        refine_fillers=rf.get("remove_fillers", True),
        filler_words=rf.get("filler_words", []) or [],
        refine_pauses=rf.get("remove_pauses", True),
        pause_sec=rf.get("pause_sec", 0.6),
        pause_keep_pad_sec=rf.get("keep_pad_sec", 0.15),
        operator_enabled=op.get("enabled", False),
        operator_intensity=op.get("intensity", "dynamic"),
        operator_x=op.get("subject_x", 0.5),
        operator_y=op.get("subject_y", 0.44),
        operator_face=op.get("face", True),
        title_text=ti.get("text", "") or "",
        title_subtitle=ti.get("subtitle", "") or "",
        title_duration=ti.get("duration", 4.0),
        intro_video=intro.get("video"),
        outro_video=outro.get("video"),
        sponsor_video=sponsor.get("video"),
        sponsor_placement=str(
            sponsor.get("placement", "midroll") or "midroll").strip().lower(),
        transitions=fin.get("transitions", True),
        transition_sec=fin.get("transition_sec", 0.6),
        speech_transition_sec=fin.get("speech_transition_sec", 0.4),
        speech_audio_crossfade_sec=fin.get("speech_audio_crossfade_sec", 0.04),
        fade_sec=fin.get("fade_sec", 0.75),
        audio_normalize=fin.get("audio_normalize", True),
        outro_placeholder=bool(
            (raw.get("outro") or {}).get(
                "placeholder",
                fin.get("outro_placeholder", True))),
        vision_enabled=str(vi.get("enabled", "on")).strip().lower() or "on",
        vision_model=vi.get("model", "moondream") or "moondream",
        vision_base_url=vi.get("base_url", "http://127.0.0.1:11434")
            or "http://127.0.0.1:11434",
        vision_timeout_sec=float(vi.get("timeout_sec", 45.0) or 45.0),
        vision_samples=int(vi.get("samples", 3) or 3),
        vision_qc_samples=int(vi.get("qc_samples", 5) or 5),
        vision_workdir=vi.get("workdir"),
    )

    # Podcast / multicam: listen to each camera's embedded audio when no
    # separate mic file is attached (video-follows-audio).
    if cfg.video_follows_audio:
        for a in cfg.angles:
            if not a.mic and a.name != cfg.wide:
                a.mic = a.video

    # Validation
    names = [a.name for a in angles]
    if len(names) != len(set(names)):
        raise ValueError("Angle names must be unique.")
    if cfg.wide and cfg.wide not in names:
        raise ValueError(f"wide '{cfg.wide}' is not one of the angles.")
    if cfg.sync_reference and cfg.sync_reference not in names:
        raise ValueError(f"sync.reference '{cfg.sync_reference}' is not an angle.")
    if not cfg.mic_angles():
        raise ValueError(
            "At least one angle needs a mic (or enable switch.video_follows_audio "
            "to use each camera's embedded audio).")
    if cfg.backend not in ("ffmpeg", "resolve"):
        raise ValueError(f"output.backend must be 'ffmpeg' or 'resolve', got '{cfg.backend}'.")
    if cfg.vision_enabled not in ("off", "on", "auto", "true", "false", "0", "1"):
        raise ValueError(
            f"vision.enabled must be off|on (auto→on), got '{cfg.vision_enabled}'."
        )
    # Normalize — auto/true/1 → on (hardwired); false/0 → off (tests only)
    ve = cfg.vision_enabled
    if ve in ("false", "0", "off"):
        cfg.vision_enabled = "off"
    else:
        cfg.vision_enabled = "on"
    return cfg
