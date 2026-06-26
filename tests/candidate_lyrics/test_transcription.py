from __future__ import annotations

import json
import subprocess
from argparse import Namespace
from pathlib import Path

from pytest import MonkeyPatch

from xingyu_lyrics_aligner.candidate_lyrics import transcription


def test_extract_parser_requires_audio_and_output_dir() -> None:
    parser = transcription.build_extract_parser()

    try:
        parser.parse_args([])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("parse_args should fail when required arguments are missing")


def test_clean_transcript_segments_is_conservative() -> None:
    segments = [
        transcription.TranscriptSegment(start=0.0, end=1.0, text="  终于   等到你  "),
        transcription.TranscriptSegment(start=1.0, end=2.0, text=""),
        transcription.TranscriptSegment(start=2.0, end=3.0, text=" 差点\t要错过你 "),
    ]

    assert transcription.clean_transcript_segments(segments) == "终于 等到你\n差点 要错过你\n"


def test_clean_transcript_segments_filters_suspected_metadata_by_default() -> None:
    segments = [
        transcription.TranscriptSegment(start=0.0, end=1.0, text=" 詞曲 李宗盛 "),
        transcription.TranscriptSegment(start=1.0, end=2.0, text=" 声声慢 "),
    ]

    assert transcription.clean_transcript_segments(segments) == "声声慢\n"
    assert (
        transcription.clean_transcript_segments(segments, keep_suspected_metadata=True)
        == "詞曲 李宗盛\n声声慢\n"
    )
    assert transcription.suspected_metadata_segments(segments) == [
        {"start": 0.0, "end": 1.0, "text": "詞曲 李宗盛"}
    ]


def test_extract_candidate_lyrics_creates_output_dir_and_writes_outputs(tmp_path: Path) -> None:
    audio = tmp_path / "song.flac"
    audio.write_bytes(b"fake audio")
    output_dir = tmp_path / "out"

    def fake_separator(audio_path: Path, output_path: Path) -> Path:
        assert audio_path == audio
        vocals = output_path / "vocals.wav"
        vocals.write_bytes(b"fake vocals")
        return vocals

    def fake_transcriber(
        audio_path: Path,
        *,
        model_name: str,
        language: str | None,
        device: str,
        vad_filter: bool,
        condition_on_previous_text: bool,
    ) -> object:
        assert audio_path == output_dir / "vocals.wav"
        assert model_name == "tiny"
        assert language == "zh"
        assert device == "cpu"
        assert vad_filter is True
        assert condition_on_previous_text is False
        return transcription.TranscriptionResult(
            segments=[transcription.TranscriptSegment(start=0.0, end=1.0, text="  你好  ")],
            detected_language="zh",
        )

    args = Namespace(
        audio=audio,
        output_dir=output_dir,
        language="zh",
        model="tiny",
        device="cpu",
        skip_separation=False,
        no_vad=False,
        condition_on_previous_text=False,
        keep_suspected_metadata=False,
        keep_intermediates=True,
    )

    report = transcription.extract_candidate_lyrics(
        args,
        separator=fake_separator,
        transcriber=fake_transcriber,
    )

    assert output_dir.exists()
    assert (output_dir / "vocals.wav").exists()
    assert (output_dir / "transcript.raw.txt").read_text(encoding="utf-8") == "你好\n"
    assert (output_dir / "transcript.cleaned.txt").read_text(encoding="utf-8") == "你好\n"
    assert json.loads((output_dir / "transcript.segments.json").read_text(encoding="utf-8")) == [
        {"start": 0.0, "end": 1.0, "text": "  你好  ", "words": []}
    ]
    assert report["separation_enabled"] is True
    assert report["asr_options"]["vad_filter"] is True
    assert report["asr_options"]["condition_on_previous_text"] is False


def test_report_json_serialization(tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    report = {
        "input_audio": "歌曲.flac",
        "warnings": ["ASR 候选歌词"],
        "outputs": {"report": str(report_path)},
    }

    transcription.write_report_json(report, report_path)

    assert json.loads(report_path.read_text(encoding="utf-8"))["input_audio"] == "歌曲.flac"


def test_skip_separation_transcribes_original_audio(tmp_path: Path) -> None:
    audio = tmp_path / "song.flac"
    audio.write_bytes(b"fake audio")
    output_dir = tmp_path / "out"

    def fail_separator(audio_path: Path, output_path: Path) -> Path:
        raise AssertionError("separator should not be called")

    def fake_transcriber(
        audio_path: Path,
        *,
        model_name: str,
        language: str | None,
        device: str,
        vad_filter: bool,
        condition_on_previous_text: bool,
    ) -> object:
        assert audio_path == audio.resolve()
        return transcription.TranscriptionResult(
            segments=[transcription.TranscriptSegment(start=0.0, end=1.0, text="candidate")],
            detected_language="en",
        )

    args = Namespace(
        audio=audio,
        output_dir=output_dir,
        language=None,
        model="base",
        device="auto",
        skip_separation=True,
        no_vad=False,
        condition_on_previous_text=False,
        keep_suspected_metadata=False,
        keep_intermediates=False,
    )

    report = transcription.extract_candidate_lyrics(
        args,
        separator=fail_separator,
        transcriber=fake_transcriber,
    )

    assert report["separation_enabled"] is False
    assert report["outputs"]["vocals"] is None
    assert "已跳过 Demucs 人声分离" in report["warnings"][1]


def test_missing_audio_file_error_message(tmp_path: Path) -> None:
    args = Namespace(
        audio=tmp_path / "missing.flac",
        output_dir=tmp_path / "out",
        language=None,
        model="base",
        device="cpu",
        skip_separation=True,
        no_vad=False,
        condition_on_previous_text=False,
        keep_suspected_metadata=False,
        keep_intermediates=False,
    )

    try:
        transcription.extract_candidate_lyrics(args)
    except transcription.CandidateLyricsError as exc:
        assert "音频文件不存在" in str(exc)
    else:
        raise AssertionError("missing audio should raise CandidateLyricsError")


def test_demucs_torchcodec_error_is_actionable(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    audio = tmp_path / "song.flac"
    audio.write_bytes(b"fake audio")

    monkeypatch.setattr(transcription.shutil, "which", lambda name: "/fake/bin/demucs")

    def fail_run(command: list[str], check: bool, stderr: object, text: bool) -> object:
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=command,
            stderr="ImportError: TorchCodec is required for save_with_torchcodec.",
        )

    monkeypatch.setattr(transcription.subprocess, "run", fail_run)

    try:
        transcription.separate_vocals_with_demucs(audio, tmp_path / "out")
    except transcription.CandidateLyricsError as exc:
        message = str(exc)
        assert "缺少 TorchCodec" in message
        assert "python -m pip install torchcodec" in message
    else:
        raise AssertionError("TorchCodec failure should raise CandidateLyricsError")
