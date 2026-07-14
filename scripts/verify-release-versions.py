#!/usr/bin/env python3
"""Fail a formal release candidate when product/engine artifacts drift."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def require(label: str, actual: str | None, expected: str) -> None:
    if actual != expected:
        raise SystemExit(f"{label} version mismatch: {actual!r} != {expected!r}")


def json_version(path: Path, key: str) -> str:
    return str(json.loads(path.read_text(encoding="utf-8"))[key])


def require_text(path: Path, expected_text: str) -> None:
    if expected_text not in path.read_text(encoding="utf-8"):
        raise SystemExit(f"Release documentation mismatch: {path} lacks {expected_text!r}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--expected-version")
    parser.add_argument("--runtime-manifest", type=Path)
    parser.add_argument("--wheelhouse-manifest", type=Path)
    parser.add_argument("--release-manifest", type=Path)
    parser.add_argument("--dmg", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    project_match = re.search(
        r"^\[project\].*?^version\s*=\s*[\"']([^\"']+)",
        pyproject,
        re.MULTILINE | re.DOTALL,
    )
    package = project_match.group(1) if project_match else None
    expected = args.expected_version or package
    if expected is None:
        raise SystemExit("Could not determine expected release version.")
    require("pyproject", package, expected)
    init_text = (root / "src/xingyu_lyrics_aligner/__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)', init_text, re.MULTILINE)
    require("Python __version__", match.group(1) if match else None, expected)
    project = (root / "apps/macos/XingyuLyricsAligner.xcodeproj/project.pbxproj").read_text()
    marketing = set(re.findall(r"MARKETING_VERSION = ([^;]+);", project))
    if marketing != {expected}:
        raise SystemExit(f"Xcode MARKETING_VERSION mismatch: {sorted(marketing)} != {[expected]}")
    build_numbers = set(re.findall(r"CURRENT_PROJECT_VERSION = ([^;]+);", project))
    if build_numbers != {"1"}:
        raise SystemExit(f"Xcode build number mismatch: {sorted(build_numbers)} != ['1']")
    current_document_markers = {
        "README.md": f"v{expected}",
        "README.zh-CN.md": f"v{expected}",
        "CHANGELOG.md": f"Unreleased — {expected}",
        "docs/macos-release.md": f"macOS v{expected} release candidate",
        "docs/macos-runtime.md": f"final {expected} candidate Runtime",
        "docs/macos-model-management.md": f"v{expected} native App",
        "docs/macos-unsigned-install.md": f"v{expected} macOS Desktop",
        "docs/desktop-worker-protocol.md": f'"workerVersion": "{expected}"',
    }
    for relative_path, marker in current_document_markers.items():
        require_text(root / relative_path, marker)
    about = (root / "apps/macos/XingyuLyricsAligner/Views/AboutView.swift").read_text(
        encoding="utf-8"
    )
    if "Development Candidate" in about:
        raise SystemExit("About still contains the Development Candidate fallback")
    if args.runtime_manifest:
        require("runtime package", json_version(args.runtime_manifest, "packageVersion"), expected)
        require("runtime version", json_version(args.runtime_manifest, "runtimeVersion"), "v1")
    if args.wheelhouse_manifest:
        wheels = json.loads(args.wheelhouse_manifest.read_text())["wheels"]
        project_wheel = next(
            (item for item in wheels if item["name"] == "xingyu-lyrics-aligner"), None
        )
        version = None if project_wheel is None else str(project_wheel["version"])
        require("project wheel", version, expected)
        if project_wheel is None or f"-{expected}-" not in str(project_wheel.get("filename")):
            raise SystemExit("Project wheel filename does not contain the release version")
    if args.release_manifest:
        manifest = json.loads(args.release_manifest.read_text())
        require("release app", str(manifest.get("appVersion")), expected)
        require("release engine", str(manifest.get("engineVersion")), expected)
        require("release Python package", str(manifest.get("pythonPackageVersion")), expected)
        require("release build number", str(manifest.get("buildNumber")), "1")
        if manifest.get("developerIdSigned") is not False:
            raise SystemExit("Unsigned candidate must declare developerIdSigned=false")
        if manifest.get("signatureType") != "ADHOC":
            raise SystemExit("Unsigned candidate must declare signatureType=ADHOC")
        if manifest.get("notarized") is not False or manifest.get("gatekeeperTrusted") is not False:
            raise SystemExit("Unsigned candidate must not claim notarization or Gatekeeper trust")
    if args.dmg and f"-{expected}-" not in args.dmg.name:
        raise SystemExit(
            f"DMG filename does not contain release version {expected}: {args.dmg.name}"
        )
    print(f"Release versions are consistent: {expected}")


if __name__ == "__main__":
    main()
