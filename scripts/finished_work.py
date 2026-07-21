#!/usr/bin/env python3
"""Assemble a finished edit entirely in DaVinci Resolve and render to mp4:

    TITLE card  →  operated test footage (AI operator punch-ins)  →  [BRAW clips]  →  ENDING card

BRAW clips (with their own audio) are folded in when present. Output goes to the
Desktop as the given name. Everything — cuts, punch-ins, render — is Resolve.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault(
    "RESOLVE_SCRIPT_API",
    "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting")
os.environ.setdefault(
    "RESOLVE_SCRIPT_LIB",
    "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autoedit import ffmpeg, operator, refine, titles, transcribe   # noqa: E402
from autoedit.resolve_backend import _clip_fps, connect             # noqa: E402

TEST = "/Users/studio/Movies/AUTOEDITING FORGE Inbox/practice-obs/cam_main.mp4"
BRAW: list[str] = []            # filled from argv; each plays its first PORTION secs
BRAW_PORTION = 12
OUT_DIR = "/Users/studio/Desktop"
OUT_NAME = "finished work"
TITLE = ("AUTOEDITING FORGE", "The Fully Automated Studio")
ENDING = ("AUTOEDITING FORGE", "The Fully Automated Studio")
W, H, FPS = 1920, 1080, 30
WORK = Path("/tmp/finished_work"); WORK.mkdir(exist_ok=True)


def log(m): print(m, flush=True)


def main():
    BRAW.extend(a for a in sys.argv[1:] if a.lower().endswith(".braw"))

    log("• master audio + transcript…")
    master = titles.mix_master_audio([TEST], [0.0], WORK / "master.wav")
    tr = transcribe.transcribe(str(master), "base")
    dur = ffmpeg.probe_duration(TEST)
    shots = operator.plan_shots(dur, tr.cues or None, intensity="dynamic")
    rem = (refine.build_removals(tr.words, True, None, True, 0.6, 0.15)
           if tr.words else [])
    shots = [s for s in operator.subtract_from_shots(shots, rem)
             if s.end - s.start > 0.05]
    log(f"  {len(tr.words)} words · {len(shots)} operated shots · "
        f"{sum(b - a for a, b in rem):.1f}s trimmed · {len(BRAW)} BRAW clips")

    log("• title + ending cards…")
    title = titles.make_title_card(*TITLE, WORK / "title.mp4", W, H, FPS, 3.0)
    ending = titles.make_title_card(*ENDING, WORK / "ending.mp4", W, H, FPS, 3.0)

    log("• building Resolve timeline…")
    r = connect(); pm = r.GetProjectManager(); pm.SaveProject()
    proj = (pm.CreateProject("finished_work") or pm.LoadProject("finished_work")
            or pm.GetCurrentProject())
    proj.SetSetting("timelineFrameRate", str(FPS))
    proj.SetSetting("timelineResolutionWidth", str(W))
    proj.SetSetting("timelineResolutionHeight", str(H))
    mp = proj.GetMediaPool(); st = r.GetMediaStorage()
    st.AddItemListToMediaPool(list(dict.fromkeys(
        [TEST, str(master), str(title), str(ending), *BRAW])))

    def allc(f):
        cs = list(f.GetClipList() or [])
        for s in (f.GetSubFolderList() or []):
            cs += allc(s)
        return cs
    by = {Path(it.GetClipProperty("File Path")).name: it
          for it in allc(mp.GetRootFolder()) if it.GetClipProperty("File Path")}

    def item(p):
        it = by.get(Path(p).name)
        if not it:
            raise SystemExit("Resolve did not import: " + p)
        return it

    tl = mp.CreateEmptyTimeline("finished_work_edit"); proj.SetCurrentTimeline(tl)
    sfps = _clip_fps(item(TEST), FPS)
    ci = [{"mediaPoolItem": item(str(title))}]
    for s in shots:
        d = s.end - s.start
        ci.append({"mediaPoolItem": item(TEST), "mediaType": 1, "trackIndex": 1,
                   "startFrame": int(round(s.start * sfps)),
                   "endFrame": int(round((s.start + d) * sfps)) - 1})
        ci.append({"mediaPoolItem": item(str(master)), "mediaType": 2, "trackIndex": 1,
                   "startFrame": int(round(s.start * FPS)),
                   "endFrame": int(round((s.start + d) * FPS)) - 1})
    for b in BRAW:
        it = item(b); bfps = _clip_fps(it, FPS)
        ci.append({"mediaPoolItem": it, "startFrame": 0,
                   "endFrame": int(round(BRAW_PORTION * bfps)) - 1})
    ci.append({"mediaPoolItem": item(str(ending))})
    mp.AppendToTimeline(ci)

    vs = tl.GetItemListInTrack("video", 1) or []
    for it, s in zip(vs[1:1 + len(shots)], shots):     # zoom only the operated shots
        z = round(1.0 / max(0.34, s.zoom), 4)
        it.SetProperty("ZoomX", z); it.SetProperty("ZoomY", z)
    log(f"  {len(vs)} clips on the timeline")

    log("• rendering mp4 to Desktop…")
    ok = proj.SetCurrentRenderFormatAndCodec("mp4", "H264")
    if not ok:
        log("  (mp4/H264 not set; formats: %s)" % proj.GetRenderFormats())
    proj.DeleteAllRenderJobs()
    proj.SetRenderSettings({"TargetDir": OUT_DIR, "CustomName": OUT_NAME,
                            "SelectAllFrames": True})
    proj.AddRenderJob(); proj.StartRendering(isInteractiveMode=False)
    while proj.IsRenderingInProgress():
        time.sleep(2)
    out = Path(OUT_DIR) / f"{OUT_NAME}.mp4"
    log(f"✓ rendered: {out}" if out.exists() else f"! render finished but {out} not found")


if __name__ == "__main__":
    main()
