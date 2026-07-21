"""DaVinci Resolve Studio backend.

Turns the (refined) cut list into a Resolve timeline and optionally renders it,
reading Blackmagic RAW natively. Layout:

    V1: intro clip(s) -> title card -> camera-switched body -> outro clip(s)
    A1: one pre-mixed master audio track, kept frame-aligned with V1

Requirements at run time:
  * DaVinci Resolve Studio must be OPEN (free/App-Store builds can't be scripted).
  * Preferences > System > General > "External scripting using" = Local.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from .config import Config
from .switch import Segment
from .sync import _vid_id

_VIDEO = 1
_AUDIO = 2

_DEFAULT_API = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
_DEFAULT_LIB = ("/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/"
                "Libraries/Fusion/fusionscript.so")


def _load_bridge():
    api = os.environ.setdefault("RESOLVE_SCRIPT_API", _DEFAULT_API)
    os.environ.setdefault("RESOLVE_SCRIPT_LIB", _DEFAULT_LIB)
    mod = os.path.join(api, "Modules")
    if mod not in sys.path:
        sys.path.append(mod)
    try:
        import DaVinciResolveScript as dvr  # noqa: N813
    except ImportError as e:
        raise RuntimeError(
            "Could not load the DaVinci Resolve scripting module.\n"
            f"Looked in: {mod}\nIs DaVinci Resolve Studio installed?"
        ) from e
    return dvr


def connect():
    dvr = _load_bridge()
    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        raise RuntimeError(
            "Resolve is not reachable. Open DaVinci Resolve Studio and set\n"
            "Preferences > System > General > 'External scripting using' = Local."
        )
    return resolve


def _clip_fps(item, default: float) -> float:
    try:
        val = item.GetClipProperty("FPS")
        return float(val) if val else default
    except Exception:                               # noqa: BLE001
        return default


def build_clip_plan(cfg: Config, segments: list[Segment], offsets: dict,
                    master_audio: str, fps_of):
    """Per-segment plan (offline-testable): chosen camera on V1, master audio on A1."""
    afps = fps_of(master_audio) or cfg.fps
    plan: list[dict] = []
    for seg in segments:
        dur = seg.end - seg.start
        if dur <= 0.02:
            continue
        angle = cfg.angle_by_name(seg.angle)
        vpath = cfg.resolve(angle.video)
        vfps = fps_of(vpath) or cfg.fps
        v_start = max(0.0, seg.start + offsets.get(_vid_id(seg.angle), 0.0))
        v_sf = int(round(v_start * vfps))
        v_ef = v_sf + max(1, int(round(dur * vfps))) - 1
        plan.append({"path": vpath, "name": seg.angle, "mediaType": _VIDEO,
                     "trackIndex": 1, "startFrame": v_sf, "endFrame": v_ef,
                     "fps": vfps, "t0": round(seg.start, 3), "t1": round(seg.end, 3),
                     "rotate": 180 if angle.rotate == 180 else 0})

        a_sf = int(round(seg.start * afps))
        a_ef = a_sf + max(1, int(round(dur * afps))) - 1
        plan.append({"path": master_audio, "name": "master", "mediaType": _AUDIO,
                     "trackIndex": 1, "startFrame": a_sf, "endFrame": a_ef,
                     "fps": afps, "t0": round(seg.start, 3), "t1": round(seg.end, 3)})
    return plan


def build_operator(
    cfg: Config,
    source: str,
    source_offset: float,
    master_audio: str,
    shots,
    out_path: Path,
    log=print,
    render: bool = False,
    prepend: list[str] | None = None,
    face_track: list | None = None,
) -> dict:
    """AI Camera Operator through Resolve: one high-res source, each shot placed
    as a clip with Zoom transform (punch-in) and optional Pan/Tilt (face-follow).
    Full-quality, gradeable timeline the client work can be finished in.
    """
    prepend = prepend or []
    resolve = connect()
    pm = resolve.GetProjectManager()
    pm.SaveProject()
    project = pm.CreateProject(cfg.project_name) or pm.LoadProject(cfg.project_name) \
        or pm.GetCurrentProject()
    if project is None:
        raise RuntimeError("Could not create or open a Resolve project.")
    log(f"  project: {project.GetName()}")
    project.SetSetting("timelineFrameRate", str(cfg.fps))
    project.SetSetting("timelineResolutionWidth", str(cfg.width))
    project.SetSetting("timelineResolutionHeight", str(cfg.height))

    media_pool = project.GetMediaPool()
    storage = resolve.GetMediaStorage()
    to_import = list(dict.fromkeys([source, master_audio, *prepend]))
    storage.AddItemListToMediaPool(to_import)

    def _all(folder):
        cs = list(folder.GetClipList() or [])
        for s in (folder.GetSubFolderList() or []):
            cs += _all(s)
        return cs
    by_name = {}
    for it in _all(media_pool.GetRootFolder()):
        fp = it.GetClipProperty("File Path")
        if fp:
            by_name[Path(fp).name] = it

    def item(p):
        it = by_name.get(Path(p).name)
        if it is None:
            raise RuntimeError(f"Resolve did not import: {p}")
        return it

    src_item = item(source)
    sfps = _clip_fps(src_item, cfg.fps)
    afps = cfg.fps

    tl_name = f"{cfg.project_name}_operated_{int(time.time())}"
    timeline = media_pool.CreateEmptyTimeline(tl_name)
    if timeline is None:
        raise RuntimeError(f"Could not create a timeline ({tl_name}).")
    project.SetCurrentTimeline(timeline)

    clip_infos = []
    for p in prepend:                       # title card first (video + its audio)
        clip_infos.append({"mediaPoolItem": item(p)})
    for s in shots:
        dur = s.end - s.start
        if dur <= 0.05:
            continue
        vs = max(0.0, s.start + source_offset)
        clip_infos.append({"mediaPoolItem": src_item,
                           "startFrame": int(round(vs * sfps)),
                           "endFrame": int(round((vs + dur) * sfps)) - 1,
                           "mediaType": _VIDEO, "trackIndex": 1})
        clip_infos.append({"mediaPoolItem": item(master_audio),
                           "startFrame": int(round(s.start * afps)),
                           "endFrame": int(round((s.start + dur) * afps)) - 1,
                           "mediaType": _AUDIO, "trackIndex": 1})
    media_pool.AppendToTimeline(clip_infos)

    # Apply each shot's punch-in as a Zoom transform + optional Pan/Tilt (face-follow).
    v_items = timeline.GetItemListInTrack("video", 1) or []
    shot_items = v_items[len(prepend):]     # skip the title card(s)
    applied = 0
    for it, s in zip(shot_items, [s for s in shots if s.end - s.start > 0.05]):
        z = round(1.0 / max(0.34, s.zoom), 4)
        try:
            it.SetProperty("ZoomX", z)
            it.SetProperty("ZoomY", z)
            # Face-follow Pan/Tilt: normalize to ±50 (Resolve's pan/tilt range is ±100, 0 = center).
            # cx, cy are normalized (0..1); convert to Resolve space: (cx - 0.5) * 100 → pan,
            # (0.5 - cy) * 100 → tilt (invert Y since Resolve has Y+ = down in normal coords).
            if face_track:
                cx, cy = s.cx, s.cy
                pan = (cx - 0.5) * 100
                tilt = (0.5 - cy) * 100
                it.SetProperty("Pan", round(pan, 1))
                it.SetProperty("Tilt", round(tilt, 1))
            applied += 1
        except Exception:                    # noqa: BLE001
            pass
    log(f"  timeline: {len(shot_items)} operated shots, {applied} punch-ins + face-follow set")

    result = {"backend": "resolve", "project": project.GetName(),
              "timeline": timeline.GetName(), "shots": len(shot_items),
              "rendered": False}
    if not render:
        log("  timeline built in Resolve — grade + render there, or set render: true")
        return result

    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        project.LoadRenderPreset(cfg.render_preset)
    except Exception:                        # noqa: BLE001
        pass
    project.SetRenderSettings({"TargetDir": str(out_path.parent),
                               "CustomName": out_path.stem, "SelectAllFrames": True})
    project.AddRenderJob()
    project.StartRendering(isInteractiveMode=False)
    log("  rendering in Resolve…")
    while project.IsRenderingInProgress():
        time.sleep(2)
    result["rendered"] = True
    result["output"] = str(out_path)
    log("  render complete")
    return result


def build_and_render(
    cfg: Config,
    segments: list[Segment],
    offsets: dict[str, float],
    master_audio: str,
    out_path: Path,
    log=print,
    render: bool = False,
    intro_paths: list[str] | None = None,
    outro_paths: list[str] | None = None,
) -> dict:
    intro_paths = intro_paths or []
    outro_paths = outro_paths or []
    resolve = connect()
    pm = resolve.GetProjectManager()
    pm.SaveProject()                                # let a new project be created
    project = pm.CreateProject(cfg.project_name) or pm.LoadProject(cfg.project_name) \
        or pm.GetCurrentProject()
    if project is None:
        raise RuntimeError("Could not create or open a Resolve project.")
    log(f"  project: {project.GetName()}")

    project.SetSetting("timelineFrameRate", str(cfg.fps))
    project.SetSetting("timelineResolutionWidth", str(cfg.width))
    project.SetSetting("timelineResolutionHeight", str(cfg.height))

    media_pool = project.GetMediaPool()
    storage = resolve.GetMediaStorage()

    to_import = [cfg.resolve(a.video) for a in cfg.angles]
    to_import += [master_audio, *intro_paths, *outro_paths]
    to_import = list(dict.fromkeys(to_import))
    storage.AddItemListToMediaPool(to_import)      # adds any not already present

    def _all_clips(folder):
        clips = list(folder.GetClipList() or [])
        for sub in (folder.GetSubFolderList() or []):
            clips += _all_clips(sub)
        return clips

    by_name: dict = {}
    for it in _all_clips(media_pool.GetRootFolder()):
        fp = it.GetClipProperty("File Path")
        if fp:
            by_name[Path(fp).name] = it
    missing = [Path(p).name for p in to_import if Path(p).name not in by_name]
    if missing:
        raise RuntimeError("Resolve did not import: " + ", ".join(missing))

    def item_for(path: str):
        it = by_name.get(Path(path).name)
        if it is None:
            raise RuntimeError(f"Resolve did not import: {path}")
        return it

    def fps_of(path: str) -> float:
        it = by_name.get(Path(path).name)
        return _clip_fps(it, cfg.fps) if it else cfg.fps

    # Unique name — Resolve returns None if the timeline already exists.
    tl_name = f"{cfg.project_name}_edit_{int(time.time())}"
    timeline = media_pool.CreateEmptyTimeline(tl_name)
    if timeline is None:
        raise RuntimeError(f"Could not create a timeline ({tl_name}).")
    project.SetCurrentTimeline(timeline)

    clip_infos: list[dict] = []
    # Intro clips (whole clip: video + its own/silent audio) keep V1 & A1 aligned.
    for p in intro_paths:
        clip_infos.append({"mediaPoolItem": item_for(p)})
    # Body: chosen camera on V1 + matching master-audio slice on A1.
    plan = build_clip_plan(cfg, segments, offsets, master_audio, fps_of)
    for p in plan:
        clip_infos.append({"mediaPoolItem": item_for(p["path"]),
                           "startFrame": p["startFrame"], "endFrame": p["endFrame"],
                           "mediaType": p["mediaType"], "trackIndex": p["trackIndex"]})
    # Outro clips (whole).
    for p in outro_paths:
        clip_infos.append({"mediaPoolItem": item_for(p)})

    media_pool.AppendToTimeline(clip_infos)
    # The only permitted picture transform: correct reviewed/configured
    # upside-down camera clips. Intro items precede body items on V1.
    body_video_plan = [p for p in plan if p["mediaType"] == _VIDEO]
    video_items = (timeline.GetItemListInTrack("video", 1) or [])[len(intro_paths):]
    rotated = 0
    for timeline_item, planned in zip(video_items, body_video_plan):
        if planned.get("rotate") == 180:
            try:
                if timeline_item.SetProperty("RotationAngle", 180):
                    rotated += 1
            except Exception:                         # noqa: BLE001
                pass
    log(f"  built timeline: {len(intro_paths)} intro + {len(plan)//2} shots + "
        f"{len(outro_paths)} outro"
        + (f"; corrected {rotated} upside-down shots" if rotated else ""))

    result = {"backend": "resolve", "project": project.GetName(),
              "timeline": timeline.GetName(), "shots": len(plan) // 2,
              "rendered": False}

    if not render:
        log("  timeline built (review/render in Resolve, or set render: true)")
        return result

    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        project.LoadRenderPreset(cfg.render_preset)
    except Exception:                               # noqa: BLE001
        log(f"  (render preset '{cfg.render_preset}' not found; using current)")
    # Unique name avoids Resolve reusing / skipping over a stale short render.
    render_name = f"{out_path.stem}_{int(time.time())}"
    try:
        project.DeleteAllRenderJobs()
    except Exception:                               # noqa: BLE001
        pass
    project.SetRenderSettings({
        "TargetDir": str(out_path.parent),
        "CustomName": render_name,
        "SelectAllFrames": True,
        "ExportVideo": True,
        "ExportAudio": True,
    })
    project.AddRenderJob()
    project.StartRendering(isInteractiveMode=False)
    log("  rendering in Resolve…")
    while project.IsRenderingInProgress():
        time.sleep(2)
    # Prefer the freshly rendered file; also copy/alias to the expected stem.
    rendered = None
    for cand in sorted(out_path.parent.glob(render_name + ".*"),
                       key=lambda p: p.stat().st_mtime, reverse=True):
        if cand.suffix.lower() in {".mov", ".mp4", ".mxf"}:
            rendered = cand
            break
    if rendered is None:
        raise RuntimeError(
            f"Resolve finished but no output matching {render_name}.* in "
            f"{out_path.parent}")
    if rendered.resolve() != out_path.resolve():
        # Keep the canonical episode.mp4/mov name the pipeline expects.
        dest = out_path.with_suffix(rendered.suffix)
        try:
            if dest.exists():
                dest.unlink()
            rendered.replace(dest)
            rendered = dest
        except OSError:
            pass
    result["rendered"] = True
    result["output"] = str(rendered)
    log(f"  render complete → {rendered.name}")
    return result
