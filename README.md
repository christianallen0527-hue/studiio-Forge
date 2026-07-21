# AUTOEDITING FORGE

A free, fully-automated multi-camera podcast editor. You give it your separately
recorded camera angles + one microphone per person, and it produces:

- **`episode.mp4`** — the finished long-form episode, automatically cutting to
  whoever is talking (and to a wide shot during cross-talk / silence).
- **`shorts/short_01.mp4 …`** — vertical (9:16) clips of the best moments, with
  burned-in captions.
- **`episode.srt`** — captions for the full episode.
- **`editlist.json` / `offsets.json`** — a record of every edit decision (handy
  for your own UI to read).

It uses only free tools (ffmpeg + optional faster-whisper). No subscriptions.

---

## What's already set up on this Mac

I've already done these for you:

- ✅ Installed **ffmpeg** (the free video engine).
- ✅ Created a Python environment at `.venv/` with the required libraries.

You do **not** need to repeat those. Skip to "Edit one episode" below.

---

## Two engines (pick in `project.yaml` → `output.backend`)

| | `resolve` (recommended for you) | `ffmpeg` (free fallback) |
|---|---|---|
| Reads Blackmagic RAW (.braw)? | ✅ yes, natively | ❌ no — needs ProRes/H.264 |
| Cost | uses your Resolve Studio | free |
| Output | editable Resolve timeline + optional render | finished mp4 directly |
| Runs headless? | needs Resolve open | fully headless |

**Resolve backend — one-time setup:** open DaVinci Resolve, then set
**Preferences → System → General → "External scripting using" → Local**, and
**Save**. That security switch lets the tool drive Resolve. Then:

- `output.render: false` → builds the timeline so you can **review/tweak it in
  Resolve** before rendering (safest).
- `output.render: true` → also renders locally to `out/episode.*`.

## How to record so it works (important)

The automatic camera-switching decides who to show by listening to **each
person's own microphone**. So:

1. **One mic per person**, each recorded to its **own file** (host.wav,
   guest.wav, …). This is the single most important rule.
2. **Codec depends on your engine.** With the **resolve** backend, Blackmagic
   RAW (.braw) works natively — record however you like. With the **ffmpeg**
   backend, record ProRes/H.264 (ffmpeg can't read `.braw`).
3. **Remote Zoom guest:** in Zoom, turn on *"Record a separate audio file of
   each participant."* That gives the guest their own clean mic track. Drop their
   video + audio in as another angle.
4. A **wide/room camera** (no mic) is optional but recommended — it's used when
   two people talk at once or during pauses.

---

## Edit one episode

**1. Make a project folder** with your files, e.g. on the Desktop:

```
my-episode/
  raw/
    cam_host.mov     mic_host.wav
    cam_cohost.mov   mic_cohost.wav
    cam_guest.mov    mic_guest.wav
    cam_wide.mov
```

**2. Copy the example config** into that folder and rename it `project.yaml`,
then edit the file paths to match your files. The example is
`config.example.yaml` (well commented).

**3. Run it.** Open Terminal and paste:

```bash
cd "/Users/studio/Desktop/auto-edit-forge"
./.venv/bin/python edit.py "/Users/studio/Desktop/my-episode/project.yaml"
```

When it finishes, your `episode.mp4` and `shorts/` are inside
`my-episode/out/`.

---

## Turning on transcripts + shorts

Captions and shorts need one extra free piece (a local speech-to-text engine).
Install it once:

```bash
cd "/Users/studio/Desktop/auto-edit-forge"
./.venv/bin/pip install faster-whisper
```

After that, every run also produces `episode.srt` and the vertical `shorts/`.
(Without it, the tool still makes the full `episode.mp4` — it just skips
captions and shorts.)

---

## Calling it from your own UI

`edit.py` is designed to be run as a command by another program:

- **Progress messages** go to **stderr**.
- A **JSON result** (paths to the finished files) is printed to **stdout**.
- **Exit codes:** `0` = success, `1` = processing error, `2` = bad config.

Example result on stdout:

```json
{
  "long_form": "/…/out/episode.mp4",
  "srt": "/…/out/episode.srt",
  "shorts": ["/…/out/shorts/short_01.mp4", "…"]
}
```

Run only part of the pipeline with `--only` (e.g. long-form now, shorts later):

```bash
./.venv/bin/python edit.py project.yaml --only assemble
./.venv/bin/python edit.py project.yaml --only transcribe,shorts
```

---

## Tuning the edit (in `project.yaml`)

| Setting | What it does |
|---|---|
| `switch.min_shot_sec` | Minimum time on one camera before it's allowed to cut again (raise it if cuts feel too fast). |
| `switch.activation_db` | How loud a mic must be to count as "talking" (raise toward `-25` in a noisy room). |
| `switch.overlap_to_wide` | Cut to the wide shot when two+ people talk at once. |
| `switch.fallback` | During silence: show `wide`, or `hold` on the last camera. |
| `silence.remove: true` | Also automatically cut long dead-air gaps. |
| `shorts.count / min_sec / max_sec` | How many shorts and how long. |

---

## Cinematic touches & smoothing

The pipeline does more than switch cameras — it hand-builds a polished edit:

- **Title card** — set `title.text` / `title.subtitle` for a clean fading title at the
  front. (Rendered with Pillow, so it works even on a minimal ffmpeg.)
- **Intro / outro** — point `intro.video` / `outro.video` at pre-made branded clips
  and they bookend the episode. *(They must contain an audio track — even silent —
  so the mix stays aligned.)*
- **Filler-word removal** — `refine.remove_fillers` cuts "um / uh / er …". The word
  list is in the config; `and / so / like / you know` are included but flagged as
  aggressive — trim the list if the result feels choppy.
- **Pause tightening** — `refine.remove_pauses` closes gaps longer than `pause_sec`,
  leaving a small breath (`keep_pad_sec`).
- **Shorts with captions** — highlight clips are cropped 9:16 with burned-in captions
  (also Pillow-rendered), and their timing is remapped to match the trimmed edit.

Filler/pause removal and captions need **faster-whisper** and **Pillow**
(`./.venv/bin/pip install faster-whisper Pillow` — already installed on this Mac).

## If the cameras/mics look out of sync

The tool auto-aligns everything by audio. To see what it computed:

```bash
./.venv/bin/python edit.py project.yaml --check-sync
```

If one source is off, set a manual nudge in `project.yaml`:

```yaml
sync:
  manual_offsets:
    vid:guest: 0.20     # shift the guest camera 0.2s
    mic:guest: 0.20
```

---

## Notes & limits

- **BRAW isn't supported directly** — record/export ProRes or H.264 (see above).
- Auto-switching is **loudness-based**: it needs isolated mics. One shared mic
  can't be split into people.
- Shorts are chosen by a simple transcript heuristic (length + questions +
  content). It's a solid first pass, not a viral-prediction model — you can
  hand-pick from `editlist.json` timestamps too.
- Everything runs on your Mac; nothing is uploaded anywhere.

## For developers

- Core edit math is unit-tested without any media: `./.venv/bin/python selftest.py`.
- Package layout: `autoedit/{config,sync,audiotools,switch,silence,assemble,transcribe,shorts,pipeline}.py`, CLI in `edit.py`.
