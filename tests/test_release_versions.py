from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def write_fixture(root: Path, *, app_version: str = "0.7.0") -> None:
    (root / "src/xingyu_lyrics_aligner").mkdir(parents=True)
    (root / "apps/macos/XingyuLyricsAligner.xcodeproj").mkdir(parents=True)
    (root / "apps/macos/XingyuLyricsAligner/Views").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "pyproject.toml").write_text('[project]\nversion = "0.7.0"\n', encoding="utf-8")
    (root / "src/xingyu_lyrics_aligner/__init__.py").write_text(
        '__version__ = "0.7.0"\n', encoding="utf-8"
    )
    (root / "apps/macos/XingyuLyricsAligner.xcodeproj/project.pbxproj").write_text(
        f"MARKETING_VERSION = {app_version}; CURRENT_PROJECT_VERSION = 1;\n",
        encoding="utf-8",
    )
    markers = {
        "README.md": "v0.7.0\n",
        "README.zh-CN.md": "v0.7.0\n",
        "CHANGELOG.md": "Unreleased — 0.7.0\n",
        "docs/macos-release.md": "macOS v0.7.0 release candidate\n",
        "docs/macos-runtime.md": "final 0.7.0 candidate Runtime\n",
        "docs/macos-model-management.md": "v0.7.0 native App\n",
        "docs/macos-unsigned-install.md": "v0.7.0 macOS Desktop\n",
        "docs/desktop-worker-protocol.md": '"workerVersion": "0.7.0"\n',
        "apps/macos/XingyuLyricsAligner/Views/AboutView.swift": "Development Runtime\n",
    }
    for relative_path, content in markers.items():
        (root / relative_path).write_text(content, encoding="utf-8")


def run_verifier(root: Path) -> subprocess.CompletedProcess[str]:
    script = Path(__file__).parents[1] / "scripts/verify-release-versions.py"
    return subprocess.run(
        [sys.executable, str(script), "--root", str(root)],
        text=True,
        capture_output=True,
        check=False,
    )


def test_release_version_verifier_accepts_consistent_fixture(tmp_path: Path) -> None:
    write_fixture(tmp_path)
    result = run_verifier(tmp_path)
    assert result.returncode == 0
    assert "0.7.0" in result.stdout


def test_release_version_verifier_rejects_app_drift(tmp_path: Path) -> None:
    write_fixture(tmp_path, app_version="0.6.1")
    result = run_verifier(tmp_path)
    assert result.returncode != 0
    assert "MARKETING_VERSION mismatch" in result.stderr
