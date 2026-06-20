from __future__ import annotations

from pytest import MonkeyPatch
from typer.testing import CliRunner

from xingyu_lyrics_aligner.cli import app

runner = CliRunner()


def test_doctor_smoke() -> None:
    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "Xingyu Lyrics Aligner doctor" in result.stdout
    assert "Python:" in result.stdout
    assert "FFmpeg:" in result.stdout


def test_models_list_smoke() -> None:
    result = runner.invoke(app, ["models", "list"])

    assert result.exit_code == 0
    assert "Known model slots" in result.stdout
    assert "forced-aligner" in result.stdout
    assert "placeholder only" in result.stdout


def test_models_status_smoke() -> None:
    result = runner.invoke(app, ["models", "status"])

    assert result.exit_code == 0
    assert "Local model status" in result.stdout
    assert "No model files are required or installed" in result.stdout


def test_locale_switch_with_option() -> None:
    result = runner.invoke(app, ["--locale", "zh-CN", "doctor"])

    assert result.exit_code == 0
    assert "星语歌词对齐环境检查" in result.stdout
    assert "操作系统" in result.stdout


def test_locale_switch_with_env_var(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("XINGYU_ALIGN_LOCALE", "zh-CN")

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "星语歌词对齐环境检查" in result.stdout


def test_align_missing_files_is_clear() -> None:
    result = runner.invoke(
        app,
        [
            "align",
            "--audio",
            "missing-audio.wav",
            "--lyrics",
            "missing-lyrics.txt",
        ],
    )

    assert result.exit_code == 2
    assert "File does not exist: missing-audio.wav" in result.stderr
    assert "File does not exist: missing-lyrics.txt" in result.stderr
