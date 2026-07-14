#!/usr/bin/env python3
"""Minimal deterministic pkg-config adapter for the pinned PyAV build only."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ALLOWED = {
    "libavformat",
    "libavcodec",
    "libavdevice",
    "libavutil",
    "libavfilter",
    "libswscale",
    "libswresample",
}


def main() -> None:
    prefix_value = os.environ.get("XINGYU_LGPL_FFMPEG_PREFIX")
    if not prefix_value:
        raise SystemExit("XINGYU_LGPL_FFMPEG_PREFIX is required")
    prefix = Path(prefix_value).resolve()
    requested = {value for value in sys.argv[1:] if not value.startswith("-")}
    if not requested or not requested.issubset(ALLOWED):
        raise SystemExit(f"Unsupported pkg-config request: {sorted(requested)}")
    libraries = " ".join(f"-l{value.removeprefix('lib')}" for value in sorted(requested))
    print(f"-I{prefix / 'include'} -L{prefix / 'lib'} {libraries}")


if __name__ == "__main__":
    main()
