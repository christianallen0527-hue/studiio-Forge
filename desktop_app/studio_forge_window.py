#!/usr/bin/env python3
"""Native desktop window for Studio Forge (pywebview)."""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:8765")
    p.add_argument("--title", default="Studio Forge")
    args = p.parse_args(argv)
    try:
        import webview
    except ImportError:
        print("pywebview not installed", file=sys.stderr)
        return 2
    webview.create_window(
        args.title,
        args.url,
        width=1280,
        height=860,
        min_size=(960, 640),
        background_color="#0a0706",
    )
    webview.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
