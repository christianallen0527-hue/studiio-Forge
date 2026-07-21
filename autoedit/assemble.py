"""Render the long-form episode from the cut list using ffmpeg.

Each segment is rendered to a uniform intermediate clip (chosen camera video +
a mix of all mics for that time range), then all intermediates are concatenated
with stream copy.  This stays correct for any number of cuts and handles
silence-removed gaps automatically.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from . import ffmpeg
from .config import Config
from .operator import Shot
from .switch import Segment
from .sync import _mic_id, _vid_id


def render_operator(
    cfg: Config,
    source: str,
    source_offset: float,
    master_audio: str,
    shots: list[Shot],
    workdir: Path,
    out_path: Path,
    log=print,
    prepend: list[str] | None = None,
    grade_vf: str | None = None,
) -> Path:
    """Render single-camera operated coverage: each shot is a framed punch-in
    (optionally with a slow push) cut from the high-res source, audio from the mix.
    `prepend` clips (e.g. a title card at the output size) play first.
    `grade_vf` is an optional ffmpeg color-grade chain applied to each shot."""
    seg_dir = workdir / "op_segments"
    seg_dir.mkdir(parents=True, exist_ok=True)
    lines: list[str] = [f"file '{Path(p).as_posix()}'" for p in (prepend or [])]
    for idx, s in enumerate(shots):
        dur = s.end - s.start
        if dur <= 0.05:
            continue
        z0, push = s.zoom, s.push
        # Time-varying crop (push-in); centred on the subject, clamped to frame.
        zexpr = f"({z0}-{push}*min(t/{dur:.3f}\\,1))"
        crop = (f"crop=w='min(iw\\,iw*{zexpr})':h='min(ih\\,ih*{zexpr})':"
                f"x='max(0\\,min(iw-ow\\,iw*{s.cx}-ow/2))':"
                f"y='max(0\\,min(ih-oh\\,ih*{s.cy}-oh/2))'")
        vf = (f"{crop},scale={cfg.width}:{cfg.height}:flags=bicubic,setsar=1"
              + (f",{grade_vf}" if grade_vf else "")
              + f",fps={cfg.fps},format=yuv420p")
        v_start = max(0.0, s.start + source_offset)
        seg_out = seg_dir / f"op_{idx:05d}.mp4"
        ffmpeg.run([
            "ffmpeg", "-y", "-v", "error",
            "-ss", f"{v_start:.3f}", "-t", f"{dur:.3f}", "-i", source,
            "-ss", f"{s.start:.3f}", "-t", f"{dur:.3f}", "-i", master_audio,
            "-vf", vf, "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-r", str(cfg.fps),
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", str(seg_out),
        ])
        lines.append(f"file '{seg_out.as_posix()}'")
        if (idx + 1) % 20 == 0:
            log(f"  operated {idx + 1}/{len(shots)} shots")
    if not lines:
        raise RuntimeError("Camera operator produced no shots.")
    lst = workdir / "op_concat.txt"
    lst.write_text("\n".join(lines) + "\n")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                "-i", str(lst), "-c", "copy", "-movflags", "+faststart", str(out_path)])
    log(f"  wrote {out_path}  ({len(lines)} operated shots)")
    return out_path


# ---------------------------------------------------------------------------
# Editorial finishing helpers (cross-dissolves, fades, loudness, orientation)
# ---------------------------------------------------------------------------

_ENC = [
    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
    "-ar", "48000", "-ac", "2", "-movflags", "+faststart",
]

# Joins shorter than this are treated as hard (no xfade/acrossfade).
_MIN_XFADE = 0.02
# Never let a dissolve consume more than this fraction of either side.
_MAX_XFADE_FRAC = 0.45


def _zone_for_index(i: int, n_pre: int, n_body: int, n_post: int) -> str:
    """Classify clip index as 'pre' (intro/title/sponsor), 'body', or 'post'."""
    if i < n_pre:
        return "pre"
    if i < n_pre + n_body:
        return "body"
    return "post"


def join_kinds_from_zones(zones: list[str]) -> list[str]:
    """Speech only for body→body; everything else is a structural dissolve."""
    if len(zones) < 2:
        return []
    kinds: list[str] = []
    for i in range(len(zones) - 1):
        if zones[i] == "body" and zones[i + 1] == "body":
            kinds.append("speech")
        else:
            kinds.append("structural")
    return kinds


def join_kinds(n_pre: int, n_body: int, n_post: int) -> list[str]:
    """Return 'structural' or 'speech' for each join between consecutive clips.

    Structural = anything touching intro/title/sponsor/outro (or between those).
    Speech = body→body (filler/pause/silence jump-cuts, cam switches).
    """
    n = n_pre + n_body + n_post
    zones = [
        _zone_for_index(i, n_pre, n_body, n_post) for i in range(n)
    ]
    return join_kinds_from_zones(zones)


def clamp_xfade(
    desired: float,
    left_dur: float,
    right_dur: float,
    chain_dur: float,
    min_sec: float = _MIN_XFADE,
    max_frac: float = _MAX_XFADE_FRAC,
) -> float:
    """Clamp a dissolve/crossfade so both sides and the running chain can afford it.

    Returns 0.0 when a useful transition cannot fit (caller should hard-cut).
    Never forces a minimum that exceeds the available budget (fixes the old
    behaviour that pinned t_k to 0.05 even on tiny clips).
    """
    if desired <= 0 or left_dur <= 0 or right_dur <= 0 or chain_dur <= 0:
        return 0.0
    budget = min(left_dur, right_dur, chain_dur) * max_frac
    # Leave a sliver of each side so xfade offset stays valid.
    budget = min(budget, left_dur - 1e-3, right_dur - 1e-3, chain_dur - 1e-3)
    t = min(float(desired), max(0.0, budget))
    if t < min_sec:
        return 0.0
    return t


def plan_join_durations(
    durs: list[float],
    kinds: list[str],
    *,
    structural_sec: float,
    speech_video_sec: float,
    speech_audio_sec: float,
) -> list[float]:
    """Per-join overlap seconds used for both xfade and acrossfade (A/V lock).

    Speech joins default to a micro crossfade (audio continuity without a mushy
    dissolve). When speech_video_sec > 0 that length is used instead. Structural
    joins use structural_sec. Durations are clamped for short clips.
    """
    n = len(durs)
    if n < 2:
        return []
    if len(kinds) != n - 1:
        raise ValueError(f"kinds length {len(kinds)} != joins {n - 1}")

    joins: list[float] = []
    acc = durs[0]
    for k in range(1, n):
        kind = kinds[k - 1]
        if kind == "structural":
            desired = float(structural_sec)
        else:
            # Prefer an explicit speech dissolve; else micro audio blend.
            # Same value for v+a so the filter chain stays in sync.
            desired = (
                float(speech_video_sec)
                if speech_video_sec > 0
                else float(speech_audio_sec)
            )
        t = clamp_xfade(desired, acc, durs[k], acc)
        joins.append(t)
        acc = acc + durs[k] - t
    return joins


def clamp_program_fades(fade_sec: float, total: float) -> float:
    """Episode fade in/out length that still leaves visible program content."""
    if fade_sec <= 0 or total <= 0:
        return 0.0
    # Keep at least ~1/3 of the program undimmed when possible.
    return min(float(fade_sec), max(0.0, total / 3.0))


def _has_audio(path: str) -> bool:
    """True if the media file carries at least one audio stream."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    return bool(out.stdout.strip())


def _normalize_clip(cfg: Config, src: str, dst: Path) -> str:
    """Re-encode an arbitrary intro/outro/sponsor clip to the uniform
    intermediate spec (WxH, fps, yuv420p, stereo 48k aac) so it can take part
    in the cross-dissolve chain and concat regardless of its source format.
    Silent sources get a generated stereo silence track."""
    has_audio = _has_audio(src)
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(src)]
    if not has_audio:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    vf = (
        f"scale={cfg.width}:{cfg.height}:force_original_aspect_ratio=decrease,"
        f"pad={cfg.width}:{cfg.height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"fps={cfg.fps},format=yuv420p,setsar=1"
    )
    amap = "1:a" if not has_audio else "0:a"
    cmd += [
        "-filter_complex",
        f"[0:v]{vf}[v];[{amap}]aresample=48000,aformat=channel_layouts=stereo[a]",
        "-map", "[v]", "-map", "[a]", "-r", str(cfg.fps),
    ] + _ENC
    if not has_audio:
        cmd += ["-shortest"]
    cmd += [str(dst)]
    ffmpeg.run(cmd)
    return str(dst)


def _render_with_transitions(
    cfg: Config,
    clips: list[str],
    out_path: Path,
    log=print,
    n_pre: int = 0,
    n_post: int = 0,
    zones: list[str] | None = None,
) -> Path:
    """Join uniform intermediates with smart editorial transitions.

    Body→body (speech) joins: dissolve when speech_transition_sec > 0, else
    micro acrossfade. Structural joins (intro/title/midroll/outro): longer
    cross-dissolve. Then program fade in/out + optional loudnorm.
    """
    durs = [ffmpeg.probe_duration(c) for c in clips]
    n = len(clips)
    n_pre = max(0, min(int(n_pre), n))
    n_post = max(0, min(int(n_post), n - n_pre))
    n_body = n - n_pre - n_post

    structural_sec = float(getattr(cfg, "transition_sec", 0.5) or 0.0)
    speech_video = float(getattr(cfg, "speech_transition_sec", 0.0) or 0.0)
    speech_audio = float(getattr(cfg, "speech_audio_crossfade_sec", 0.04) or 0.0)
    F_req = float(getattr(cfg, "fade_sec", 0.5) or 0.0)

    if zones is not None and len(zones) == n:
        kinds = join_kinds_from_zones(zones)
    else:
        kinds = join_kinds(n_pre, n_body, n_post)
    join_ts = plan_join_durations(
        durs, kinds,
        structural_sec=structural_sec,
        speech_video_sec=speech_video,
        speech_audio_sec=speech_audio,
    )

    cmd = ["ffmpeg", "-y", "-v", "error"]
    for c in clips:
        cmd += ["-i", str(c)]

    vparts: list[str] = []
    aparts: list[str] = []

    if n == 1:
        total = durs[0]
        prev_v, prev_a = "[0:v]", "[0:a]"
    else:
        acc = durs[0]
        prev_v, prev_a = "[0:v]", "[0:a]"
        for k in range(1, n):
            t_k = join_ts[k - 1]
            last = k == n - 1
            vout = "[vchain]" if last else f"[vx{k}]"
            aout = "[achain]" if last else f"[ax{k}]"
            if t_k >= _MIN_XFADE:
                off = max(0.0, acc - t_k)
                vparts.append(
                    f"{prev_v}[{k}:v]xfade=transition=fade:"
                    f"duration={t_k:.3f}:offset={off:.3f}{vout}")
                aparts.append(
                    f"{prev_a}[{k}:a]acrossfade=d={t_k:.3f}:c1=tri:c2=tri{aout}")
                acc = acc + durs[k] - t_k
            else:
                # True hard cut — concat keeps A/V durations matched.
                vparts.append(f"{prev_v}[{k}:v]concat=n=2:v=1:a=0{vout}")
                aparts.append(f"{prev_a}[{k}:a]concat=n=2:v=0:a=1{aout}")
                acc = acc + durs[k]
            prev_v, prev_a = vout, aout
        total = acc

    F = clamp_program_fades(F_req, total)
    if F >= _MIN_XFADE:
        out_v = max(0.0, total - F)
        vparts.append(
            f"{prev_v}fade=t=in:st=0:d={F:.3f},"
            f"fade=t=out:st={out_v:.3f}:d={F:.3f},format=yuv420p[v]")
        afade = (f"{prev_a}afade=t=in:st=0:d={F:.3f},"
                 f"afade=t=out:st={out_v:.3f}:d={F:.3f}")
    else:
        vparts.append(f"{prev_v}format=yuv420p[v]")
        afade = f"{prev_a}anull"

    if cfg.audio_normalize:
        afade += ",loudnorm=I=-14:TP=-1.5:LRA=11"
    aparts.append(afade + "[a]")

    cmd += [
        "-filter_complex", ";".join(vparts + aparts),
        "-map", "[v]", "-map", "[a]", "-r", str(cfg.fps),
    ] + _ENC + [str(out_path)]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg.run(cmd)

    n_struct = sum(1 for k, t in zip(kinds, join_ts) if k == "structural" and t >= _MIN_XFADE)
    n_speech = sum(1 for k in kinds if k == "speech")
    log(f"  wrote {out_path}  ({n} clips, ~{total:.1f}s, "
        f"{n_struct} structural dissolves, {n_speech} speech joins, fades={F:.2f}s)")
    return out_path


def render(
    cfg: Config,
    segments: list[Segment],
    offsets: dict[str, float],
    workdir: Path,
    out_path: Path,
    log=print,
    grade_vf: str | None = None,
    prepend: list[str] | None = None,
    append: list[str] | None = None,
    midroll: list[str] | None = None,
) -> Path:
    """Straight edit: keep each camera's original framing, cut on the audio,
    optionally color-grade. This is the path for already-shot-ready footage —
    no reframing, no punch-ins.

    `prepend` (intro / title) play first, `midroll` (sponsor) lands in the
    middle of the body, `append` (outro) play last. When `cfg.transitions`
    is on (default): structural dissolves at those boundaries; smooth body
    joins; program fade in/out + loudnorm.
    """
    mics = cfg.mic_angles()
    seg_dir = workdir / "segments"
    seg_dir.mkdir(parents=True, exist_ok=True)
    list_file = workdir / "concat.txt"

    seg_paths: list[str] = []
    for idx, seg in enumerate(segments):
        dur = seg.end - seg.start
        if dur <= 0.02:
            continue
        angle = cfg.angle_by_name(seg.angle)
        seg_out = seg_dir / f"seg_{idx:05d}.mp4"

        cmd = ["ffmpeg", "-y", "-v", "error"]

        # input 0: chosen camera video
        v_start = max(0.0, seg.start + offsets.get(_vid_id(seg.angle), 0.0))
        cmd += ["-ss", f"{v_start:.3f}", "-t", f"{dur:.3f}",
                "-i", cfg.resolve(angle.video)]

        # inputs 1..M: every mic (for the mixed master audio)
        for m in mics:
            a_start = max(0.0, seg.start + offsets.get(_mic_id(m.name), 0.0))
            cmd += ["-ss", f"{a_start:.3f}", "-t", f"{dur:.3f}",
                    "-i", cfg.resolve(m.mic)]

        # Orientation fix only (defect correction, not creative reframing):
        # a 180° camera gets flipped both axes.
        rot = ("vflip,hflip," if getattr(angle, "rotate", 0) == 180 else "")
        vf = (
            f"scale={cfg.width}:{cfg.height}:force_original_aspect_ratio=decrease,"
            f"pad={cfg.width}:{cfg.height}:(ow-iw)/2:(oh-ih)/2:color=black,"
            + rot
            + (f"{grade_vf}," if grade_vf else "")
            + f"fps={cfg.fps},format=yuv420p,setsar=1"
        )
        audio_parts: list[str] = []
        audio_labels: list[str] = []
        for i, mic in enumerate(mics):
            gain = float(getattr(mic, "audio_gain_db", 0.0))
            label = f"am{i}"
            filt = f"[{i+1}:a]"
            if abs(gain) >= 0.05:
                filt += f"volume={gain:.1f}dB"
            else:
                filt += "anull"
            audio_parts.append(f"{filt}[{label}]")
            audio_labels.append(f"[{label}]")
        amix_inputs = "".join(audio_labels)
        afilter = (
            ";".join(audio_parts) + ";"
            + f"{amix_inputs}amix=inputs={len(mics)}:duration=longest:normalize=0,"
            f"dynaudnorm=f=250:g=15[a]"
        )
        cmd += [
            "-filter_complex", f"[0:v]{vf}[v];{afilter}",
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-r", str(cfg.fps),
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", str(seg_out),
        ]
        ffmpeg.run(cmd)
        seg_paths.append(str(seg_out))
        if (idx + 1) % 25 == 0:
            log(f"  rendered {idx + 1}/{len(segments)} segments")

    # Normalise any intro/title/sponsor/outro clips to the intermediate spec so
    # they join cleanly (any source format) and take part in the dissolves.
    norm_dir = workdir / "extras"
    norm_dir.mkdir(parents=True, exist_ok=True)
    pre_clips = [_normalize_clip(cfg, p, norm_dir / f"pre_{i:03d}.mp4")
                 for i, p in enumerate(prepend or [])]
    mid_clips = [_normalize_clip(cfg, p, norm_dir / f"mid_{i:03d}.mp4")
                 for i, p in enumerate(midroll or [])]
    post_clips = [_normalize_clip(cfg, p, norm_dir / f"post_{i:03d}.mp4")
                  for i, p in enumerate(append or [])]

    # Midroll sponsor lands at the midpoint of the body (by duration).
    if mid_clips and seg_paths:
        body_durs = [ffmpeg.probe_duration(p) for p in seg_paths]
        half = sum(body_durs) / 2.0
        acc = 0.0
        cut = len(seg_paths) // 2  # fallback
        for i, d in enumerate(body_durs):
            if acc + d >= half:
                # Prefer the join after this clip unless most of the half
                # still sits inside it — then split that one clip.
                into = half - acc
                if 1.0 < into < (d - 1.0) and len(seg_paths) == 1:
                    left = norm_dir / "body_mid_a.mp4"
                    right = norm_dir / "body_mid_b.mp4"
                    ffmpeg.run([
                        "ffmpeg", "-y", "-v", "error",
                        "-i", seg_paths[0], "-t", f"{into:.3f}",
                        "-c", "copy", str(left),
                    ])
                    ffmpeg.run([
                        "ffmpeg", "-y", "-v", "error",
                        "-ss", f"{into:.3f}", "-i", seg_paths[0],
                        "-c", "copy", str(right),
                    ])
                    seg_paths = [str(left), str(right)]
                    cut = 1
                else:
                    cut = i + 1 if into >= d * 0.5 else i
                break
            acc += d
        cut = max(0, min(cut, len(seg_paths)))
        body_a, body_b = seg_paths[:cut], seg_paths[cut:]
        if not body_a and body_b:
            body_a = [body_b.pop(0)]
        if not body_b and body_a:
            body_b = [body_a.pop()]
        log(f"  midroll sponsor after {len(body_a)} body clip(s) "
            f"(~{sum(ffmpeg.probe_duration(p) for p in body_a):.1f}s)")
    else:
        body_a, body_b = seg_paths, []

    clips = pre_clips + body_a + mid_clips + body_b + post_clips
    zones = (
        ["pre"] * len(pre_clips)
        + ["body"] * len(body_a)
        + ["mid"] * len(mid_clips)
        + ["body"] * len(body_b)
        + ["post"] * len(post_clips)
    )
    if not clips:
        raise RuntimeError("No segments to render — check your input/config.")

    out_path.parent.mkdir(parents=True, exist_ok=True)

    if cfg.transitions:
        return _render_with_transitions(
            cfg, clips, out_path, log=log,
            n_pre=len(pre_clips), n_post=len(post_clips),
            zones=zones,
        )

    # Fallback: plain hard-cut concat (backward-compatible behaviour).
    lines = [f"file '{Path(p).as_posix()}'" for p in clips]
    list_file.write_text("\n".join(lines) + "\n")
    ffmpeg.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                "-i", str(list_file), "-c", "copy",
                "-movflags", "+faststart", str(out_path)])
    log(f"  wrote {out_path}")
    return out_path
