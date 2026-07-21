# Auto Edit Forge — START HERE (handoff for Cursor)

**What this is:** a **fully automated video editor** for YouTube/podcast content. Point it at footage → it reviews the clips, removes ums/dead air, adds titles/transitions/fades/shorts, and delivers a finished episode. The UI is branded **EDITING FORGE**.

## The golden rule (do not break)
This tool does **EDITORIAL work only** — cut, pace, titles, transitions, audio, shorts.
It must **NOT** color-grade and must **NOT** reframe/crop/punch-in/face-track. The footage's **look and framing are kept exactly as shot** (a separate studio system owns camera work + LUT/color). The only picture fix allowed is **rotating upside-down footage 180°**. (`grade.py`, `operator.py`, `facetrack.py` exist but are intentionally OFF/unused.)

## Layout
```
autoedit/              core engine (pure Python)
  review.py            ⭐ Footage Review — analyzes clips BEFORE editing (audio loudness, orientation, black/dead, content)
  pipeline.py          orchestrates all stages: sync→cuts→mix→transcribe→refine→titles→assemble→shorts
  config.py            YAML -> Config dataclass (all the knobs)
  sync.py audiotools.py switch.py   multicam sync + loudness-based cutting
  transcribe.py refine.py silence.py  whisper + filler/pause/silence removal
  titles.py textgen.py  Pillow-rendered title/ending cards (this ffmpeg has no drawtext)
  assemble.py          ffmpeg render: cross-dissolves, fade in/out, 180° rotate, audio normalize -14 LUFS
  resolve_backend.py   DaVinci Resolve 21 build+render (reads BRAW natively)
  shorts.py            vertical 9:16 shorts with burned-in captions
  ingest.py            auto-watch recording folders / plugged-in SSDs
  operator.py facetrack.py grade.py   PRESENT BUT UNUSED (see golden rule)
  models/yunet.onnx    face detector (orientation + operator)
ui/
  index.html           EDITING FORGE web UI (single self-contained file, ember/forge look)
  server.py            Flask app driving the pipeline (127.0.0.1:8765)
  Open Auto Edit.command   double-click launcher
edit.py                CLI entry: `python edit.py project.yaml`
selftest.py            unit tests
config.example.yaml    example project config
requirements.txt       deps
context_docs/          full architecture/context notes — READ THESE
context_docs/obsidian/ LIVING MEMORY (wanted vs not okay, HPM sponsor lock, review-before-show, learning)
autoedit/sponsor_qc.py QC gate for sponsor spots — run/fix BEFORE showing the human
autoedit/learning/     MAJOR subsystem — daily YouTube curricula, ratings -1..20, never-again memory
data/learning/         store.json + daily journals (priors, refs, ratings, dislikes)
scripts/daily_learning.command   + launchd plist — run learning every day
helper_scripts/        Resolve/BRAW helper tools
```

## Environment gotchas (important — see context_docs/Environment & Gotchas.md)
- **ffmpeg** here is a minimal build: has libx264, xfade, acrossfade, fade, afade, loudnorm, ebur128, blackdetect — but **NO drawtext/subtitles/libass** (that's why titles/captions are Pillow PNGs). It **cannot read .braw** (use Resolve).
- **DaVinci Resolve Studio 21 must be OPEN** to use the Resolve backend (BRAW). Prefs → System → General → External scripting = Local.
- **OpenCV 5** (opencv-python-headless): use `cv2.FaceDetectorYN` (CascadeClassifier removed).
- Optional local vision: **Ollama** with the `moondream` model (review's semantic layer; everything works without it).
- The original dev folder name contained a `$` and spaces — rename to something clean like `auto-edit-forge/` when you import into Cursor.

## Run it
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt   # + optionally: faster-whisper, opencv-python-headless, flask, pillow
# UI:
.venv/bin/python ui/server.py               # then open http://127.0.0.1:8765
# or CLI:
.venv/bin/python edit.py config.example.yaml
# tests:
.venv/bin/python selftest.py
```

## Roadmap (see context_docs/Roadmap & Rules.md)
Wire review→edit auto-fixes, cold-open hook, b-roll music, styled captions, chapters, retention pacing, social package. **Never re-add color grade or reframing.**
