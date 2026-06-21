from __future__ import annotations

import sys
from pathlib import Path

SPIKE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SPIKE_DIR))

from run_spike import (  # noqa: E402
    backfill_lines,
    build_line_specs,
    clean_alignment_text,
    load_section_manifest,
    parse_line_set,
)


def test_clean_alignment_text_keeps_display_distinctions_for_alignment_only() -> None:
    assert clean_alignment_text(" 妳，好～♪ 123 ") == "妳好123"
    assert clean_alignment_text("你，好～♪ 123") == "你好123"
    assert clean_alignment_text("妳") != clean_alignment_text("你")


def test_build_line_specs_records_alignment_lengths() -> None:
    specs = build_line_specs(["星语，在夜里发光！"])

    assert specs[0].text == "星语，在夜里发光！"
    assert specs[0].alignment_text == "星语在夜里发光"
    assert sum(token.alignment_length for token in specs[0].tokens) == len("星语在夜里发光")


def test_backfill_lines_maps_characters_to_lines_and_marks_voice_switch() -> None:
    specs = build_line_specs(["星语发光", "明天继续"])
    chars = [
        {"text": "星", "start": 1.0, "end": 1.1},
        {"text": "语", "start": 1.1, "end": 1.2},
        {"text": "发", "start": 1.2, "end": 1.3},
        {"text": "光", "start": 1.3, "end": 1.4},
        {"text": "明", "start": 2.0, "end": 2.1},
        {"text": "天", "start": 2.1, "end": 2.2},
        {"text": "继", "start": 2.2, "end": 2.3},
        {"text": "续", "start": 2.3, "end": 2.4},
    ]

    lines, warnings = backfill_lines(specs, chars, {0})

    assert warnings == []
    assert lines[0]["start"] == 1.0
    assert lines[0]["end"] == 1.4
    assert lines[0]["status"] == "aligned"
    assert "foreground_voice_switch" in lines[0]["warnings"]
    assert lines[1]["start"] == 2.0


def test_backfill_lines_marks_missing_timestamps() -> None:
    specs = build_line_specs(["星语"])
    chars = [
        {"text": "星", "start": None, "end": None},
        {"text": "语", "start": None, "end": None},
    ]

    lines, _ = backfill_lines(specs, chars, set())

    assert lines[0]["status"] == "missing_timestamps"
    assert "missing_character_timestamps" in lines[0]["warnings"]
    assert "line_without_timing" in lines[0]["warnings"]


def test_parse_line_set_is_one_based_with_ranges() -> None:
    assert parse_line_set("1,3-5") == {0, 2, 3, 4}


def test_load_section_manifest_uses_zero_based_exclusive_ranges(tmp_path: Path) -> None:
    manifest = tmp_path / "sections.json"
    manifest.write_text(
        """
        {
          "version": 1,
          "sections": [
            {
              "id": "before",
              "audio_start": 0.0,
              "audio_end": 10.0,
              "line_start": 0,
              "line_end": 1,
              "kind": "singing"
            },
            {
              "id": "after",
              "audio_start": 10.0,
              "audio_end": 20.0,
              "line_start": 1,
              "line_end": 3,
              "kind": "foreground_voice_switch"
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    sections = load_section_manifest(manifest, line_count=3, duration=20.0)

    assert sections[0].line_start == 0
    assert sections[0].line_end == 1
    assert sections[1].line_start == 1
    assert sections[1].line_end == 3


def test_backfill_lines_adds_section_metadata() -> None:
    specs = build_line_specs(["星语"])
    chars = [
        {"text": "星", "start": 1.0, "end": 1.1},
        {"text": "语", "start": 1.1, "end": 1.2},
    ]

    lines, _ = backfill_lines(
        specs,
        chars,
        set(),
        section_id="before_phone",
        section_kind="singing",
    )

    assert lines[0]["section_id"] == "before_phone"
    assert lines[0]["section_kind"] == "singing"
