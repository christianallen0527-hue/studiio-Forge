#!/usr/bin/env python3
"""List .braw on Studio Files via Resolve's MediaStorage (Resolve has disk access)."""
import os, sys
os.environ["RESOLVE_SCRIPT_API"] = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
os.environ["RESOLVE_SCRIPT_LIB"] = "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
sys.path.append(os.environ["RESOLVE_SCRIPT_API"] + "/Modules")
import DaVinciResolveScript as dvr

r = dvr.scriptapp("Resolve")
if not r:
    sys.exit("Resolve not reachable — open DaVinci Resolve Studio first.")
ms = r.GetMediaStorage()

found = []
def walk(path, depth=0):
    if depth > 4:
        return
    for f in (ms.GetFileList(path) or []):
        if str(f).lower().endswith(".braw"):
            found.append(str(f))
    for sub in (ms.GetSubFolderList(path) or []):
        walk(sub, depth + 1)

walk("/Volumes/Studio Files")
print(f"{len(found)} braw file(s):")
for f in found:
    print("  " + f)
