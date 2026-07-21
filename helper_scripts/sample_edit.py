import os, sys, time
os.environ.setdefault("RESOLVE_SCRIPT_API","/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting")
os.environ.setdefault("RESOLVE_SCRIPT_LIB","/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so")
sys.path.append(os.environ["RESOLVE_SCRIPT_API"]+"/Modules")
import DaVinciResolveScript as dvr
r = dvr.scriptapp("Resolve"); pm = r.GetProjectManager(); proj = pm.GetCurrentProject()
mp = proj.GetMediaPool()
proj.SetSetting("timelineFrameRate","30"); proj.SetSetting("timelineResolutionWidth","1920"); proj.SetSetting("timelineResolutionHeight","1080")
def allclips(f):
    cs=list(f.GetClipList() or [])
    for s in (f.GetSubFolderList() or []): cs+=allclips(s)
    return cs
by={}
for c in allclips(mp.GetRootFolder()):
    by[c.GetName()]=c
def fps(c):
    try: return float(c.GetClipProperty("FPS") or 30)
    except: return 30.0
# Build: title -> 3 BRAW portions (as-is, own audio) -> ending
order=[]
order.append({"mediaPoolItem":by["title.mp4"]})
for name,secs in [("A001_04281422_C002.braw",12),("A001_05010946_C003.braw",5),("A001_05122245_C003.braw",12)]:
    c=by[name]; f=fps(c)
    order.append({"mediaPoolItem":c,"startFrame":0,"endFrame":int(secs*f)-1})
order.append({"mediaPoolItem":by["ending.mp4"]})
tl=mp.CreateEmptyTimeline("sample_edit_%d"%int(time.time()))
proj.SetCurrentTimeline(tl)
mp.AppendToTimeline(order)
print("timeline items V1:", len(tl.GetItemListInTrack("video",1) or []))
# Render mp4 to ~/Movies
out=os.path.expanduser("~/Movies")
try: proj.SetCurrentRenderFormatAndCodec("mp4","H264")
except Exception as e: print("fmt:",e)
proj.SetRenderSettings({"TargetDir":out,"CustomName":"sample_edit","SelectAllFrames":True})
proj.DeleteAllRenderJobs(); proj.AddRenderJob(); proj.StartRendering(isInteractiveMode=False)
print("rendering…")
while proj.IsRenderingInProgress(): time.sleep(2)
print("DONE:", os.path.join(out,"sample_edit.mp4"))
