#!/usr/bin/env python3
"""Self-tests for the pure-math core (no media files or ffmpeg needed).

Run:  python selftest.py
"""

from __future__ import annotations

import json

import numpy as np

from autoedit import assemble, audiotools, ingest, operator, pipeline, refine, review, silence, vision
from autoedit.switch import Segment, decide_segments
from autoedit.transcribe import Word


def test_offset_recovery():
    rng = np.random.default_rng(0)
    sr = 8000
    L = sr * 5
    ref = rng.standard_normal(L).astype(np.float32)
    D = 400  # samples => 0.05s; sig is `ref` delayed by D
    sig = np.zeros(L, dtype=np.float32)
    sig[D:] = ref[: L - D]
    off = audiotools.find_offset_seconds(ref, sig, sr, max_offset_sec=1.0)
    assert abs(off - D / sr) < 1e-3, f"expected {D/sr:.3f}s, got {off:.3f}s"
    print(f"  offset recovery: {off:+.3f}s  OK")


def test_switching_alternates():
    loud, quiet = -10.0, -80.0
    env = {
        "a": [loud] * 50 + [quiet] * 50,
        "b": [quiet] * 50 + [loud] * 50,
    }
    segs, silent = decide_segments(
        env, window_sec=0.1, activation_db=-35.0, min_shot_sec=0.5,
        overlap_to_wide=False, wide_name=None, fallback="hold")
    assert [s.angle for s in segs] == ["a", "b"], segs
    assert abs(segs[0].end - 5.0) < 0.11, segs[0].end
    assert not any(silent), "no window should be silent here"
    print(f"  switching alternates a->b at {segs[0].end:.1f}s  OK")


def test_overlap_to_wide_and_silence():
    loud, quiet = -10.0, -80.0
    env = {
        "a": [loud] * 30 + [quiet] * 40 + [loud] * 30,
        "b": [loud] * 30 + [quiet] * 40 + [quiet] * 30,
    }
    segs, silent = decide_segments(
        env, window_sec=0.1, activation_db=-35.0, min_shot_sec=0.5,
        overlap_to_wide=True, wide_name="wide", fallback="wide")
    assert segs[0].angle == "wide", "cross-talk should show wide"
    assert all(silent[30:70]), "middle should read as silence"
    assert segs[-1].angle == "a", segs[-1].angle
    print("  overlap->wide and silence detection  OK")


def test_video_follows_audio_relative_and_margin():
    """Embedded-cam podcast switching: noise-floor gate + hold margin."""
    # Cam A room tone ~-50, speech -12; cam B room -48, brief louder -8 mid-clip
    env = {
        "host":  [-50.0] * 40 + [-12.0] * 40 + [-50.0] * 40,
        "guest": [-48.0] * 40 + [-48.0] * 20 + [-8.0] * 20 + [-48.0] * 40,
    }
    segs, _ = decide_segments(
        env, window_sec=0.1, activation_db=-60.0, min_shot_sec=0.5,
        overlap_to_wide=False, wide_name=None, fallback="hold",
        relative_db=8.0, switch_margin_db=3.0)
    angles = [s.angle for s in segs]
    assert "host" in angles and "guest" in angles, angles
    # Relative gate must ignore room tone (absolute -50 would look "active" vs -60)
    segs_abs, silent = decide_segments(
        env, window_sec=0.1, activation_db=-60.0, min_shot_sec=0.5,
        overlap_to_wide=False, fallback="hold", relative_db=None)
    assert not all(silent[:40]), "absolute -60 would treat room as speech"
    segs_rel, silent_rel = decide_segments(
        env, window_sec=0.1, activation_db=-60.0, min_shot_sec=0.5,
        overlap_to_wide=False, fallback="hold", relative_db=8.0)
    assert all(silent_rel[:40]), "relative gate should treat room tone as silence"
    print("  video-follows-audio relative gate + margin  OK")


def test_silence_subtract():
    segs = [Segment(0.0, 10.0, "x")]
    out = silence.subtract_intervals(segs, [(4.0, 6.0)])
    spans = [(round(s.start, 2), round(s.end, 2)) for s in out]
    assert spans == [(0.0, 4.0), (6.0, 10.0)], spans
    print("  silence subtract splits segment  OK")


def test_filler_removal():
    words = [Word(0.0, 0.5, "Hello"), Word(0.6, 0.9, "um,"),
             Word(1.0, 1.5, "world"), Word(1.6, 1.9, "AND"),
             Word(2.0, 2.5, "welcome")]
    cuts = refine.filler_intervals(words, ["um", "and"])
    assert len(cuts) == 2, cuts
    assert abs(cuts[0][0] - 0.58) < 1e-6 and abs(cuts[0][1] - 0.92) < 1e-6, cuts
    print("  filler removal (um, and, case-insensitive)  OK")


def test_pause_removal():
    words = [Word(0.0, 1.0, "a"), Word(3.0, 4.0, "b")]   # 2s gap
    cuts = refine.pause_intervals(words, max_gap=0.6, keep_pad=0.15)
    assert len(cuts) == 1 and abs(cuts[0][0] - 1.15) < 1e-6, cuts
    assert abs(cuts[0][1] - 2.85) < 1e-6, cuts
    print("  pause removal keeps a small pad  OK")


def test_build_and_subtract():
    words = [Word(0.0, 0.5, "so"), Word(0.6, 1.0, "yeah")]
    rem = refine.build_removals(words, remove_fillers=True, fillers=["so"],
                                remove_pauses=False)
    out = silence.subtract_intervals([Segment(0.0, 2.0, "host")], rem)
    # "so" (0..0.52) cut -> first kept piece starts at 0.52
    assert out[0].start > 0.5 and out[-1].end == 2.0, [(s.start, s.end) for s in out]
    print("  build_removals + subtract integrates  OK")


def test_operator_plan():
    shots = operator.plan_shots(30.0, cues=None, intensity="dynamic")
    assert shots[0].start == 0.0 and shots[0].kind == "wide", "must establish wide"
    assert abs(shots[-1].end - 30.0) < 1e-6, "must cover full duration"
    for a, b in zip(shots, shots[1:]):
        assert abs(a.end - b.start) < 1e-6, "shots must be contiguous"
    assert len({s.kind for s in shots}) >= 2, "needs framing variety"
    assert all(s.end > s.start for s in shots)
    print(f"  operator plans {len(shots)} varied, contiguous shots  OK")


def test_operator_crop():
    s = operator.Shot(0, 4, "close", 0.56, 0.5, 0.44, 0.06)
    cw, ch, x, y = operator.crop_rect(s, 3840, 2160, at=0.0)
    assert cw % 2 == 0 and ch % 2 == 0, "even dims for yuv420p"
    assert 0 <= x <= 3840 - cw and 0 <= y <= 2160 - ch, "crop stays in frame"
    assert abs(cw - 3840 * 0.56) < 4, "close keeps ~56% width"
    cw2, _, _, _ = operator.crop_rect(s, 3840, 2160, at=1.0)   # after push
    assert cw2 < cw, "push tightens the frame over the shot"
    print("  operator crop rects are valid + push tightens  OK")


def test_ingest_sessions():
    from pathlib import Path
    mk = lambda name, mt: ingest.FoundFile(Path(name), 100, mt)
    files = [mk("a.mp4", 1000), mk("b.mp4", 1200), mk("c.mp4", 1500),
             mk("d.mp4", 1000 + 4 * 3600)]           # 4h later = new session
    groups = ingest.group_sessions(files, gap=1800)
    assert len(groups) == 2 and len(groups[0]) == 3 and len(groups[1]) == 1
    # Camera Forge session manifest helper
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        sess = Path(td) / "CAM1_test"
        sess.mkdir()
        (sess / "clip.braw").write_bytes(b"x")
        got = ingest.ensure_session_for_folder(sess, cam_id=1, log=lambda *_: None)
        assert got == sess
        mf = json.loads((sess / "session.json").read_text())
        assert mf["kind"] == "braw" and mf["engine"] == "resolve"
        assert mf["source"] == "camera-forge"
        assert mf["files"] == ["clip.braw"]
    print("  ingest groups recordings into sessions by time  OK")


def test_ingest_ledger(tmp="/tmp/_autoedit_ledger_test.json"):
    from pathlib import Path
    p = Path(tmp); p.unlink(missing_ok=True)
    led = ingest.Ledger.load(p)
    f = ingest.FoundFile(Path("/x/cam1.mp4"), 12345, 999.0)
    assert not led.seen(f)
    led.mark(f, "/inbox/cam1.mp4"); led.save()
    led2 = ingest.Ledger.load(p)
    assert led2.seen(f), "ledger must persist across loads"
    f2 = ingest.FoundFile(Path("/x/cam1.mp4"), 99999, 999.0)   # same path, new size
    assert not led2.seen(f2), "re-recorded file must count as new"
    p.unlink(missing_ok=True)
    print("  ingest ledger dedupes and persists  OK")


def test_review_decisions():
    decision = review.apply_review({
        "orientation": 180,
        "duration": 20.0,
        "audio_verdict": "quiet",
        "loudness_lufs": -30.0,
        "peak_db": -10.0,
        "black_ranges": [[0.0, 1.2], [5.0, 6.0], [19.0, 20.0], [8.0, 8.1]],
        "content": "talking",
    })
    assert decision["rotate"] == 180
    assert decision["audio_gain_db"] == 8.5, decision  # peak remains <= -1.5 dBFS
    assert decision["trim_ranges"] == [[0.0, 1.2], [19.0, 20.0]], decision
    assert review.apply_review({}) == {
        "rotate": 0, "audio_gain_db": 0.0, "trim_ranges": [], "add_music": False,
    }
    print("  review decisions are safe + edge-only  OK")


def test_review_trim_consensus():
    decisions = {
        "a": {"trim_ranges": [[0.0, 2.0], [98.0, 100.0]]},
        "b": {"trim_ranges": [[0.0, 2.5], [98.5, 101.0]]},
    }
    cuts = pipeline._consensus_review_trims(
        decisions, {"vid:a": 0.0, "vid:b": 0.5}
    )
    assert cuts == [(0.0, 2.0), (98.0, 100.0)], cuts
    decisions["b"]["trim_ranges"] = []
    assert pipeline._consensus_review_trims(decisions, {}) == []
    print("  review trims require all-camera consensus  OK")


def test_vision_json_repair_and_schema():
    assert vision.repair_json("") is None
    assert vision.repair_json("not json") is None
    fenced = '```json\n{"description": "host talking", "content": "talking"}\n```'
    parsed = vision.repair_json(fenced)
    assert parsed and parsed["content"] == "talking"
    trailing = '{"verdict": "good", "scores": {"overall": 0.9,},}'
    assert vision.repair_json(trailing)["verdict"] == "good"

    norm = vision.normalize_pre_edit({
        "content": "talking-head",
        "orientation": "inverted",
        "usable": "yes",
        "scores": {"sharpness": 1.5, "obstruction": 0.2, "confidence": "0.8"},
        "issues": [{"code": "Blurry", "detail": "soft", "confidence": 2, "severity": "extreme"}],
        "recommendations": [
            "Trim the blurry head",
            "Apply a cinematic color grade",  # forbidden — dropped
            "Punch-in on the face",           # forbidden — dropped
        ],
    })
    assert norm["content"] == "talking_head"
    assert norm["orientation"] == "upside_down"
    assert norm["usable"] is True
    assert norm["scores"]["sharpness"] == 1.0
    assert abs(norm["scores"]["obstruction_free"] - 0.8) < 1e-6
    assert abs(norm["scores"]["confidence"] - 0.8) < 1e-6
    assert norm["issues"][0]["code"] == "blurry"
    assert norm["issues"][0]["severity"] == "medium"
    assert norm["recommendations"] == ["Trim the blurry head"]

    qc = vision.normalize_qc({
        "verdict": "needswork",
        "scores": {"pacing": -1, "confidence": None},
        "issues": [{"code": "jump_cut", "detail": "hard join", "confidence": 0.7}],
        "recommendations": ["Re-cut the hard join"],
    })
    assert qc["verdict"] == "needs_work"
    assert qc["scores"]["pacing"] == 0.0
    assert qc["scores"]["confidence"] == 0.0
    assert qc["issues"][0]["code"] == "jump_cut"
    print("  vision JSON repair + schema defaults  OK")


def test_vision_sample_times_and_merge():
    assert vision.sample_times(10.0, 1) == [4.0]
    assert vision.sample_times(10.0, 3) == [2.5, 5.0, 7.5]

    clip = {
        "content": "talking",
        "usable": True,
        "orientation": 0,
        "orientation_note": "Upright (no face to confirm).",
        "flags": [],
        "recommendations": ["Clean at -14.0 LUFS."],
    }
    vis = {
        "ok": True, "skipped": False,
        "content": "broll",
        "orientation": "upside_down",
        "usable": True,
        "scores": {"confidence": 0.9},
        "issues": [{"code": "blurry", "detail": "soft focus", "confidence": 0.8, "severity": "high"}],
        "recommendations": ["Reject or trim soft frames."],
    }
    out = vision.merge_vision_into_review(dict(clip), vis)
    assert out["content"] == "broll"
    assert "vision" in out and out["vision"]["ok"] is True
    assert any("soft focus" in r or "Vision:" in r for r in out["recommendations"])
    assert any("vision upside-down" in f for f in out["flags"])
    assert "blurry" in out["flags"]
    # Deterministic orientation must stay 0 (vision only annotates)
    assert out["orientation"] == 0

    skipped = vision.review_visual("/no/such.mp4", enabled="off")
    assert skipped["skipped"] is True and skipped["ok"] is False
    assert skipped["skip_reason"] == "vision disabled"

    empty = vision.empty_qc(skipped=True, reason="ollama unavailable")
    assert empty["verdict"] == "unknown" and empty["skipped"] is True
    print("  vision sample times + merge + skip  OK")


def test_vision_enabled_resolution():
    assert vision.resolve_enabled(True) == "on"
    assert vision.resolve_enabled(False) == "off"
    assert vision.resolve_enabled("AUTO") == "on"   # auto → on (hardwired)
    assert vision.resolve_enabled(None) == "on"     # default on
    # Force-off via env for this check (tests only)
    import os
    prev = os.environ.get("AUTOEDIT_VISION")
    try:
        os.environ["AUTOEDIT_VISION"] = "0"
        assert vision.resolve_enabled(None) == "off"
        run, reason = vision.should_run_vision(None)
        assert run is False and reason == "vision disabled"
    finally:
        if prev is None:
            os.environ.pop("AUTOEDIT_VISION", None)
        else:
            os.environ["AUTOEDIT_VISION"] = prev
    # ensure_ollama is idempotent when the engine is already up
    st = vision.ensure_ollama(pull=False, wait_sec=5.0)
    assert "ok" in st and "available" in st
    print("  vision enablement resolution  OK")


def test_facetrack_framing():
    # Synthetic track: subject consistently at right side, upper third.
    track = [(float(t), 0.75, 0.35, 0.15, 0.18) for t in range(0, 12)]
    shots = operator.plan_shots(12.0, cues=None, intensity="dynamic")
    operator.apply_facetrack(shots, track)
    close = next(s for s in shots if s.kind in ("close", "punch"))
    assert close.cx > 0.6, f"framing should shift toward subject: {close.cx}"
    cw, ch, x, y = operator.crop_rect(close, 1920, 1080)
    assert x + cw / 2 > 1920 * 0.55, "crop must sit toward the subject's side"
    # No plausible faces -> safe fall back to centre-ish default (never worse)
    empty = [(float(t), None, None, None, None) for t in range(0, 12)]
    s2 = operator.plan_shots(12.0, cues=None, intensity="dynamic")
    operator.apply_facetrack(s2, empty)
    assert 0.3 < s2[1].cx < 0.7, "no face -> centred, not skewed"
    print("  face-track framing follows subject + safe fallback  OK")


def test_join_kinds_structural_vs_speech():
    # intro + title | body body body | outro
    kinds = assemble.join_kinds(n_pre=2, n_body=3, n_post=1)
    assert kinds == [
        "structural",  # intro → title
        "structural",  # title → body
        "speech",      # body → body
        "speech",
        "structural",  # body → outro
    ], kinds
    assert assemble.join_kinds(1, 0, 0) == []
    assert assemble.join_kinds(0, 1, 0) == []
    print("  join_kinds structural vs speech  OK")


def test_clamp_xfade_short_clips():
    # Old bug: forced 0.05 even when clips couldn't afford it.
    assert assemble.clamp_xfade(0.5, 0.04, 0.04, 0.04) == 0.0
    assert assemble.clamp_xfade(0.5, 2.0, 2.0, 2.0) == 0.5
    # Budget is 45% of the shortest side.
    t = assemble.clamp_xfade(0.5, 0.5, 2.0, 2.0)
    assert abs(t - 0.225) < 1e-6, t
    assert assemble.clamp_xfade(0.0, 5.0, 5.0, 5.0) == 0.0
    print("  clamp_xfade short-clip / budget  OK")


def test_plan_join_durations_speech_micro():
    durs = [4.0, 5.0, 3.0, 6.0]  # pre, body, body, post
    kinds = assemble.join_kinds(1, 2, 1)
    joins = assemble.plan_join_durations(
        durs, kinds,
        structural_sec=0.5,
        speech_video_sec=0.0,
        speech_audio_sec=0.04,
    )
    assert abs(joins[0] - 0.5) < 1e-6, joins   # structural pre→body
    assert abs(joins[1] - 0.04) < 1e-6, joins  # speech micro
    assert abs(joins[2] - 0.5) < 1e-6, joins   # structural body→post
    # Legacy dissolve-every-cut: raise speech_video_sec
    mush = assemble.plan_join_durations(
        durs, kinds,
        structural_sec=0.5,
        speech_video_sec=0.5,
        speech_audio_sec=0.04,
    )
    assert all(abs(j - 0.5) < 1e-6 for j in mush), mush
    print("  plan_join_durations speech micro vs structural  OK")


def test_clamp_program_fades():
    assert assemble.clamp_program_fades(0.5, 30.0) == 0.5
    assert assemble.clamp_program_fades(0.5, 0.9) == 0.3  # total/3
    assert assemble.clamp_program_fades(0.5, 0.0) == 0.0
    print("  clamp_program_fades  OK")


def test_prune_short_segments():
    segs = [
        Segment(0.0, 2.0, "a"),
        Segment(2.0, 2.05, "a"),   # too short
        Segment(3.0, 5.0, "b"),
    ]
    out = silence.prune_short_segments(segs, min_sec=0.12)
    assert [(s.start, s.end, s.angle) for s in out] == [
        (0.0, 2.0, "a"), (3.0, 5.0, "b")
    ]
    print("  prune_short_segments  OK")


if __name__ == "__main__":
    test_facetrack_framing()
    test_review_decisions()
    test_review_trim_consensus()
    test_vision_json_repair_and_schema()
    test_vision_sample_times_and_merge()
    test_vision_enabled_resolution()
    test_offset_recovery()
    test_switching_alternates()
    test_overlap_to_wide_and_silence()
    test_video_follows_audio_relative_and_margin()
    test_silence_subtract()
    test_filler_removal()
    test_pause_removal()
    test_build_and_subtract()
    test_operator_plan()
    test_operator_crop()
    test_ingest_sessions()
    test_ingest_ledger()
    test_join_kinds_structural_vs_speech()
    test_clamp_xfade_short_clips()
    test_plan_join_durations_speech_micro()
    test_clamp_program_fades()
    test_prune_short_segments()
    print("\nAll core self-tests passed.")
