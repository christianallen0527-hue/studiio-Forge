#!/usr/bin/env python3
"""AUTOEDITING FORGE command-line entry point.

Usage:
    python edit.py project.yaml                 # full auto-edit
    python edit.py project.yaml --check-sync    # just print sync offsets
    python edit.py project.yaml --only assemble # long-form only, skip shorts

Progress is printed to stderr; a machine-readable JSON result is printed to
stdout at the end (so the UI that calls this can parse it).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from autoedit import config as cfgmod
from autoedit import pipeline


def _log(msg: str = "") -> None:
    print(msg, file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="AUTOEDITING FORGE")
    p.add_argument("config", nargs="?", default="project.yaml",
                   help="Path to the project YAML (default: project.yaml)")
    p.add_argument("--check-sync", action="store_true",
                   help="Only compute and print the sync offsets, then exit")
    p.add_argument("--only", default="",
                   help="Comma list of stages to run: assemble,transcribe,shorts")
    args = p.parse_args(argv)

    try:
        cfg = cfgmod.load(args.config)
    except (OSError, ValueError) as e:
        _log(f"Config error: {e}")
        return 2

    try:
        if args.check_sync:
            offsets = pipeline.check_sync(cfg, log=_log)
            print(json.dumps(offsets, indent=2))
            return 0

        stages = ({s.strip() for s in args.only.split(",") if s.strip()}
                  or {"assemble", "transcribe", "shorts"})
        results = pipeline.run(cfg, stages=stages, log=_log)
        print(json.dumps(results, indent=2))
        return 0
    except Exception as e:                          # noqa: BLE001
        _log(f"\nERROR: {e}")
        return 1


if __name__ == "__main__":
    _rc = main()
    # Resolve's Python module can segfault during normal interpreter teardown;
    # flush and hard-exit so automated/hands-off runs always return a clean code.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(_rc)
