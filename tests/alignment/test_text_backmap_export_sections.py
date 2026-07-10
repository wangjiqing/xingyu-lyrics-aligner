from __future__ import annotations

import json
from pathlib import Path

import pytest

from xingyu_lyrics_aligner.alignment.backmap import CharacterTiming, backfill_lines
from xingyu_lyrics_aligner.alignment.exporters import render_lrc
from xingyu_lyrics_aligner.alignment.sections import load_section_manifest, validate_sections
from xingyu_lyrics_aligner.alignment.text import (
    TrustedLineKind,
    build_line_specs,
    clean_alignment_text,
    parse_trusted_lyrics,
)
from xingyu_lyrics_aligner.schemas.alignment import AlignmentLine, AlignmentStatus, AlignmentToken


def test_display_text_and_alignment_text_are_separate() -> None:
    specs = build_line_specs(["妳，好～♪ 星语"])

    assert specs[0].text == "妳，好～♪ 星语"
    assert specs[0].alignment_text == "妳好星语"


def test_trusted_header_block_is_preserved_but_not_classified_as_singing(tmp_path: Path) -> None:
    lyrics = tmp_path / "lyrics.txt"
    lyrics.write_text(
        "——\n我的快乐就是想你\n作词：牛哥\n作曲：平凡人/小龙女\n——\n有个问题一直藏在我心里\n",
        encoding="utf-8",
    )
    document = parse_trusted_lyrics(lyrics)

    assert [line.kind for line in document.lines[:5]] == [TrustedLineKind.NON_LYRIC_HEADER] * 5
    assert [line.text for line in document.singing_lines] == ["有个问题一直藏在我心里"]
    assert document.lines[2].source_line_index == 2


def test_credit_words_inside_real_lyric_are_not_misclassified(tmp_path: Path) -> None:
    lyrics = tmp_path / "lyrics.txt"
    lyrics.write_text("作词的人也会流泪\n这是歌声\n", encoding="utf-8")
    document = parse_trusted_lyrics(lyrics)
    assert all(line.kind == TrustedLineKind.SINGING_LYRIC for line in document.lines)


def test_clean_alignment_text_removes_punctuation_space_music_and_brackets() -> None:
    assert clean_alignment_text(" （妳，好） ♪ 123 ") == "妳好123"


def test_ni_and_nin_are_not_rewritten() -> None:
    assert clean_alignment_text("妳") == "妳"
    assert clean_alignment_text("你") == "你"
    assert clean_alignment_text("妳") != clean_alignment_text("你")


def test_character_timestamps_backfill_to_tokens_and_line() -> None:
    specs = build_line_specs(["星语"])
    chars = [
        CharacterTiming(text="星", start=1.0, end=1.2),
        CharacterTiming(text="语", start=1.2, end=1.4),
    ]

    lines, warnings = backfill_lines(specs, chars)

    assert warnings == []
    assert lines[0].start == 1.0
    assert lines[0].end == 1.4
    assert lines[0].tokens[0].start == 1.0
    assert lines[0].tokens[-1].end == 1.4


def test_missing_character_timestamps_are_marked() -> None:
    specs = build_line_specs(["星语"])
    chars = [
        CharacterTiming(text="星", start=None, end=None),
        CharacterTiming(text="语", start=None, end=None),
    ]

    lines, _ = backfill_lines(specs, chars)

    assert lines[0].status == AlignmentStatus.MISSING_TIMESTAMPS
    assert "missing_character_timestamps" in lines[0].warnings
    assert "line_without_timing" in lines[0].warnings


def test_non_monotonic_time_adds_warning() -> None:
    specs = build_line_specs(["星", "语"])
    chars = [
        CharacterTiming(text="星", start=2.0, end=2.2),
        CharacterTiming(text="语", start=1.9, end=2.1),
    ]

    lines, warnings = backfill_lines(specs, chars)

    assert "timing_non_monotonic" in warnings
    assert lines[1].status == AlignmentStatus.MANUAL_REVIEW_REQUIRED
    assert "timing_non_monotonic" in lines[1].warnings


def test_duration_outlier_adds_warning() -> None:
    specs = build_line_specs(["星语"])
    chars = [
        CharacterTiming(text="星", start=1.0, end=2.0),
        CharacterTiming(text="语", start=2.0, end=20.0),
    ]

    lines, _ = backfill_lines(specs, chars)

    assert "duration_outlier" in lines[0].warnings


def test_lrc_format_and_offset() -> None:
    lines = [
        AlignmentLine(
            index=0,
            text="星语发光",
            start=12.34,
            end=14.0,
            status=AlignmentStatus.ALIGNED,
            tokens=[AlignmentToken(text="星", start=12.34, end=12.5)],
        )
    ]

    assert render_lrc(lines, offset_ms=500) == "[00:12.84]星语发光\n"


def test_section_manifest_valid_and_invalid_inputs(tmp_path: Path) -> None:
    manifest = tmp_path / "sections.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "line_index_base": 0,
                "line_end_inclusive": False,
                "sections": [
                    {
                        "id": "a",
                        "audio_start": 0.0,
                        "audio_end": 3.0,
                        "line_start": 0,
                        "line_end": 1,
                        "kind": "singing",
                    },
                    {
                        "id": "b",
                        "audio_start": 3.2,
                        "audio_end": 6.0,
                        "line_start": 1,
                        "line_end": 2,
                        "kind": "foreground_voice_switch",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    loaded = load_section_manifest(manifest)
    assert validate_sections(loaded.sections, line_count=2, audio_duration=6.0) == [
        "section_boundary_review"
    ]

    loaded.sections[1].line_start = 0
    with pytest.raises(ValueError, match="cover every line"):
        validate_sections(loaded.sections, line_count=2, audio_duration=6.0)
