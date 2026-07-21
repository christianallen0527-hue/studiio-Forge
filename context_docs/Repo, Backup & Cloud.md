---
title: Repo, Backup & Cloud
type: note
tags: [auto-edit-forge, git, backup, deploy]
created: 2026-07-17
updated: 2026-07-17
summary: GitHub repo, the Desktop zip backup, and phone/cloud access.
---
# Repo, Backup & Cloud

Back to [[Auto Edit Forge — HOME]].

## GitHub repo
- **`auto-edit-forge`** (private) — `https://github.com/christianallen0527-hue/auto-edit-forge`
- GitHub account: **christianallen0527-hue**. Authed via `gh` (GitHub CLI 2.96) using the browser device flow.
- Git identity set: `Christian Allen <christian.allen0527@gmail.com>`.
- **Status:** repo created; the first `git push` was interrupted / hit a transient "stale NFS file handle". **To finish:**
  ```bash
  export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin
  cd '/Users/studio/Desktop/$k auto editing pipeline'
  git push -u origin main
  ```
- `.gitignore` excludes `.venv/`, `ui/jobs/`, `**/out/`, `_work`, `test/raw/`, `__pycache__`, `*.pyc`. Repo is tiny (~68 KB of git objects, 34 tracked files — no large media). Model `models/yunet.onnx` (230 KB) is tracked.

## Desktop backup zip
- **`~/Desktop/auto-edit-forge.zip`** (~2 MB, 258 files) — full code + `README.md` + config + `.git` history + `helper_scripts/` (the `~/Movies` tools). Excludes the regenerable `.venv` and job renders.
- Re-create anytime: `cd '/Users/studio/Desktop/$k auto editing pipeline' && zip -r -q ~/Desktop/auto-edit-forge.zip . -x '.venv/*' 'ui/jobs/*' '*/__pycache__/*' '*.pyc'`.

## Phone / cloud access (the goal)
Christian wants to work on this from his phone via Claude in the cloud. Path: **push to GitHub → open the repo in claude.ai (Claude Code cloud) on the phone.**
1. Finish the push (command above).
2. On the phone, open claude.ai → connect GitHub → open `auto-edit-forge`.
3. From there he can view code and ask for changes from anywhere.

## To restore from zip
Unzip → `cd` in → `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` → double-click `ui/Open Auto Edit.command`.
