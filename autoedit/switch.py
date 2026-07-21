"""Speaker-driven camera switching (video-follows-audio).

Core rule: at each moment the loudest active mic decides which camera we show.
For podcasts where each camera has its own embedded audio, that track *is*
the mic — same algorithm.

Includes hysteresis (minimum shot length) so cuts stay smooth, optional
noise-floor-relative gating for embedded camera audio, plus a wide shot for
cross-talk and silence.

Pure — unit-tested in selftest.py without any media.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Segment:
    start: float          # seconds on the master timeline
    end: float
    angle: str            # angle name to show


def _noise_floor_db(env: list[float], percentile: float = 20.0) -> float:
    """Estimate room/noise floor from the quietest part of an envelope."""
    if not env:
        return -80.0
    ordered = sorted(float(x) for x in env)
    idx = int(len(ordered) * (percentile / 100.0))
    idx = max(0, min(idx, len(ordered) - 1))
    return ordered[idx]


def per_angle_thresholds(
    env_db: dict[str, list],
    activation_db: float = -35.0,
    relative_db: float | None = None,
) -> dict[str, float]:
    """Absolute dB gate per angle.

    When ``relative_db`` is set (podcast / embedded-cam audio), a mic must
    rise that many dB above its own noise floor — and never below the absolute
    ``activation_db`` floor — before it counts as talking.
    """
    out: dict[str, float] = {}
    for name, env in env_db.items():
        if relative_db is None:
            out[name] = activation_db
        else:
            out[name] = max(activation_db, _noise_floor_db(env) + relative_db)
    return out


def decide_segments(
    env_db: dict[str, list],
    window_sec: float,
    activation_db: float = -35.0,
    min_shot_sec: float = 1.5,
    overlap_to_wide: bool = True,
    wide_name: str | None = None,
    fallback: str = "wide",         # "wide" or "hold"
    relative_db: float | None = None,
    switch_margin_db: float = 0.0,
) -> tuple[list[Segment], list[bool]]:
    """Return (segments, silent_mask).

    `env_db` maps mic'd angle name -> per-window loudness in dB (master grid).
    `silent_mask[k]` is True when nobody was speaking in window k.

    ``switch_margin_db``: when already on a talking angle, require another
    talker to be this many dB louder before cutting (smooth podcast hold).
    """
    mic_angles = list(env_db.keys())
    if not mic_angles:
        raise ValueError("Need at least one angle with a mic.")
    k = min(len(v) for v in env_db.values())
    default_cam = wide_name or mic_angles[0]
    thresholds = per_angle_thresholds(env_db, activation_db, relative_db)

    raw: list[str | None] = []
    silent: list[bool] = []
    last_talker: str | None = None
    for i in range(k):
        talkers = [(name, env_db[name][i]) for name in mic_angles
                   if env_db[name][i] > thresholds[name]]
        if not talkers:
            silent.append(True)
            raw.append(None if fallback == "hold" else (wide_name or None))
        elif len(talkers) == 1:
            silent.append(False)
            pick = talkers[0][0]
            raw.append(pick)
            last_talker = pick
        else:
            silent.append(False)
            if overlap_to_wide and wide_name:
                raw.append(wide_name)
            else:
                loudest = max(talkers, key=lambda t: t[1])
                if (last_talker and switch_margin_db > 0
                        and any(n == last_talker for n, _ in talkers)):
                    held = next(lvl for n, lvl in talkers if n == last_talker)
                    if loudest[0] != last_talker and loudest[1] < held + switch_margin_db:
                        raw.append(last_talker)
                    else:
                        raw.append(loudest[0])
                        last_talker = loudest[0]
                else:
                    raw.append(loudest[0])
                    last_talker = loudest[0]

    # Carry the last real camera forward across "hold"/None windows.
    state: list[str] = []
    last = default_cam
    for cam in raw:
        if cam is None:
            state.append(last)
        else:
            state.append(cam)
            last = cam

    # Enforce a minimum shot length by merging too-short runs into a neighbour.
    min_bins = max(1, round(min_shot_sec / window_sec))
    runs = _to_runs(state)
    runs = _merge_short_runs(runs, min_bins)

    segments = [
        Segment(start=s * window_sec, end=e * window_sec, angle=cam)
        for (cam, s, e) in runs
    ]
    return segments, silent


def _to_runs(state: list[str]) -> list[tuple[str, int, int]]:
    """Collapse a per-bin list into (value, start_bin, end_bin) runs."""
    runs: list[tuple[str, int, int]] = []
    if not state:
        return runs
    cur, start = state[0], 0
    for i in range(1, len(state)):
        if state[i] != cur:
            runs.append((cur, start, i))
            cur, start = state[i], i
    runs.append((cur, start, len(state)))
    return runs


def _merge_short_runs(runs, min_bins):
    """Absorb runs shorter than min_bins into the previous run (or next)."""
    changed = True
    while changed and len(runs) > 1:
        changed = False
        for i, (cam, s, e) in enumerate(runs):
            if e - s >= min_bins:
                continue
            if i > 0:
                pcam, ps, _ = runs[i - 1]
                runs[i - 1] = (pcam, ps, e)
            else:
                ncam, _, ne = runs[i + 1]
                runs[i + 1] = (ncam, s, ne)
            del runs[i]
            changed = True
            break
    return runs
