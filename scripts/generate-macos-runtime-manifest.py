#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
from pathlib import Path


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> None:
    runtime = Path(sys.argv[1]).resolve()
    source = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    lock = Path(sys.argv[3])
    output = runtime / "runtime-manifest.json"
    ffmpeg_version = subprocess.run(
        [runtime / "bin/ffmpeg", "-version"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()[0]
    packages = sorted(
        (
            {"name": item.metadata["Name"], "version": item.version}
            for item in importlib.metadata.distributions()
        ),
        key=lambda item: item["name"].lower(),
    )
    files = []
    for path in sorted(runtime.rglob("*")):
        if path == output or path.is_dir():
            continue
        relative = str(path.relative_to(runtime))
        if path.is_symlink():
            target = os.readlink(path)
            resolved = path.resolve(strict=True)
            resolved.relative_to(runtime)
            files.append({"relativePath": relative, "type": "symlink", "target": target})
        elif path.is_file():
            files.append(
                {
                    "relativePath": relative,
                    "type": "file",
                    "sizeBytes": path.stat().st_size,
                    "sha256": digest(path),
                }
            )
        else:
            raise RuntimeError(f"Unsupported Runtime entry: {relative}")

    def command(*arguments: str) -> str:
        return subprocess.run(arguments, check=True, capture_output=True, text=True).stdout.strip()

    toolchain = {
        "xcodeVersion": command("xcodebuild", "-version"),
        "clangVersion": command("clang", "--version").splitlines()[0],
        "macOSSDKVersion": command("xcrun", "--sdk", "macosx", "--show-sdk-version"),
        "hostMacOSVersion": command("sw_vers", "-productVersion"),
    }
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    payload = {
        "schemaVersion": 1,
        "runtimeVersion": "v1",
        "platform": "macOS",
        "architecture": platform.machine(),
        "pythonVersion": platform.python_version(),
        "pythonSource": source["python"],
        "ffmpeg": {
            **source["ffmpeg"],
            "runtimeVersion": ffmpeg_version,
        },
        "packageVersion": importlib.metadata.version("xingyu-lyrics-aligner"),
        "packagesLockHash": digest(lock),
        "sourceDateEpoch": int(epoch) if epoch else None,
        "packages": packages,
        "toolchain": toolchain,
        "files": files,
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
