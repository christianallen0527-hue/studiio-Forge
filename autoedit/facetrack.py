"""Face tracking for cinematic framing (OpenCV YuNet DNN).

Samples the source video, follows the dominant face, and returns a normalized
position timeline. The operator uses this to frame every punch-in ON the person
— with rule-of-thirds headroom — instead of the centre of the frame.

Degrades gracefully: if OpenCV or the model is missing, the caller falls back to
centre framing.
"""

from __future__ import annotations

import os
import statistics

_MODEL_CANDIDATES = [
    os.path.join(os.path.dirname(__file__), "models", "yunet.onnx"),
    os.path.expanduser("~/Movies/yunet.onnx"),
]


class FaceTrackUnavailable(RuntimeError):
    pass


def _model_path() -> str:
    for p in _MODEL_CANDIDATES:
        if os.path.exists(p):
            return p
    raise FaceTrackUnavailable("yunet.onnx model not found")


def track(video_path, sample_hz: float = 4.0, conf: float = 0.4,
          det_width: int = 704) -> list:
    """Return [(t, cx, cy, fw, fh), …] with normalized face positions.

    Entries where no face was found have cx=None. Detection runs on downscaled
    frames for speed; normalized coordinates are resolution-independent.
    """
    try:
        import cv2
    except ImportError as e:                          # noqa: BLE001
        raise FaceTrackUnavailable("opencv not installed") from e

    model = _model_path()
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise FaceTrackUnavailable(f"cannot open {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1920
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1080
    dw = min(det_width, W)
    dh = int(round(H * dw / W))
    det = cv2.FaceDetectorYN.create(model, "", (dw, dh), score_threshold=conf)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))

    step = max(1, int(round(fps / sample_hz)))
    out: list = []
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if i % step == 0:
            small = cv2.resize(frame, (dw, dh))
            # Lift contrast on the luminance — helps backlit / washed-out footage.
            lab = cv2.cvtColor(small, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            small = cv2.cvtColor(cv2.merge((clahe.apply(l), a, b)), cv2.COLOR_LAB2BGR)
            _, faces = det.detect(small)
            t = i / fps
            # Keep only plausible faces: sane size + head-like aspect ratio +
            # both eyes present (YuNet landmarks). Rejects skin/background hits.
            cands = []
            for f in (faces if faces is not None else []):
                w, h = float(f[2]), float(f[3])
                if h <= 0 or w <= 0:
                    continue
                fhn, ar = h / dh, w / h
                eyes_ok = float(f[14]) > 0.7 if len(f) > 14 else True
                if 0.05 <= fhn <= 0.32 and 0.55 <= ar <= 1.25 and eyes_ok:
                    cands.append(f)
            if cands:
                f = max(cands, key=lambda r: r[2] * r[3])
                x, y, w, h = float(f[0]), float(f[1]), float(f[2]), float(f[3])
                out.append((t, (x + w / 2) / dw, (y + h / 2) / dh, w / dw, h / dh))
            else:
                out.append((t, None, None, None, None))
        i += 1
    cap.release()
    return out


def coverage(track_list) -> float:
    """Fraction of samples where a face was found (0..1)."""
    if not track_list:
        return 0.0
    hits = sum(1 for r in track_list if r[1] is not None)
    return hits / len(track_list)


def subject_for(track_list, t0: float, t1: float,
                default=(0.5, 0.42)) -> tuple:
    """Median (cx, cy, face_height) of faces within [t0, t1].

    Falls back to the whole-clip median, then to `default` if no face was ever
    seen. Median (not mean) rejects the odd false-positive detection.
    """
    def med(pts):
        return (statistics.median(p[0] for p in pts),
                statistics.median(p[1] for p in pts),
                statistics.median(p[2] for p in pts))

    span = [(cx, cy, fh) for (t, cx, cy, fw, fh) in track_list
            if cx is not None and t0 - 0.3 <= t <= t1 + 0.3]
    if span:
        return med(span)
    allp = [(cx, cy, fh) for (t, cx, cy, fw, fh) in track_list if cx is not None]
    if allp:
        return med(allp)
    return (default[0], default[1], 0.2)
