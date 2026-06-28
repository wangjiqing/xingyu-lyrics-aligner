from __future__ import annotations

from xingyu_lyrics_aligner.alignment.swlrc_exporter import build_swlrc_document
from xingyu_lyrics_aligner.formats.swlrc import parse_swlrc, serialize_swlrc
from xingyu_lyrics_aligner.schemas.alignment import (
    AlignmentDocument,
    AlignmentLine,
    AlignmentSource,
    AlignmentStatus,
    AlignmentToken,
)


def source() -> AlignmentSource:
    return AlignmentSource(
        audio_name="song.wav",
        alignment_model="fake",
        requested_device="cpu",
        actual_alignment_device="cpu",
    )


def test_chinese_tokens_export_as_valid_char_swlrc() -> None:
    alignment = AlignmentDocument(
        language="zh",
        source=source(),
        lines=[
            AlignmentLine(
                index=0,
                text="终于等到你",
                start=82.45,
                end=83.65,
                status=AlignmentStatus.ALIGNED,
                tokens=[
                    AlignmentToken(text="终", start=82.45, end=82.68),
                    AlignmentToken(text="于", start=82.68, end=82.87),
                    AlignmentToken(text="等", start=82.87, end=83.12),
                    AlignmentToken(text="到", start=83.12, end=83.40),
                    AlignmentToken(text="你", start=83.40, end=83.65),
                ],
            )
        ],
    )

    result = build_swlrc_document(alignment)
    serialized = serialize_swlrc(result.document)
    parsed = parse_swlrc(serialized)

    assert parsed.tokenization == "char"
    assert parsed.lines[0].text == "终于等到你"
    assert parsed.lines[0].tokens[0].start_ms == 82450
    assert result.stats.estimated_token_count == 0


def test_english_word_tokens_export_as_valid_word_swlrc() -> None:
    alignment = AlignmentDocument(
        language="en",
        source=source(),
        lines=[
            AlignmentLine(
                index=0,
                text="Soft morning light",
                start=1.0,
                end=2.5,
                status=AlignmentStatus.ALIGNED,
                tokens=[
                    AlignmentToken(text="Soft", start=1.0, end=1.4),
                    AlignmentToken(text="morning", start=1.4, end=2.0),
                    AlignmentToken(text="light", start=2.0, end=2.5),
                ],
            )
        ],
    )

    result = build_swlrc_document(alignment)
    parsed = parse_swlrc(serialize_swlrc(result.document))

    assert parsed.tokenization == "word"
    assert [token.text for token in parsed.lines[0].tokens] == ["Soft", "morning", "light"]
    assert result.stats.token_count == 3


def test_missing_token_timing_is_estimated_from_line_range() -> None:
    alignment = AlignmentDocument(
        language="zh",
        source=source(),
        lines=[
            AlignmentLine(
                index=0,
                text="星语",
                start=10.0,
                end=11.0,
                status=AlignmentStatus.PARTIAL,
                tokens=[
                    AlignmentToken(text="星", start=None, end=None, estimated=True),
                    AlignmentToken(text="语", start=None, end=None, estimated=True),
                ],
            )
        ],
    )

    result = build_swlrc_document(alignment)
    parsed = parse_swlrc(serialize_swlrc(result.document))

    assert [(token.start_ms, token.end_ms) for token in parsed.lines[0].tokens] == [
        (10000, 10500),
        (10500, 11000),
    ]
    assert result.stats.estimated_token_count == 2


def test_missing_line_timing_is_skipped_and_reported() -> None:
    alignment = AlignmentDocument(
        language="zh",
        source=source(),
        lines=[
            AlignmentLine(
                index=0,
                text="星语",
                start=None,
                end=None,
                status=AlignmentStatus.MISSING_TIMESTAMPS,
                tokens=[AlignmentToken(text="星", start=None, end=None)],
            )
        ],
    )

    result = build_swlrc_document(alignment)

    assert result.document.lines == []
    assert result.stats.skipped_line_count == 1
    assert result.stats.warnings == ["swlrc_skipped_line:0:missing_line_timing"]
