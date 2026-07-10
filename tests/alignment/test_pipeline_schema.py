from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from pytest import MonkeyPatch

from xingyu_lyrics_aligner.alignment.backmap import CharacterTiming
from xingyu_lyrics_aligner.alignment.ctc import DeviceResolution
from xingyu_lyrics_aligner.alignment.pipeline import AlignRequest, run_alignment
from xingyu_lyrics_aligner.device import DeviceStrategy
from xingyu_lyrics_aligner.formats.swlrc import parse_swlrc


class FakeAligner:
    def __init__(self, **_: object) -> None:
        self.align_model_name = "fake-ctc"
        self.device = DeviceResolution(requested="cpu", actual="cpu", warnings=[])

    def align(self, segment: object, audio: object) -> list[CharacterTiming]:
        text = segment.text
        start = segment.start
        return [
            CharacterTiming(text=char, start=start + index * 0.1, end=start + index * 0.1 + 0.05)
            for index, char in enumerate(text)
        ]


def test_global_and_sectional_pipeline_outputs_share_schema(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "xingyu_lyrics_aligner.alignment.pipeline.load_audio",
        lambda path: SimpleNamespace(samples=object(), duration_seconds=10.0),
    )
    monkeypatch.setattr(
        "xingyu_lyrics_aligner.alignment.pipeline.WhisperXCtcAligner",
        FakeAligner,
    )
    audio = tmp_path / "song.wav"
    lyrics = tmp_path / "lyrics.txt"
    audio.write_bytes(b"fake")
    lyrics.write_text("星语\n发光\n", encoding="utf-8")

    global_result = run_alignment(
        AlignRequest(
            audio=audio,
            lyrics=lyrics,
            output_dir=tmp_path / "global",
            language="zh",
            device=DeviceStrategy.CPU,
        )
    )

    manifest = tmp_path / "sections.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "line_index_base": 0,
                "line_end_inclusive": False,
                "sections": [
                    {
                        "id": "before",
                        "audio_start": 0.0,
                        "audio_end": 5.0,
                        "line_start": 0,
                        "line_end": 1,
                        "kind": "singing",
                    },
                    {
                        "id": "after",
                        "audio_start": 5.0,
                        "audio_end": 10.0,
                        "line_start": 1,
                        "line_end": 2,
                        "kind": "foreground_voice_switch",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    sectional_result = run_alignment(
        AlignRequest(
            audio=audio,
            lyrics=lyrics,
            output_dir=tmp_path / "sectional",
            language="zh",
            device=DeviceStrategy.CPU,
            section_manifest=manifest,
        )
    )

    assert global_result.alignment.model_dump()["version"] == 1
    assert sectional_result.alignment.model_dump()["version"] == 1
    assert len(global_result.alignment.lines) == len(sectional_result.alignment.lines) == 2
    assert sectional_result.alignment.lines[1].section_id == "after"
    assert "foreground_voice_switch" in sectional_result.alignment.lines[1].warnings
    assert (tmp_path / "global" / "alignment.json").exists()
    assert (tmp_path / "sectional" / "lyrics.lrc").exists()
    assert (tmp_path / "global" / "lyrics.swlrc").exists()
    assert sectional_result.files["swlrc"] == tmp_path / "sectional" / "lyrics.swlrc"


def test_pipeline_overwrite_protection_and_debug_output(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "xingyu_lyrics_aligner.alignment.pipeline.load_audio",
        lambda path: SimpleNamespace(samples=object(), duration_seconds=10.0),
    )
    monkeypatch.setattr(
        "xingyu_lyrics_aligner.alignment.pipeline.WhisperXCtcAligner",
        FakeAligner,
    )
    audio = tmp_path / "song.wav"
    lyrics = tmp_path / "lyrics.txt"
    output = tmp_path / "out"
    audio.write_bytes(b"fake")
    lyrics.write_text("星语\n", encoding="utf-8")
    output.mkdir()
    (output / "lyrics.swlrc").write_text("exists", encoding="utf-8")

    request = AlignRequest(
        audio=audio,
        lyrics=lyrics,
        output_dir=output,
        language="zh",
        device=DeviceStrategy.CPU,
    )

    try:
        run_alignment(request)
    except FileExistsError as exc:
        assert "lyrics.swlrc" in str(exc)
        assert "Use --overwrite" in str(exc)
    else:
        raise AssertionError("Expected overwrite protection")

    result = run_alignment(
        AlignRequest(
            audio=audio,
            lyrics=lyrics,
            output_dir=output,
            language="zh",
            device=DeviceStrategy.CPU,
            overwrite=True,
            debug_output=True,
        )
    )

    assert result.report.line_count == 1
    assert result.report.estimated_token_count == 2
    assert (output / "debug.summary.json").exists()


def test_header_protocol_lrc_swlrc_and_structured_outputs(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "xingyu_lyrics_aligner.alignment.pipeline.load_audio",
        lambda path: SimpleNamespace(samples=object(), duration_seconds=30.0),
    )
    monkeypatch.setattr("xingyu_lyrics_aligner.alignment.pipeline.WhisperXCtcAligner", FakeAligner)
    audio = tmp_path / "song.wav"
    lyrics = tmp_path / "lyrics.txt"
    audio.write_bytes(b"fake")
    lyrics.write_text(
        "[ti:我的快乐就是想你]\n——\n我的快乐就是想你\n作词：牛哥\n作曲：平凡人/小龙女\n——\n有个问题一直藏在我心里\n",
        encoding="utf-8",
    )
    # Start at 5 s to exercise intro presentation hints.
    manifest = tmp_path / "sections.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "line_index_base": 0,
                "line_end_inclusive": False,
                "sections": [
                    {
                        "id": "verse",
                        "audio_start": 5.0,
                        "audio_end": 30.0,
                        "line_start": 0,
                        "line_end": 1,
                        "kind": "singing",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result = run_alignment(
        AlignRequest(
            audio=audio,
            lyrics=lyrics,
            output_dir=tmp_path / "out",
            language="zh",
            device=DeviceStrategy.CPU,
            section_manifest=manifest,
        )
    )

    assert len(result.alignment.lines) == 1
    assert result.alignment.lines[0].source_line_index == 6
    assert result.report.first_aligned_lyric_start_ms == 5000
    assert len(result.report.preserved_header_lines) == 6
    assert all(not line.participated_in_alignment for line in result.report.preserved_header_lines)
    assert max(hint.suggested_end_ms for hint in result.report.presentation_hints) <= 5000
    lrc = (tmp_path / "out" / "lyrics.lrc").read_text(encoding="utf-8")
    assert lrc.startswith("[ti:我的快乐就是想你]\n——\n我的快乐就是想你\n作词：牛哥")
    assert "[00:05.00]有个问题一直藏在我心里" in lrc
    swlrc_text = (tmp_path / "out" / "lyrics.swlrc").read_text(encoding="utf-8")
    assert "作词" not in swlrc_text
    assert len(parse_swlrc(swlrc_text).lines) == 1
    alignment_json = json.loads((tmp_path / "out" / "alignment.json").read_text(encoding="utf-8"))
    assert alignment_json["preservedHeaderLines"][1]["nonAlignmentReason"] == "non_singing_header"
    assert alignment_json["preservedHeaderLines"][1]["lineClassification"] == "NON_LYRIC_HEADER"


def test_header_presentation_hints_degrade_safely_at_zero(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "xingyu_lyrics_aligner.alignment.pipeline.load_audio",
        lambda path: SimpleNamespace(samples=object(), duration_seconds=10.0),
    )
    monkeypatch.setattr("xingyu_lyrics_aligner.alignment.pipeline.WhisperXCtcAligner", FakeAligner)
    audio, lyrics = tmp_path / "song.wav", tmp_path / "lyrics.txt"
    audio.write_bytes(b"fake")
    lyrics.write_text("作词：牛哥\n第一句\n", encoding="utf-8")
    result = run_alignment(
        AlignRequest(
            audio=audio,
            lyrics=lyrics,
            output_dir=tmp_path / "zero",
            language="zh",
            device=DeviceStrategy.CPU,
        )
    )
    assert result.report.first_aligned_lyric_start_ms == 0
    assert result.report.presentation_hints == []
