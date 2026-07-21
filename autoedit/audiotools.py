"""Audio math: loudness envelopes and cross-correlation sync.

Pure numpy so it can be unit-tested without any media files (see selftest.py).
"""

from __future__ import annotations

import numpy as np


def rms_envelope(samples: np.ndarray, sr: int, window_sec: float) -> np.ndarray:
    """Return per-window RMS loudness of a mono signal.

    The result has one value per `window_sec` chunk of the input.
    """
    win = max(1, int(round(sr * window_sec)))
    n_windows = int(np.ceil(len(samples) / win))
    padded = np.zeros(n_windows * win, dtype=np.float32)
    padded[: len(samples)] = samples
    frames = padded.reshape(n_windows, win)
    return np.sqrt(np.mean(frames * frames, axis=1) + 1e-12)


def to_db(rms: np.ndarray) -> np.ndarray:
    """Convert linear RMS to dBFS (0 dB = full scale)."""
    return 20.0 * np.log10(np.maximum(rms, 1e-9))


def xcorr_lag(ref: np.ndarray, sig: np.ndarray, max_lag: int) -> int:
    """Sample lag D (in [-max_lag, max_lag]) that best aligns `sig` to `ref`.

    Definition: D maximises sum_n ref[n] * sig[n - D].  A positive D means
    `sig` is delayed relative to `ref` (its events happen D samples later), so
    to read reference-time m from sig you sample sig at time m + D.
    """
    ref = ref.astype(np.float64)
    sig = sig.astype(np.float64)
    ref = ref - ref.mean()
    sig = sig - sig.mean()
    n = len(ref) + len(sig)
    R = np.fft.rfft(ref, n)
    S = np.fft.rfft(sig, n)
    cc = np.fft.irfft(R * np.conj(S), n)  # circular cross-correlation
    max_lag = min(max_lag, len(sig) - 1, len(ref) - 1)
    pos = cc[: max_lag + 1]                # lags 0 .. +max_lag
    neg = cc[n - max_lag: n][::-1]         # lags -1 .. -max_lag
    best_pos = int(np.argmax(pos))
    best_neg = int(np.argmax(neg)) if len(neg) else -1
    if len(neg) == 0 or pos[best_pos] >= neg[best_neg]:
        return best_pos
    return -(best_neg + 1)


def find_offset_seconds(
    ref: np.ndarray, sig: np.ndarray, sr: int, max_offset_sec: float
) -> float:
    """Seconds to add to a reference time to read the same instant from `sig`.

    `xcorr_lag` returns the lag L maximising sum ref[n]*sig[n-L]; if `sig` is
    delayed by D (its events happen later), that peak is at L = -D. To read
    reference-time m we must sample `sig` at m + D, so the offset is -L.
    """
    max_lag = int(round(max_offset_sec * sr))
    return -xcorr_lag(ref, sig, max_lag) / float(sr)
