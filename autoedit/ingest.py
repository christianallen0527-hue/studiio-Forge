"""Footage ingest — AUTOEDITING FORGE front door.

Primary path (this studio):
  **Camera Forge** pulls ``.braw`` from the camera USB SSD. Permanent storage
  is the **Studio Files NAS** (``/Volumes/Studio Files/…``). The Mac SSD is
  only a fast staging area — footage is drained to the NAS so the laptop
  disk does not fill up.

ZowieBox is **monitor-only** — it is NOT a footage source.

Emergency side door: a freshly plugged SSD with ``.braw`` can still be
ingested when ``watch_braw_volumes`` is enabled.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

NETWORK_EXT = {".mp4", ".mov", ".ts", ".m4v", ".mxf"}
BRAW_EXT = {".braw"}
SKIP_VOLUMES = {"Macintosh HD", "Recovery", "Preboot", "VM", "Update"}
SKIP_DIR_NAMES = {
    ".Trashes", ".Spotlight-V100", ".fseventsd", "$RECYCLE.BIN",
    ".runtime", ".venv", "__pycache__",
}

# Permanent storage — Studio Files NAS (large capacity).
STUDIO_FILES = Path("/Volumes/Studio Files")
DEFAULT_INBOX = STUDIO_FILES / "AUTOEDITING FORGE Inbox"
DEFAULT_JOBS = STUDIO_FILES / "AUTOEDITING FORGE Jobs"

# Fast local staging on the Mac SSD — drained into DEFAULT_INBOX. Keep small.
LOCAL_STAGING = Path.home() / "Movies" / "AUTOEDITING FORGE Staging"

# Legacy local inboxes (still listed / drained to NAS).
LEGACY_INBOX = Path.home() / "Movies" / "AutoEdit Inbox"
LEGACY_INBOX_RENAME = Path.home() / "Movies" / "AUTOEDITING FORGE Inbox"
DEFAULT_CAMERA_FORGE_DROP = Path.home() / "Desktop" / "BRAW from Camera Forge"
LEDGER_PATH = Path.home() / ".autoedit_ingest_ledger.json"

SESSION_GAP_SEC = 30 * 60


def studio_files_available() -> bool:
    """True when the Studio Files NAS volume is mounted and writable."""
    try:
        return STUDIO_FILES.is_dir() and os.access(STUDIO_FILES, os.W_OK)
    except OSError:
        return False


def require_studio_files() -> Path:
    if not studio_files_available():
        raise RuntimeError(
            "Studio Files NAS is not mounted at /Volumes/Studio Files. "
            "Mount it before pulling or forging — the Mac SSD is too full "
            "for permanent BRAW storage."
        )
    return STUDIO_FILES


@dataclass
class FoundFile:
    path: Path
    size: int
    mtime: float


@dataclass
class Ledger:
    path: Path = LEDGER_PATH
    entries: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path = LEDGER_PATH) -> "Ledger":
        led = cls(path=path)
        if path.exists():
            try:
                led.entries = json.loads(path.read_text())
            except json.JSONDecodeError:
                led.entries = {}
        return led

    def key(self, f: FoundFile) -> str:
        return f"{f.path}|{f.size}|{int(f.mtime)}"

    def seen(self, f: FoundFile) -> bool:
        return self.key(f) in self.entries

    def mark(self, f: FoundFile, dest: str) -> None:
        self.entries[self.key(f)] = {"dest": dest, "at": time.time()}

    def save(self) -> None:
        self.path.write_text(json.dumps(self.entries, indent=1))


def expand_path(p: str | Path) -> Path:
    return Path(os.path.expanduser(str(p))).resolve()


def scan_folder(root: Path, exts: set[str], max_depth: int = 4) -> list[FoundFile]:
    """Find candidate media under root (bounded depth, skips system dirs)."""
    out: list[FoundFile] = []
    if not root.is_dir():
        return out
    base_depth = len(root.parts)

    def walk(d: Path):
        if len(d.parts) - base_depth > max_depth or d.name in SKIP_DIR_NAMES:
            return
        try:
            for c in d.iterdir():
                if c.name.startswith("."):
                    continue
                if c.is_dir():
                    walk(c)
                elif c.suffix.lower() in exts:
                    st = c.stat()
                    out.append(FoundFile(c, st.st_size, st.st_mtime))
        except (PermissionError, OSError):
            return

    walk(root)
    return out


def is_stable(f: FoundFile, settle_sec: float = 20.0) -> bool:
    """A file still being written isn't ready to ingest."""
    try:
        st = f.path.stat()
    except OSError:
        return False
    return st.st_size == f.size and (time.time() - st.st_mtime) >= settle_sec


def group_sessions(files: list[FoundFile], gap: float = SESSION_GAP_SEC
                   ) -> list[list[FoundFile]]:
    """Cluster files into sessions: mtimes within `gap` of the previous file."""
    if not files:
        return []
    files = sorted(files, key=lambda f: f.mtime)
    groups: list[list[FoundFile]] = [[files[0]]]
    for f in files[1:]:
        if f.mtime - groups[-1][-1].mtime <= gap:
            groups[-1].append(f)
        else:
            groups.append([f])
    return groups


def session_name(files: list[FoundFile], kind: str) -> str:
    t = time.localtime(min(f.mtime for f in files))
    stamp = time.strftime("%Y-%m-%d_%H%M", t)
    return f"{stamp}-{kind}"


def mounted_volumes() -> list[Path]:
    vols = []
    root = Path("/Volumes")
    if root.is_dir():
        for v in root.iterdir():
            if v.name not in SKIP_VOLUMES and v.is_dir():
                vols.append(v)
    return vols


def write_session_manifest(
    sess: Path,
    *,
    files: list[str],
    kind: str = "braw",
    engine: str | None = None,
    source: str = "camera-forge",
    cameras: list[dict] | None = None,
    extra: dict | None = None,
) -> Path:
    """Write/refresh ``session.json`` for a drop folder (idempotent)."""
    sess.mkdir(parents=True, exist_ok=True)
    manifest = {
        "kind": kind,
        "engine": engine or ("resolve" if kind == "braw" else "ffmpeg"),
        "source": source,
        "files": list(files),
        "cameras": cameras or [],
        "ingested_at": time.time(),
    }
    if extra:
        manifest.update(extra)
    path = sess / "session.json"
    path.write_text(json.dumps(manifest, indent=2))
    return path


def list_braw_names(folder: Path) -> list[str]:
    if not folder.is_dir():
        return []
    return sorted(
        p.name for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in BRAW_EXT and not p.name.startswith(".")
    )


def ensure_session_for_folder(
    folder: Path,
    *,
    source: str = "camera-forge",
    cam_id: int | None = None,
    log=print,
) -> Path | None:
    """If folder has .braw, ensure session.json exists. Returns session path or None."""
    names = list_braw_names(folder)
    if not names:
        return None
    mf = folder / "session.json"
    # Parse CAM1_2026-07-21 style folder names when possible
    cam = cam_id
    if cam is None and folder.name.upper().startswith("CAM"):
        part = folder.name.split("_", 1)[0]
        try:
            cam = int(part[3:])
        except ValueError:
            cam = None
    cameras = [{"id": cam, "name": f"CAM{cam}", "files": names}] if cam else []
    if mf.exists():
        try:
            existing = json.loads(mf.read_text())
            # Refresh file list if new clips landed in the same folder
            if set(existing.get("files") or []) != set(names):
                write_session_manifest(
                    folder, files=names, source=existing.get("source", source),
                    cameras=cameras or existing.get("cameras"),
                )
                log(f"  ◆ refreshed session {folder.name} ({len(names)} clips)")
            return folder
        except json.JSONDecodeError:
            pass
    write_session_manifest(folder, files=names, source=source, cameras=cameras)
    log(f"  ✓ Camera Forge session ready: {folder.name} ({len(names)} BRAW)")
    return folder


def _move_tree(src: Path, dest: Path, log=print) -> None:
    """Move a file/folder onto the NAS (copy+delete if cross-volume rename fails)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(src, dest)
        return
    except OSError:
        pass
    if src.is_dir():
        shutil.copytree(src, dest, dirs_exist_ok=True)
        shutil.rmtree(src)
    else:
        shutil.copy2(src, dest)
        src.unlink()


def _folder_has_media(folder: Path) -> bool:
    """True if folder looks like an ingest session (BRAW / video / session.json)."""
    try:
        for c in folder.iterdir():
            if c.name.startswith("."):
                continue
            if c.name == "session.json":
                return True
            if c.is_file() and c.suffix.lower() in (BRAW_EXT | NETWORK_EXT):
                return True
    except OSError:
        return False
    return False


def _newest_mtime(folder: Path) -> float:
    newest = 0.0
    try:
        for c in folder.rglob("*"):
            if c.is_file() and not c.name.startswith("."):
                try:
                    newest = max(newest, c.stat().st_mtime)
                except OSError:
                    pass
    except OSError:
        pass
    return newest


def _dedupe_local_after_nas(src_dir: Path, dest_dir: Path, log=print) -> None:
    """Delete Mac copies that already exist on the NAS (same name + size)."""
    try:
        children = list(src_dir.iterdir())
    except OSError:
        return
    for src_f in children:
        if src_f.name.startswith("."):
            continue
        dst_f = dest_dir / src_f.name
        if src_f.is_file() and dst_f.is_file():
            try:
                if src_f.stat().st_size == dst_f.stat().st_size:
                    src_f.unlink()
            except OSError:
                pass
        elif src_f.is_dir() and dst_f.is_dir():
            _dedupe_local_after_nas(src_f, dst_f, log=log)
            try:
                if not any(src_f.iterdir()):
                    src_f.rmdir()
            except OSError:
                pass
    # Drop empty staging folder once everything is on NAS
    try:
        if not any(p for p in src_dir.iterdir() if not p.name.startswith(".")):
            shutil.rmtree(src_dir, ignore_errors=True)
            log(f"  ✓ freed Mac staging {src_dir.name} (already on NAS)")
    except OSError:
        pass


def drain_local_to_nas(
    staging_dirs: list[Path],
    inbox: Path = DEFAULT_INBOX,
    settle_sec: float = 15.0,
    log=print,
) -> list[Path]:
    """Move finished drops from Mac SSD staging → Studio Files inbox.

    The Mac only has a few GB free; BRAW (and session folders) must not stay local.
    """
    if not studio_files_available():
        log("  ! Studio Files NAS offline — leaving staging in place (do not fill Mac)")
        return []
    inbox = expand_path(inbox)
    inbox.mkdir(parents=True, exist_ok=True)
    touched: list[Path] = []

    for root in staging_dirs:
        root = expand_path(root)
        if not root.is_dir():
            continue
        # Never treat the NAS inbox as staging
        try:
            if root.resolve() == inbox.resolve():
                continue
        except OSError:
            continue
        try:
            children = list(root.iterdir())
        except OSError:
            continue

        for child in children:
            if child.name.startswith(".") or child.name in SKIP_DIR_NAMES:
                continue
            if child.is_dir():
                if not _folder_has_media(child):
                    continue
                newest = _newest_mtime(child)
                if newest and time.time() - newest < settle_sec:
                    continue
                dest = inbox / child.name
                if dest.exists():
                    # Merge new files, then delete Mac dupes already on NAS
                    try:
                        for src_f in child.iterdir():
                            if src_f.name.startswith("."):
                                continue
                            dst_f = dest / src_f.name
                            if src_f.is_file() and not dst_f.exists():
                                log(f"  ⇪ {src_f.name} → NAS {dest.name}/")
                                _move_tree(src_f, dst_f, log=log)
                    except OSError:
                        pass
                    if list_braw_names(dest):
                        ensure_session_for_folder(dest, log=log)
                    _dedupe_local_after_nas(child, dest, log=log)
                    touched.append(dest)
                else:
                    log(f"  ⇪ staging {child.name} → Studio Files inbox")
                    _move_tree(child, dest, log=log)
                    if list_braw_names(dest):
                        ensure_session_for_folder(dest, log=log)
                    touched.append(dest)
            elif child.is_file() and child.suffix.lower() in (BRAW_EXT | NETWORK_EXT):
                f = FoundFile(child, child.stat().st_size, child.stat().st_mtime)
                if not is_stable(f, settle_sec):
                    continue
                kind = "braw" if child.suffix.lower() in BRAW_EXT else "network"
                sess = inbox / session_name([f], kind)
                sess.mkdir(parents=True, exist_ok=True)
                dest = sess / child.name
                if not dest.exists():
                    log(f"  ⇪ {child.name} → NAS {sess.name}/")
                    _move_tree(child, dest, log=log)
                elif dest.stat().st_size == child.stat().st_size:
                    child.unlink()
                if kind == "braw":
                    write_session_manifest(
                        sess, files=[child.name], source="camera-forge")
                touched.append(sess)
    return touched


def promote_camera_forge_drops(
    watch_dirs: list[Path],
    inbox: Path = DEFAULT_INBOX,
    settle_sec: float = 15.0,
    log=print,
) -> list[Path]:
    """Scan Camera Forge drop folders; write session.json; move orphans into inbox.

    - Subfolders that already contain ``.braw`` (e.g. ``CAM1_2026-07-21``) get a
      manifest in place (no re-copy when they already live under the inbox).
    - Loose ``.braw`` files sitting directly in a watch dir are grouped into a
      new session under ``inbox``.
    """
    if not studio_files_available():
        log("  ! Studio Files NAS offline — cannot promote into permanent inbox")
        return []
    inbox = expand_path(inbox)
    inbox.mkdir(parents=True, exist_ok=True)
    touched: list[Path] = []

    for root in watch_dirs:
        root = expand_path(root)
        if not root.is_dir():
            continue

        # 1) Subfolders with BRAW (Camera Forge CAM*_date layout)
        try:
            children = list(root.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_dir() or child.name.startswith(".") or child.name in SKIP_DIR_NAMES:
                continue
            names = list_braw_names(child)
            if not names:
                continue
            # Wait until the newest file looks finished (pull may still be writing)
            try:
                newest = max((child / n).stat().st_mtime for n in names)
            except OSError:
                continue
            if time.time() - newest < settle_sec:
                continue
            # If drop folder is outside inbox, copy into a session under inbox
            try:
                child.resolve().relative_to(inbox.resolve())
                in_inbox = True
            except ValueError:
                in_inbox = False

            if in_inbox:
                got = ensure_session_for_folder(child, log=log)
                if got:
                    touched.append(got)
            else:
                # Copy stable files into a new inbox session (once)
                found = [
                    FoundFile(child / n, (child / n).stat().st_size,
                              (child / n).stat().st_mtime)
                    for n in names if (child / n).is_file()
                ]
                found = [f for f in found if is_stable(f, settle_sec)]
                if not found:
                    continue
                sess = inbox / session_name(found, "braw")
                if not (sess / "session.json").exists():
                    sess.mkdir(parents=True, exist_ok=True)
                    for f in found:
                        dest = sess / f.path.name
                        if not dest.exists():
                            log(f"  ⇣ {f.path.name} → {sess.name}/")
                            shutil.copy2(f.path, dest)
                    cam = None
                    if child.name.upper().startswith("CAM"):
                        try:
                            cam = int(child.name.split("_", 1)[0][3:])
                        except ValueError:
                            pass
                    cams = [{"id": cam, "name": f"CAM{cam}",
                             "files": [f.path.name for f in found]}] if cam else []
                    write_session_manifest(
                        sess,
                        files=[f.path.name for f in found],
                        source="camera-forge",
                        cameras=cams,
                    )
                    log(f"  ✓ session ready: {sess.name}")
                touched.append(sess)

        # 2) Loose .braw directly in the watch root (not inside a CAM*_ folder)
        loose = [
            f for f in scan_folder(root, BRAW_EXT, max_depth=0)
            if f.path.parent.resolve() == root.resolve() and is_stable(f, settle_sec)
        ]
        if loose:
            for group in group_sessions(loose):
                sess = inbox / session_name(group, "braw")
                sess.mkdir(parents=True, exist_ok=True)
                names = []
                new_copy = False
                for f in group:
                    dest = sess / f.path.name
                    if not dest.exists():
                        log(f"  ⇣ {f.path.name} → {sess.name}/")
                        shutil.copy2(f.path, dest)
                        new_copy = True
                    names.append(f.path.name)
                mf = sess / "session.json"
                if new_copy or not mf.exists():
                    write_session_manifest(
                        sess, files=names, source="camera-forge")
                    log(f"  ✓ session ready: {sess.name}")
                touched.append(sess)

    return touched


def ingest_pass(
    network_sources: list[Path],
    inbox: Path = DEFAULT_INBOX,
    ledger: Ledger | None = None,
    watch_braw_volumes: bool = False,
    braw_volumes: list[Path] | None = None,
    camera_forge_dirs: list[Path] | None = None,
    staging_dirs: list[Path] | None = None,
    settle_sec: float = 20.0,
    log=print,
) -> list[Path]:
    """One sweep. Drain Mac staging → NAS, then refresh Camera Forge sessions."""
    ledger = ledger or Ledger.load()
    touched: list[Path] = []

    if not studio_files_available():
        log("  ! Studio Files NAS not mounted at /Volumes/Studio Files")
        log("  ! Refusing to store BRAW on the Mac SSD (almost full). Mount NAS.")
        return []

    inbox = expand_path(inbox)
    inbox.mkdir(parents=True, exist_ok=True)

    # 0) Drain fast local staging / legacy Mac drops onto the NAS
    stage = list(staging_dirs or [
        LOCAL_STAGING,
        LEGACY_INBOX_RENAME,
        LEGACY_INBOX,
        DEFAULT_CAMERA_FORGE_DROP,
    ])
    touched.extend(drain_local_to_nas(
        stage, inbox=inbox, settle_sec=min(settle_sec, 15.0), log=log))

    # 1) Camera Forge drop folders (including the NAS inbox itself)
    cf_dirs = list(camera_forge_dirs or [])
    if inbox not in cf_dirs:
        cf_dirs = [inbox, *cf_dirs]
    touched.extend(promote_camera_forge_drops(
        cf_dirs, inbox=inbox, settle_sec=min(settle_sec, 15.0), log=log))

    def pull(files: list[FoundFile], kind: str):
        fresh = [f for f in files
                 if not ledger.seen(f) and is_stable(f, settle_sec)]
        if not fresh:
            return
        for group in group_sessions(fresh):
            sess = inbox / session_name(group, kind)
            sess.mkdir(parents=True, exist_ok=True)
            for f in group:
                dest = sess / f.path.name
                if dest.exists() and dest.stat().st_size == f.size:
                    ledger.mark(f, str(dest))
                    continue
                log(f"  ⇣ {f.path.name}  ({f.size/1e9:.2f} GB) → {sess.name}/")
                shutil.copy2(f.path, dest)
                ledger.mark(f, str(dest))
            write_session_manifest(
                sess,
                files=[f.path.name for f in group],
                kind=kind,
                source="network" if kind == "network" else "ssd-side-door",
            )
            touched.append(sess)

    # Optional network masters (not Zowie monitor path — left empty by default)
    for src in network_sources:
        pull(scan_folder(Path(src), NETWORK_EXT), "network")

    # Emergency: freshly plugged SSD with BRAW (off by default)
    if watch_braw_volumes:
        vols = braw_volumes if braw_volumes is not None else mounted_volumes()
        for vol in vols:
            found = scan_folder(vol, BRAW_EXT)
            if found:
                log(f"  ◆ BRAW drive detected: {vol.name} ({len(found)} clips)")
                pull(found, "braw")

    ledger.save()
    # Dedupe touched paths
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in touched:
        k = str(p.resolve()) if p.exists() else str(p)
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq


def list_sessions(inbox_roots: list[Path] | None = None, limit: int = 40) -> list[dict]:
    """List session folders with manifests (newest first)."""
    roots = inbox_roots or [
        DEFAULT_INBOX,
        LEGACY_INBOX_RENAME,
        LEGACY_INBOX,
        STUDIO_FILES / "AutoEdit Inbox Archive",
        LOCAL_STAGING,
    ]
    sessions: list[dict] = []
    for root in roots:
        root = expand_path(root)
        if not root.is_dir():
            continue
        try:
            kids = list(root.iterdir())
        except OSError:
            continue
        for s in kids:
            mf = s / "session.json"
            if not (s.is_dir() and mf.exists()):
                continue
            try:
                m = json.loads(mf.read_text())
            except json.JSONDecodeError:
                continue
            sessions.append({
                "name": s.name,
                "path": str(s),
                "engine": m.get("engine"),
                "kind": m.get("kind"),
                "source": m.get("source"),
                "files": m.get("files", []),
                "ingested_at": m.get("ingested_at"),
                "inbox": str(root),
            })
    sessions.sort(key=lambda x: x.get("ingested_at") or 0, reverse=True)
    return sessions[:limit]


def watch(network_sources: list[str], inbox: str | None = None,
          interval: float = 60.0,
          camera_forge_dirs: list[str] | None = None,
          watch_braw_volumes: bool = False,
          log=print) -> None:
    """Run forever: sweep every `interval` seconds."""
    inbox_p = Path(inbox) if inbox else DEFAULT_INBOX
    inbox_p.mkdir(parents=True, exist_ok=True)
    srcs = [Path(s) for s in network_sources]
    cf = [Path(s) for s in (camera_forge_dirs or [])]
    log(f"Camera Forge drops: {', '.join(map(str, cf)) or str(inbox_p)}")
    log(f"Network sources: {', '.join(map(str, srcs)) or '(none — Zowie is monitor-only)'}")
    log(f"BRAW SSD side door: {'on' if watch_braw_volumes else 'off'}")
    log(f"Inbox: {inbox_p}")
    while True:
        try:
            got = ingest_pass(
                srcs, inbox_p, log=log,
                camera_forge_dirs=cf or None,
                watch_braw_volumes=watch_braw_volumes,
            )
            for s in got:
                log(f"  ✓ session ready: {s.name}")
        except Exception as e:                       # noqa: BLE001
            log(f"  ! ingest error: {e}")
        time.sleep(interval)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="AUTOEDITING FORGE footage ingest daemon")
    ap.add_argument("--source", action="append", default=[],
                    help="Optional network master folder (not Zowie monitor)")
    ap.add_argument("--camera-forge", action="append", default=[],
                    help="Camera Forge BRAW drop folder (repeatable)")
    ap.add_argument("--inbox", default=str(DEFAULT_INBOX))
    ap.add_argument("--interval", type=float, default=60.0)
    ap.add_argument("--braw-volumes", action="store_true",
                    help="Also scan freshly mounted SSDs for .braw")
    ap.add_argument("--once", action="store_true", help="Single sweep, then exit")
    a = ap.parse_args()
    cf = a.camera_forge or [str(DEFAULT_INBOX), str(DEFAULT_CAMERA_FORGE_DROP)]
    if a.once:
        got = ingest_pass(
            [Path(s) for s in a.source], Path(a.inbox),
            camera_forge_dirs=[Path(s) for s in cf],
            watch_braw_volumes=a.braw_volumes,
        )
        print(f"{len(got)} session(s) ingested")
    else:
        watch(a.source, a.inbox, a.interval,
              camera_forge_dirs=cf, watch_braw_volumes=a.braw_volumes)
