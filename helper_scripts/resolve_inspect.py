import os, sys
os.environ.setdefault("RESOLVE_SCRIPT_API","/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting")
os.environ.setdefault("RESOLVE_SCRIPT_LIB","/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so")
sys.path.append(os.environ["RESOLVE_SCRIPT_API"]+"/Modules")
try:
    import DaVinciResolveScript as dvr
except Exception as e:
    print("NO_MODULE", e); sys.exit(1)
r = dvr.scriptapp("Resolve")
if not r:
    print("NOT_CONNECTED — open DaVinci Resolve Studio"); sys.exit(1)
print("CONNECTED:", r.GetProductName(), r.GetVersionString())
pm = r.GetProjectManager(); proj = pm.GetCurrentProject()
print("PROJECT:", proj.GetName() if proj else None)
mp = proj.GetMediaPool()
def allclips(f):
    cs = list(f.GetClipList() or [])
    for s in (f.GetSubFolderList() or []): cs += allclips(s)
    return cs
clips = allclips(mp.GetRootFolder())
print("MEDIA POOL CLIPS:", len(clips))
for c in clips[:25]:
    fp = c.GetClipProperty("File Path") or ""
    print("  -", c.GetName(), "|", c.GetClipProperty("Duration"), "|", os.path.splitext(fp)[1])
tls = proj.GetTimelineCount()
print("TIMELINES:", tls)
for i in range(1, tls+1):
    t = proj.GetTimelineByIndex(i)
    print("  TL:", t.GetName(), "items V1:", len(t.GetItemListInTrack("video",1) or []))
