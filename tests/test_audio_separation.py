from __future__ import annotations

from pathlib import Path

import pytest
from pytest import MonkeyPatch

from xingyu_lyrics_aligner import audio_separation
from xingyu_lyrics_aligner.audio_separation import (
    AudioSeparationError,
    export_separated_audio,
    separate_vocals_and_accompaniment,
)


def fake_demucs_process(*, missing: str | None = None, commands: list[list[str]] | None = None):
    class Process:
        returncode = 0

        def __init__(self, command: list[str], **_: object) -> None:
            if commands is not None:
                commands.append(command)
            self.command = command

        def communicate(self) -> tuple[str, str]:
            command = self.command
            output_root = Path(command[command.index("-o") + 1])
            audio = Path(command[-1])
            stem_dir = output_root / "htdemucs" / audio.stem
            stem_dir.mkdir(parents=True)
            if missing != "vocals.wav":
                (stem_dir / "vocals.wav").write_bytes(b"vocals")
            if missing != "no_vocals.wav":
                (stem_dir / "no_vocals.wav").write_bytes(b"accompaniment")
            return "", ""

        def poll(self) -> int | None:
            return self.returncode

        def terminate(self) -> None:
            self.returncode = -15

        def kill(self) -> None:
            self.returncode = -9

        def wait(self, timeout: float | None = None) -> int:
            return self.returncode

    return Process


@pytest.fixture(autouse=True)
def installed_demucs(monkeypatch: MonkeyPatch) -> None:
    """Keep subprocess tests independent of the optional package installed on the host."""

    monkeypatch.setattr(audio_separation.importlib.util, "find_spec", lambda name: object())


def test_separation_reports_missing_optional_demucs(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(audio_separation.importlib.util, "find_spec", lambda name: None)

    with pytest.raises(AudioSeparationError, match="Demucs is not installed"):
        separate_vocals_and_accompaniment(tmp_path / "song.wav", tmp_path / "work")


def test_separation_finds_both_tracks_with_unicode_and_spaces(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    audio = tmp_path / "中文 歌曲.flac"
    audio.write_bytes(b"audio")
    monkeypatch.setattr(audio_separation.subprocess, "Popen", fake_demucs_process())

    result = separate_vocals_and_accompaniment(audio, tmp_path / "工作 目录")

    assert result.vocals.name == "vocals.wav"
    assert result.accompaniment.name == "no_vocals.wav"


def test_separation_removes_stale_models_and_uses_default_model(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    audio = tmp_path / "song.flac"
    audio.write_bytes(b"audio")
    work = tmp_path / "work"
    stale = work / "_demucs" / "htdemucs_6s" / audio.stem
    stale.mkdir(parents=True)
    (stale / "vocals.wav").write_bytes(b"stale vocals")
    (stale / "no_vocals.wav").write_bytes(b"stale accompaniment")
    monkeypatch.setattr(audio_separation.subprocess, "Popen", fake_demucs_process())

    result = separate_vocals_and_accompaniment(audio, work)

    assert not stale.exists()
    assert result.vocals.read_bytes() == b"vocals"
    assert result.vocals.parent.parent.name == "htdemucs"


def test_separation_uses_managed_demucs_repository_without_shell(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    audio = tmp_path / "中文 song.wav"
    audio.write_bytes(b"audio")
    repository = tmp_path / "managed repo"
    repository.mkdir()
    commands: list[list[str]] = []

    monkeypatch.setenv("XINGYU_DEMUCS_MODEL_REPO", str(repository))
    monkeypatch.setattr(
        audio_separation.subprocess, "Popen", fake_demucs_process(commands=commands)
    )

    separate_vocals_and_accompaniment(audio, tmp_path / "work")

    assert commands[0][1:6] == [
        "-m",
        "demucs",
        "--repo",
        str(repository),
        "-n",
    ]
    assert commands[0][6] == "htdemucs"
    assert commands[0][-1] == str(audio)


@pytest.mark.parametrize("missing", ["vocals.wav", "no_vocals.wav"])
def test_separation_fails_if_either_track_is_missing(
    monkeypatch: MonkeyPatch, tmp_path: Path, missing: str
) -> None:
    audio = tmp_path / "song.flac"
    audio.write_bytes(b"audio")
    monkeypatch.setattr(audio_separation.subprocess, "Popen", fake_demucs_process(missing=missing))

    with pytest.raises(AudioSeparationError, match=missing):
        separate_vocals_and_accompaniment(audio, tmp_path / "work")


def test_export_uses_stable_names_and_survives_intermediate_cleanup(tmp_path: Path) -> None:
    intermediate = tmp_path / "intermediate"
    intermediate.mkdir()
    vocals = intermediate / "vocals.wav"
    accompaniment = intermediate / "no_vocals.wav"
    vocals.write_bytes(b"vocals")
    accompaniment.write_bytes(b"accompaniment")

    files = export_separated_audio(
        audio_separation.SeparatedAudio(vocals=vocals, accompaniment=accompaniment),
        tmp_path / "result",
        export_vocals=True,
        export_accompaniment=True,
    )
    audio_separation.shutil.rmtree(intermediate)

    assert files["vocals"].read_bytes() == b"vocals"
    assert files["vocals"].as_posix().endswith("result/audio/vocals.wav")
    assert files["accompaniment"].read_bytes() == b"accompaniment"
    assert files["accompaniment"].as_posix().endswith("result/audio/accompaniment.wav")
