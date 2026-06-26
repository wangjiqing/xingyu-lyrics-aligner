from __future__ import annotations

from pathlib import Path

from pytest import MonkeyPatch
from typer.testing import CliRunner

from xingyu_lyrics_aligner import __version__
from xingyu_lyrics_aligner.alignment.models import (
    AlignmentModelPullResult,
    AlignmentModelStatus,
)
from xingyu_lyrics_aligner.alignment.pipeline import AlignRunResult
from xingyu_lyrics_aligner.cli import app
from xingyu_lyrics_aligner.schemas.alignment import (
    AlignmentDocument,
    AlignmentSource,
    ReportDocument,
)

runner = CliRunner()


def test_doctor_smoke() -> None:
    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "Xingyu Lyrics Aligner doctor" in result.stdout
    assert "Python:" in result.stdout
    assert "FFmpeg:" in result.stdout


def test_version_command_and_option() -> None:
    command_result = runner.invoke(app, ["version"])
    option_result = runner.invoke(app, ["--version"])

    assert command_result.exit_code == 0
    assert f"xingyu-lyrics-aligner {__version__}" in command_result.stdout
    assert option_result.exit_code == 0
    assert f"xingyu-lyrics-aligner {__version__}" in option_result.stdout


def test_update_dry_run_prints_upgrade_command() -> None:
    result = runner.invoke(app, ["update", "--candidate-lyrics", "--ref", "v0.2.0"])

    assert result.exit_code == 0
    assert "Current version:" in result.stdout
    assert "pip install --upgrade" in result.stdout
    assert "xingyu-lyrics-aligner[candidate-lyrics] @ git+" in result.stdout
    assert "@v0.2.0" in result.stdout
    assert "Dry run only" in result.stdout


def test_upgrade_alias_dry_run() -> None:
    result = runner.invoke(app, ["upgrade"])

    assert result.exit_code == 0
    assert "Upgrade command:" in result.stdout


def test_models_list_smoke() -> None:
    result = runner.invoke(app, ["models", "list"])

    assert result.exit_code == 0
    assert "Known model slots" in result.stdout
    assert "forced-aligner" in result.stdout
    assert "metadata only" in result.stdout


def test_candidate_extract_cli_smoke_without_model(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    audio = tmp_path / "song.flac"
    output = tmp_path / "candidate"
    audio.write_bytes(b"fake")

    def fake_extract(args: object) -> dict[str, object]:
        values = vars(args)
        assert values["audio"] == audio
        assert values["output_dir"] == output
        assert values["language"] == "zh"
        assert values["model"] == "tiny"
        assert values["device"] == "cpu"
        return {"outputs": {"transcript_cleaned": str(output / "transcript.cleaned.txt")}}

    monkeypatch.setattr("xingyu_lyrics_aligner.cli.extract_candidate_lyrics", fake_extract)

    result = runner.invoke(
        app,
        [
            "candidate",
            "extract",
            "--audio",
            str(audio),
            "--output-dir",
            str(output),
            "--language",
            "zh",
            "--model",
            "tiny",
            "--device",
            "cpu",
            "--skip-separation",
        ],
    )

    assert result.exit_code == 0
    assert "Candidate lyrics written to" in result.stdout
    assert "not trusted lyrics" in result.stdout


def test_candidate_normalize_cli_smoke(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "transcript.cleaned.txt"
    output = tmp_path / "out"
    source.write_text("聲聲慢\n", encoding="utf-8")

    def fake_normalize(
        input_path: Path,
        *,
        output_dir: Path | None,
        target: str,
        output_name: str | None,
    ) -> dict[str, object]:
        assert input_path == source
        assert output_dir == output
        assert target == "zh-Hans"
        assert output_name is None
        return {"output": str(output / "transcript.cleaned.zh-Hans.txt")}

    monkeypatch.setattr("xingyu_lyrics_aligner.cli.normalize_transcript_script", fake_normalize)

    result = runner.invoke(
        app,
        [
            "candidate",
            "normalize",
            "--input",
            str(source),
            "--output-dir",
            str(output),
            "--to",
            "zh-Hans",
        ],
    )

    assert result.exit_code == 0
    assert "Script-normalized candidate lyrics written to" in result.stdout
    assert "not overwritten" in result.stdout


def test_models_status_smoke() -> None:
    result = runner.invoke(app, ["models", "status", "--language", "zh"])

    assert result.exit_code == 0
    assert "Local model status" in result.stdout
    assert "No model files are bundled" in result.stdout
    assert "forced-aligner" in result.stdout


def test_models_pull_smoke_without_network(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        "xingyu_lyrics_aligner.cli.alignment_model_status",
        lambda language: AlignmentModelStatus(
            language=language,
            model_name="fake/zh-model",
            available=False,
            detail="not found",
        ),
    )
    monkeypatch.setattr(
        "xingyu_lyrics_aligner.cli.pull_alignment_model",
        lambda language, device: AlignmentModelPullResult(
            language=language,
            model_name="fake/zh-model",
            actual_device="cpu",
            warnings=[],
        ),
    )

    result = runner.invoke(app, ["models", "pull", "--language", "zh"])

    assert result.exit_code == 0
    assert "No ASR transcription will run" in result.stdout
    assert "fake/zh-model" in result.stdout


def test_models_pull_network_error_is_actionable(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        "xingyu_lyrics_aligner.cli.alignment_model_status",
        lambda language: AlignmentModelStatus(
            language=language,
            model_name="fake/zh-model",
            available=False,
            detail="not found",
        ),
    )

    def fail_pull(language: str, device: object) -> AlignmentModelPullResult:
        raise RuntimeError("Cannot reach huggingface.co. Check network/DNS.")

    monkeypatch.setattr("xingyu_lyrics_aligner.cli.pull_alignment_model", fail_pull)

    result = runner.invoke(app, ["models", "pull", "--language", "zh"])

    assert result.exit_code == 2
    assert "Cannot reach huggingface.co" in result.stderr


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


def test_saved_locale_preference(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("XINGYU_ALIGN_LOCALE", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    save_result = runner.invoke(app, ["config", "set-locale", "zh-CN"])
    assert save_result.exit_code == 0
    assert "zh-CN" in save_result.stdout

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "星语歌词对齐环境检查" in result.stdout


def test_config_show_when_locale_not_set(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("XINGYU_ALIGN_LOCALE", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    result = runner.invoke(app, ["config", "show"])

    assert result.exit_code == 0
    assert "User preferences" in result.stdout
    assert "not set" in result.stdout


def test_align_missing_files_is_clear() -> None:
    result = runner.invoke(
        app,
        [
            "align",
            "--audio",
            "missing-audio.wav",
            "--lyrics",
            "missing-lyrics.txt",
            "--output-dir",
            "out",
        ],
    )

    assert result.exit_code == 2
    assert "Audio file does not exist: missing-audio.wav" in result.stderr


def test_align_help_smoke() -> None:
    result = runner.invoke(app, ["align", "--help"])

    assert result.exit_code == 0
    assert "--section-manifest" in result.stdout
    assert "--lrc-offset-ms" in result.stdout


def test_align_cli_smoke_without_model(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    audio = tmp_path / "song.wav"
    lyrics = tmp_path / "lyrics.txt"
    output = tmp_path / "out"
    audio.write_bytes(b"fake")
    lyrics.write_text("星语发光\n", encoding="utf-8")

    def fake_run_alignment(request: object) -> AlignRunResult:
        source = AlignmentSource(
            audio_name="song.wav",
            alignment_model="fake-model",
            requested_device="cpu",
            actual_alignment_device="cpu",
        )
        alignment = AlignmentDocument(language="zh", source=source, lines=[])
        report = ReportDocument(
            language="zh",
            source=source,
            line_count=0,
            aligned_or_partial_lines=0,
            input_alignment_characters=0,
            timed_character_entries=0,
            missing_character_timestamps=0,
            character_count_matches=True,
            non_monotonic_line_count=0,
            status_counts={},
        )
        return AlignRunResult(alignment=alignment, report=report, output_dir=output)

    monkeypatch.setattr("xingyu_lyrics_aligner.commands.align.run_alignment", fake_run_alignment)

    result = runner.invoke(
        app,
        [
            "align",
            "--audio",
            str(audio),
            "--lyrics",
            str(lyrics),
            "--output-dir",
            str(output),
            "--device",
            "cpu",
        ],
    )

    assert result.exit_code == 0
    assert "Alignment completed" in result.stdout
