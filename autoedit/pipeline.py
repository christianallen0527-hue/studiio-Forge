"""Full auto-edit: sync -> switch -> mix -> transcribe -> smooth -> titles ->
assemble -> shorts."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import (assemble, audiotools, ffmpeg, operator, refine, review, shorts,
               silence, sync, titles, transcribe)
from .config import Config
from .switch import decide_segments
from .sync import _mic_id, _vid_id


def _build_envelopes(cfg: Config, offsets: dict, workdir: Path, log):
    """Extract embedded (or sidecar) audio and build loudness envelopes in-edit."""
    env_by_name: dict[str, np.ndarray] = {}
    shifts: dict[str, int] = {}
    for a in cfg.mic_angles():
        src = cfg.resolve(a.mic)
        wav = workdir / f"env_{a.name}.wav"
        log(f"  listening to {a.name} ← {Path(src).name}")
        ffmpeg.extract_mono_wav(src, wav, sr=sync.ANALYSIS_SR)
        sr, samples = ffmpeg.read_wav_mono(wav)
        env = audiotools.to_db(
            audiotools.rms_envelope(samples, sr, cfg.window_sec))
        gain = float(getattr(a, "audio_gain_db", 0.0))
        env_by_name[a.name] = env + gain
        shifts[a.name] = round(offsets.get(_mic_id(a.name), 0.0) / cfg.window_sec)

    k = max(max(len(env_by_name[n]) - max(0, shifts[n]) for n in env_by_name), 1)
    master: dict[str, list] = {}
    for name, env in env_by_name.items():
        shift = shifts[name]
        out = np.full(k, -120.0, dtype=np.float32)
        for i in range(k):
            j = i + shift
            if 0 <= j < len(env):
                out[i] = env[j]
        master[name] = out.tolist()
    log(f"  analysed {len(master)} camera audio track(s) over "
        f"{k * cfg.window_sec:.0f}s")
    return master


def _review_sources(cfg: Config, log=print) -> tuple[dict, dict[str, dict]]:
    """Review configured sources and apply safe per-angle decisions in memory."""
    clips: list[dict] = []
    audio: list[dict] = []
    decisions: dict[str, dict] = {}
    video_cache: dict[str, dict] = {}
    audio_cache: dict[str, dict] = {}

    for angle in cfg.angles:
        decisions[angle.name] = review.apply_review({})
        path = cfg.resolve(angle.video)
        try:
            if path not in video_cache:
                video_cache[path] = review.analyze(path, ollama=False)
            clip = video_cache[path]
            decision = review.apply_review(clip)
            decisions[angle.name] = decision
            if angle.rotate != 180 and decision["rotate"] == 180:
                angle.rotate = 180
            clips.append({**clip, "angle": angle.name, "decision": decision})
        except Exception as exc:                         # noqa: BLE001
            log(f"  (review skipped for {Path(path).name}: {exc})")

        if not angle.mic:
            continue
        mic_path = cfg.resolve(angle.mic)
        try:
            if mic_path == path and path in video_cache:
                mic_review = video_cache[path]
            elif mic_path in audio_cache:
                mic_review = audio_cache[mic_path]
            else:
                mic_review = review.analyze_audio(mic_path)
                audio_cache[mic_path] = mic_review
            gain = review.apply_review(mic_review)["audio_gain_db"]
            angle.audio_gain_db = gain
            audio.append({
                **mic_review,
                "angle": angle.name,
                "audio_gain_db": gain,
            })
        except Exception as exc:                         # noqa: BLE001
            log(f"  (audio review skipped for {Path(mic_path).name}: {exc})")

    report = {
        "clips": clips,
        "audio": audio,
        "usable": sum(1 for clip in clips if clip.get("usable", True)),
        "total": len(clips),
        "decisions": decisions,
    }
    return report, decisions


def _consensus_review_trims(
    angle_decisions: dict[str, dict], offsets: dict[str, float]
) -> list[tuple[float, float]]:
    """Return head/tail cuts only when every camera independently agrees.

    Review ranges are source-relative; convert them to the common master clock
    before intersecting. Requiring all configured/reviewed cameras prevents one
    uncertain keyframe detection from deleting otherwise usable coverage.
    """
    if not angle_decisions:
        return []
    per_head: list[tuple[float, float]] = []
    per_tail: list[tuple[float, float]] = []
    for name, decision in angle_decisions.items():
        head = tail = None
        off = offsets.get(_vid_id(name), 0.0)
        for a, b in decision.get("trim_ranges", []) or []:
            mapped = (float(a) - off, float(b) - off)
            if float(a) <= review.EDGE_TOLERANCE_SEC:
                head = mapped if head is None else (
                    min(head[0], mapped[0]), max(head[1], mapped[1])
                )
            else:
                tail = mapped if tail is None else (
                    min(tail[0], mapped[0]), max(tail[1], mapped[1])
                )
        if head is not None:
            per_head.append(head)
        if tail is not None:
            per_tail.append(tail)

    cuts: list[tuple[float, float]] = []
    camera_count = len(angle_decisions)
    for ranges in (per_head, per_tail):
        if len(ranges) != camera_count:
            continue
        start = max(0.0, max(a for a, _ in ranges))
        end = min(b for _, b in ranges)
        if end - start >= review.MIN_EDGE_TRIM_SEC:
            cuts.append((start, end))
    return refine.merge_intervals(cuts)


def _remap(t: float, removals: list[tuple[float, float]], offset: float) -> float:
    """Map an original master time to its position in the final edit."""
    removed = 0.0
    for a, b in removals:
        if b <= t:
            removed += b - a
        elif a < t < b:
            removed += t - a
            break
        else:
            break
    return offset + (t - removed)


def check_sync(cfg: Config, log=print) -> dict:
    ffmpeg.require_ffmpeg()
    workdir = cfg.base_dir / cfg.out_dir / "_work"
    workdir.mkdir(parents=True, exist_ok=True)
    offsets = sync.compute(cfg, workdir, log=log)
    log("\nComputed offsets:")
    for k in sorted(offsets):
        log(f"  {k:<20} {offsets[k]:+.3f}s")
    return offsets


def run(cfg: Config, stages: set[str] | None = None, log=print) -> dict:
    ffmpeg.require_ffmpeg()
    stages = stages or {"assemble", "transcribe", "shorts"}
    out_dir = cfg.base_dir / cfg.out_dir
    workdir = out_dir / "_work"
    workdir.mkdir(parents=True, exist_ok=True)
    results: dict = {}

    # Growing editorial brain — nudge knobs from studied YouTube + human feedback.
    try:
        from .learning.apply import apply_priors_to_config
        apply_priors_to_config(cfg, log=log)
    except Exception as e:  # noqa: BLE001
        log(f"  (learning priors skipped: {e})")

    log("[1/7] Reviewing footage…")
    review_report, review_decisions = _review_sources(cfg, log=log)
    try:
        from .learning.apply import attach_learning_to_report
        review_report = attach_learning_to_report(review_report)
    except Exception:  # noqa: BLE001
        pass
    (out_dir / "review.json").write_text(json.dumps(review_report, indent=2))
    results["review"] = str(out_dir / "review.json")
    rotate_count = sum(1 for d in review_decisions.values() if d["rotate"] == 180)
    gain_count = sum(1 for a in cfg.mic_angles() if abs(a.audio_gain_db) >= 0.05)
    log(f"  applied {rotate_count} rotation and {gain_count} audio gain recommendation(s)")

    log("[2/7] Syncing sources…")
    if cfg.video_follows_audio:
        log("  video-follows-audio: pull each camera's embedded audio during this edit")
    offsets = sync.compute(cfg, workdir, log=log)
    (out_dir / "offsets.json").write_text(json.dumps(offsets, indent=2))
    review_removals = _consensus_review_trims(review_decisions, offsets)

    log("[3/7] Deciding camera switches…")
    # Envelopes + cut list are computed here in the same forge run — not a
    # separate preprocess. Embedded BRAW/MOV audio is extracted on the fly.
    env_db = _build_envelopes(cfg, offsets, workdir, log)
    segments, silent_mask = decide_segments(
        env_db, window_sec=cfg.window_sec, activation_db=cfg.activation_db,
        min_shot_sec=cfg.min_shot_sec, overlap_to_wide=cfg.overlap_to_wide,
        wide_name=cfg.wide, fallback=cfg.fallback,
        relative_db=cfg.relative_activation_db,
        switch_margin_db=cfg.switch_margin_db)
    if cfg.video_follows_audio:
        log(f"  video-follows-audio cut list · {len(segments)} shots "
            f"(min {cfg.min_shot_sec:g}s)")
    else:
        log(f"  {len(segments)} raw shots")

    log("[4/7] Mixing master audio…")
    mics = cfg.mic_angles()
    master_audio = workdir / "master.wav"
    if cfg.video_follows_audio:
        log(f"  mixing embedded audio from {len(mics)} camera(s)")
    titles.mix_master_audio(
        [cfg.resolve(m.mic) for m in mics],
        [offsets.get(_mic_id(m.name), 0.0) for m in mics], master_audio,
        gains_db=[m.audio_gain_db for m in mics])

    log("[5/7] Transcribing + smoothing…")
    transcript = transcribe.Transcript()
    want_tx = cfg.transcribe_enabled and (
        cfg.refine_fillers or cfg.refine_pauses or cfg.shorts_enabled
        or "transcribe" in stages)
    if want_tx:
        try:
            transcript = transcribe.transcribe(master_audio, cfg.whisper_model)
            log(f"  transcript: {len(transcript.words)} words, "
                f"{len(transcript.cues)} caption lines")
        except transcribe.WhisperUnavailable as e:
            log(f"  (skipped transcript) {e}")

    removals: list[tuple[float, float]] = list(review_removals)
    if transcript.words and (cfg.refine_fillers or cfg.refine_pauses):
        removals += refine.build_removals(
            transcript.words, cfg.refine_fillers, cfg.filler_words or None,
            cfg.refine_pauses, cfg.pause_sec, cfg.pause_keep_pad_sec)
    if cfg.silence_remove:
        removals += silence.silent_cut_intervals(
            silent_mask, cfg.window_sec, cfg.silence_min_gap_sec,
            cfg.silence_keep_pad_sec)
    removals = refine.merge_intervals(removals)
    if removals:
        segments = silence.subtract_intervals(segments, removals)
        cut = sum(b - a for a, b in removals)
        log(f"  trimmed {len(removals)} reviewed/filler/pause spots ({cut:.1f}s removed)")
    # Drop micro-fragments left by overlapping trims (avoids bad xfade budgets).
    segments = silence.prune_short_segments(segments, min_sec=0.12)
    (out_dir / "editlist.json").write_text(json.dumps(
        [{"start": s.start, "end": s.end, "angle": s.angle} for s in segments],
        indent=2))

    log("[6/7] Building intro / title / outro…")
    intro_paths: list[str] = []
    midroll_paths: list[str] = []
    if cfg.intro_video:
        intro_paths.append(cfg.resolve(cfg.intro_video))
    if cfg.title_text:
        card = titles.make_title_card(
            cfg.title_text, cfg.title_subtitle, workdir / "title.mp4",
            cfg.width, cfg.height, cfg.fps, cfg.title_duration)
        intro_paths.append(str(card))
    if cfg.sponsor_video:
        spot = cfg.resolve(cfg.sponsor_video)
        # Review-before-show: catch shake / music seams / dated cards; auto-fix when safe.
        try:
            from . import sponsor_qc
            sq = sponsor_qc.review_and_fix(spot, log=log)
            (out_dir / "qc_sponsor.json").write_text(
                __import__("json").dumps(sq, indent=2))
            if sq.get("verdict") == "fail":
                for rec in sq.get("recommendations", []):
                    log(f"  sponsor QC FAIL → {rec}")
            elif sq.get("recommendations"):
                for rec in sq.get("recommendations", []):
                    log(f"  sponsor QC note → {rec}")
        except Exception as e:  # noqa: BLE001
            log(f"  (sponsor QC skipped: {e})")
        place = str(getattr(cfg, "sponsor_placement", "midroll") or "midroll")
        if place in ("after_title", "pre", "intro"):
            intro_paths.append(spot)
            log(f"  sponsor spot (after title) ← {Path(spot).name}")
        else:
            midroll_paths.append(spot)
            log(f"  sponsor spot (midroll) ← {Path(spot).name}")
    outro_paths: list[str] = []
    if cfg.outro_video:
        outro_paths.append(cfg.resolve(cfg.outro_video))
    elif getattr(cfg, "outro_placeholder", True):
        from . import branding
        outro = branding.make_outro_placeholder(
            workdir / "outro.mp4",
            width=cfg.width, height=cfg.height, fps=cfg.fps,
            duration=5.0,
            show_name=cfg.title_text or cfg.project_name or "AUTOEDITING FORGE",
        )
        outro_paths.append(str(outro))
        log("  outro ← thanks-for-watching end card")
    intro_offset = sum(ffmpeg.probe_duration(p) for p in intro_paths)

    # Auto color-grade — shared by the straight edit and the operator path.
    grade_vf = None
    if cfg.grade:
        try:
            from . import grade as _grade
            _gsrc = cfg.resolve(cfg.angles[0].video)
            gp = _grade.analyze(_gsrc)
            grade_vf = _grade.ffmpeg_filter(gp)
            log(f"  auto color-grade (blacks {gp['black']:.2f}→0, whites {gp['white']:.2f}→1)")
            try:
                mid = max(1.0, ffmpeg.probe_duration(_gsrc) * 0.4)
                ffmpeg.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{mid:.2f}", "-i", _gsrc,
                            "-frames:v", "1", "-vf", "scale=560:-2", str(out_dir / "grade_before.jpg")])
                ffmpeg.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{mid:.2f}", "-i", _gsrc,
                            "-frames:v", "1", "-vf", f"{grade_vf},scale=560:-2",
                            str(out_dir / "grade_after.jpg")])
            except Exception:                          # noqa: BLE001
                pass
        except Exception as e:                         # noqa: BLE001
            log(f"  (grade skipped: {e})")

    long_form = out_dir / "episode.mp4"
    have_video = False
    if "assemble" in stages and cfg.operator_enabled:
        log("[7/7] AI Camera Operator…")
        src_angle = cfg.angles[0]
        src = cfg.resolve(src_angle.video)
        src_off = offsets.get(_vid_id(src_angle.name), 0.0)
        dur = ffmpeg.probe_duration(src)
        shots = operator.plan_shots(
            dur, transcript.cues or None,
            subject=(cfg.operator_x, cfg.operator_y),
            intensity=cfg.operator_intensity)
        shots = operator.subtract_from_shots(shots, removals)
        log(f"  {len(shots)} operated shots ({cfg.operator_intensity})")
        if cfg.operator_face:
            try:
                from . import facetrack
                ft = facetrack.track(src)
                cov = facetrack.coverage(ft)
                if cov > 0.04:
                    shots = operator.apply_facetrack(shots, ft)
                    log(f"  face-tracked framing — locked on subject ({cov*100:.0f}% coverage)")
                else:
                    log(f"  (no face found — centre framing)")
            except facetrack.FaceTrackUnavailable as e:
                log(f"  (face tracking unavailable: {e})")
        prepend = [p for p in intro_paths if p.endswith(".mp4")]
        intro_offset = sum(ffmpeg.probe_duration(p) for p in prepend)
        (out_dir / "editlist.json").write_text(json.dumps(
            [{"start": s.start, "end": s.end, "shot": s.kind} for s in shots], indent=2))
        face_track_for_resolve = None
        if cfg.backend == "resolve" and cfg.operator_face and 'ft' in locals():
            face_track_for_resolve = ft
        if cfg.backend == "resolve":
            from . import resolve_backend
            res = resolve_backend.build_operator(
                cfg, src, src_off, str(master_audio), shots, long_form,
                log=log, render=cfg.render, prepend=prepend,
                face_track=face_track_for_resolve)
            results["resolve"] = res
            if res.get("rendered"):
                found = [p for p in sorted(out_dir.glob("episode*.*"),
                         key=lambda p: p.stat().st_mtime, reverse=True)
                         if p.suffix.lower() != ".srt"]
                if found:
                    long_form, have_video = found[0], True
        else:
            assemble.render_operator(cfg, src, src_off, str(master_audio), shots,
                                     workdir, long_form, log=log, prepend=prepend,
                                     grade_vf=grade_vf)
            have_video = True
    elif "assemble" in stages:
        log("[7/7] Assembling…")
        if cfg.backend == "resolve":
            from . import resolve_backend
            res = resolve_backend.build_and_render(
                cfg, segments, offsets, str(master_audio), long_form, log=log,
                render=cfg.render, intro_paths=intro_paths, outro_paths=outro_paths)
            results["resolve"] = res
            if res.get("rendered"):
                found = [p for p in sorted(out_dir.glob("episode*.*"),
                         key=lambda p: p.stat().st_mtime, reverse=True)
                         if p.suffix.lower() != ".srt"]
                if found:
                    long_form, have_video = found[0], True
        else:
            assemble.render(cfg, segments, offsets, workdir, long_form, log=log,
                            grade_vf=grade_vf,
                            prepend=intro_paths, append=outro_paths,
                            midroll=midroll_paths)
            have_video = True
    results["long_form"] = str(long_form) if have_video else None

    if transcript.cues and "transcribe" in stages:
        transcribe.write_srt(transcript.cues, out_dir / "episode.srt")
        results["srt"] = str(out_dir / "episode.srt")

    if "shorts" in stages and cfg.shorts_enabled and have_video and transcript.cues:
        log("Making shorts…")
        hls = shorts.pick_highlights(
            transcript.cues, cfg.shorts_min_sec, cfg.shorts_max_sec, cfg.shorts_count)
        made = []
        for n, hl in enumerate(hls, 1):
            # Map highlight to the edited timeline (removals + intro offset).
            hl.start = _remap(hl.start, removals, intro_offset)
            hl.end = _remap(hl.end, removals, intro_offset)
            for c in hl.cues:
                c.start = _remap(c.start, removals, intro_offset)
                c.end = _remap(c.end, removals, intro_offset)
            out = shorts.render_short(cfg, Path(long_form), hl,
                                      out_dir / "shorts" / f"short_{n:02d}.mp4",
                                      workdir, cfg.shorts_captions)
            made.append(str(out))
            log(f"  short {n}/{len(hls)}")
        results["shorts"] = made
    elif cfg.backend == "resolve" and not have_video:
        log("  (timeline built — set output.render: true to also export + make shorts)")

    # Post-edit vision QC (Ollama) — never blocks delivery on failure/skip.
    if have_video and Path(long_form).exists():
        try:
            from autoedit import vision as vision_mod
            qc = review.qc_finished_edit(
                str(long_form), **vision_mod.settings_from_config(cfg), log=log)
            qc_path = out_dir / "qc_vision.json"
            qc_path.write_text(json.dumps(qc, indent=2))
            results["qc_vision"] = str(qc_path)
            if qc.get("skipped"):
                if qc.get("required_failed"):
                    log(f"  vision QC engine not ready: {qc.get('skip_reason')}")
                else:
                    log(f"  (vision QC skipped) {qc.get('skip_reason')}")
            else:
                log(f"  vision QC: {qc.get('verdict', 'unknown')}")
        except Exception as e:  # noqa: BLE001
            log(f"  vision QC error: {e}")

    # Learning brain — expose rate-me path + remind if daily study is due
    try:
        from .learning.daily import due_for_daily
        from .learning.apply import attach_learning_to_report
        from .learning.store import load_store
        learn_doc = attach_learning_to_report({
            "episode": str(long_form) if have_video else None,
            "rate_command": (
                f'python -m autoedit.learning rate "{long_form}" <SCORE> '
                f'--category general --notes "…"'
                if have_video else None
            ),
            "rating_scale": "-1 bad … 20 perfect (target 18+)",
        })
        (out_dir / "learning.json").write_text(json.dumps(learn_doc, indent=2))
        results["learning"] = str(out_dir / "learning.json")
        if due_for_daily(load_store()):
            log("  learning: daily study DUE — run: python -m autoedit.learning daily")
        if have_video:
            log("  learning: rate this edit -1…20 → "
                f'python -m autoedit.learning rate "{long_form}" 16')
    except Exception as e:  # noqa: BLE001
        log(f"  (learning summary skipped: {e})")

    log("\nDone.")
    return results
