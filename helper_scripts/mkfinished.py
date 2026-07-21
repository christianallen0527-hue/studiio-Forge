#!/usr/bin/env python3
# Self-contained finished-edit render (runs outside the Desktop TCC block).
# TITLE -> operated test footage (Resolve zoom punch-ins) -> [BRAW] -> ENDING, rendered to Desktop as mp4.
import os, sys, time, json, subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

TEST = "/Users/studio/Movies/AUTOEDITING FORGE Inbox/practice-obs/cam_main.mp4"
BRAW = [a for a in sys.argv[1:] if a.lower().endswith(".braw")]   # optional
BRAW_PORTION = 12
OUT_DIR = "/Users/studio/Desktop"; OUT_NAME = "finished work"
W, H, FPS = 1920, 1080, 30
WORK = Path("/Users/studio/Movies/_finished_work_tmp"); WORK.mkdir(exist_ok=True)
FF = "/opt/homebrew/bin/ffmpeg"; FP = "/opt/homebrew/bin/ffprobe"
FB = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
FR = "/System/Library/Fonts/Supplemental/Arial.ttf"

def run(c): subprocess.run(c, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
def dur(p):
    o = subprocess.run([FP, "-v", "error", "-show_entries", "format=duration",
                        "-of", "json", p], capture_output=True, text=True)
    return float(json.loads(o.stdout)["format"]["duration"])

def card(title, sub, out, d=3.0, fade=0.6):
    img = Image.new("RGB", (W, H), (10, 10, 10)); dr = ImageDraw.Draw(img)
    tf = ImageFont.truetype(FB, int(H*0.09)); sf = ImageFont.truetype(FR, int(H*0.036))
    bb = dr.textbbox((0, 0), title, font=tf)
    dr.text(((W-(bb[2]-bb[0]))/2, H/2-(bb[3]-bb[1])-int(H*0.015)), title, font=tf, fill=(245, 245, 245))
    dr.rectangle([W/2-40, H/2+int(H*0.005), W/2+40, H/2+int(H*0.005)+3], fill=(200, 170, 90))
    sb = dr.textbbox((0, 0), sub, font=sf)
    dr.text(((W-(sb[2]-sb[0]))/2, H/2+int(H*0.03)), sub, font=sf, fill=(176, 176, 176))
    png = str(out)+".png"; img.save(png)
    run([FF, "-y", "-v", "error", "-loop", "1", "-i", png, "-f", "lavfi",
         "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{d}",
         "-vf", f"fps={FPS},format=yuv420p,fade=t=in:st=0:d={fade},fade=t=out:st={d-fade:.2f}:d={fade}",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
         "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
         "-movflags", "+faststart", str(out)])
    return str(out)

SZ = {"wide": 1.0, "medium": 0.74, "close": 0.56}
class Shot:
    def __init__(s, a, b, k): s.start, s.end, s.kind, s.zoom = a, b, k, SZ[k]
def plan(D):
    order = ["wide", "medium", "close", "medium", "wide", "close"]; out = []; t = 0.0; i = 0
    while t < D-0.4:
        cut = min(t+5.35, D); k = "wide" if i == 0 else order[i % len(order)]
        if out and out[-1].kind == k and k != "wide": k = "medium" if k != "medium" else "wide"
        out.append(Shot(round(t, 3), round(cut, 3), k)); t = cut; i += 1
    if out: out[-1].end = round(D, 3)
    return out

print("• audio + cards…", flush=True)
master = str(WORK/"master.wav")
run([FF, "-y", "-v", "error", "-i", TEST, "-vn", "-ac", "2", "-ar", "48000",
     "-acodec", "pcm_s16le", master])
D = dur(TEST); shots = plan(D)
title = card("AUTOEDITING FORGE", "The Fully Automated Studio", WORK/"title.mp4")
ending = card("AUTOEDITING FORGE", "The Fully Automated Studio", WORK/"ending.mp4")
print(f"  {len(shots)} operated shots · {len(BRAW)} BRAW clips", flush=True)

os.environ["RESOLVE_SCRIPT_API"] = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
os.environ["RESOLVE_SCRIPT_LIB"] = "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
sys.path.append(os.environ["RESOLVE_SCRIPT_API"]+"/Modules")
import DaVinciResolveScript as dvr
r = dvr.scriptapp("Resolve")
if not r: sys.exit("Resolve not reachable — open DaVinci Resolve Studio.")
pm = r.GetProjectManager(); pm.SaveProject()
proj = pm.CreateProject("finished_work") or pm.LoadProject("finished_work") or pm.GetCurrentProject()
proj.SetSetting("timelineFrameRate", str(FPS))
proj.SetSetting("timelineResolutionWidth", str(W)); proj.SetSetting("timelineResolutionHeight", str(H))
mp = proj.GetMediaPool(); ms = r.GetMediaStorage()
ms.AddItemListToMediaPool(list(dict.fromkeys([TEST, master, title, ending, *BRAW])))
def allc(f):
    cs = list(f.GetClipList() or [])
    for s in (f.GetSubFolderList() or []): cs += allc(s)
    return cs
by = {Path(it.GetClipProperty("File Path")).name: it for it in allc(mp.GetRootFolder()) if it.GetClipProperty("File Path")}
def IT(p): return by[Path(p).name]
def cfps(x, d):
    try: v = x.GetClipProperty("FPS"); return float(v) if v else d
    except Exception: return d
tl = mp.CreateEmptyTimeline(f"finished_work_edit_{int(time.time())}")
if tl is None: sys.exit("could not create timeline")
proj.SetCurrentTimeline(tl)
sf = cfps(IT(TEST), FPS)
ci = [{"mediaPoolItem": IT(title)}]
for s in shots:
    d = s.end-s.start
    ci.append({"mediaPoolItem": IT(TEST), "mediaType": 1, "trackIndex": 1,
               "startFrame": int(round(s.start*sf)), "endFrame": int(round((s.start+d)*sf))-1})
    ci.append({"mediaPoolItem": IT(master), "mediaType": 2, "trackIndex": 1,
               "startFrame": int(round(s.start*FPS)), "endFrame": int(round((s.start+d)*FPS))-1})
for b in BRAW:
    bit = IT(b); bfps = cfps(bit, FPS)
    ci.append({"mediaPoolItem": bit, "startFrame": 0, "endFrame": int(round(BRAW_PORTION*bfps))-1})
ci.append({"mediaPoolItem": IT(ending)})
mp.AppendToTimeline(ci)
vs = tl.GetItemListInTrack("video", 1) or []
for item, s in zip(vs[1:1+len(shots)], shots):
    z = round(1.0/max(0.34, s.zoom), 4); item.SetProperty("ZoomX", z); item.SetProperty("ZoomY", z)
print(f"• timeline: {len(vs)} clips — rendering mp4 to Desktop…", flush=True)
proj.SetCurrentRenderFormatAndCodec("mp4", "H264")
proj.DeleteAllRenderJobs()
proj.SetRenderSettings({"TargetDir": OUT_DIR, "CustomName": OUT_NAME, "SelectAllFrames": True})
proj.AddRenderJob(); proj.StartRendering(isInteractiveMode=False)
while proj.IsRenderingInProgress(): time.sleep(2)
out = Path(OUT_DIR)/f"{OUT_NAME}.mp4"
print("✓ RENDERED to Desktop:" if out.exists() else "! render done but file missing:", out, flush=True)
