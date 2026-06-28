from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from pytest import MonkeyPatch

from xingyu_lyrics_aligner.alignment.backmap import CharacterTiming
from xingyu_lyrics_aligner.alignment.ctc import DeviceResolution
from xingyu_lyrics_aligner.alignment.pipeline import AlignRequest, run_alignment
from xingyu_lyrics_aligner.device import DeviceStrategy


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
