from __future__ import annotations

from pathlib import Path

import pytest

from xingyu_lyrics_aligner.formats.swlrc import (
    SwlrcDocument,
    SwlrcLine,
    SwlrcSyntaxError,
    SwlrcToken,
    SwlrcValidationError,
    parse_swlrc,
    serialize_swlrc,
    validate_swlrc,
)

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "docs" / "examples"


def read_example(name: str) -> str:
    return (EXAMPLES / name).read_text(encoding="utf-8")


def test_chinese_char_example_parses() -> None:
    document = parse_swlrc(read_example("swlrc-char-example.swlrc"))

    assert document.tokenization == "char"
    assert document.metadata["title"] == "终于等到你"
    assert document.lines[0].text == "终于等到你"
    assert document.lines[0].tokens[0].start_ms == 82450


def test_english_word_example_parses() -> None:
    document = parse_swlrc(read_example("swlrc-word-example.swlrc"))

    assert document.tokenization == "word"
    assert document.metadata["language"] == "en-US"
    assert document.lines[0].text == "Softmorninglight"


def test_mixed_example_parses() -> None:
    document = parse_swlrc(read_example("swlrc-mixed-example.swlrc"))

    assert document.tokenization == "mixed"
    assert [token.text for token in document.lines[0].tokens] == ["星", "光", "Hello", "you"]


def test_missing_swlrc_header_is_syntax_error() -> None:
    with pytest.raises(SwlrcSyntaxError, match=r"\[swlrc:1\]"):
        parse_swlrc("[offset:0]\n[tokenization:char]\n")


def test_invalid_time_format_is_syntax_error() -> None:
    text = "[swlrc:1]\n[offset:0]\n[tokenization:char]\n[1:02.000,01:03.000]\n"

    with pytest.raises(SwlrcSyntaxError, match="invalid time format"):
        parse_swlrc(text)


def test_line_start_must_be_before_end() -> None:
    text = "[swlrc:1]\n[offset:0]\n[tokenization:char]\n[00:02.000,00:02.000]\n"

    with pytest.raises(SwlrcValidationError) as exc_info:
        parse_swlrc(text)

    assert exc_info.value.result.errors[0].code == "invalid_line_range"


def test_token_outside_line_range_is_error() -> None:
    text = (
        "[swlrc:1]\n"
        "[offset:0]\n"
        "[tokenization:char]\n"
        "[00:02.000,00:03.000]\n"
        "<00:01.900,00:02.100>你\n"
    )

    with pytest.raises(SwlrcValidationError) as exc_info:
        parse_swlrc(text)

    assert exc_info.value.result.errors[0].code == "token_out_of_line_range"


def test_token_start_order_is_error() -> None:
    text = (
        "[swlrc:1]\n"
        "[offset:0]\n"
        "[tokenization:char]\n"
        "[00:02.000,00:04.000]\n"
        "<00:03.000,00:03.500>你\n"
        "<00:02.500,00:02.800>好\n"
    )

    with pytest.raises(SwlrcValidationError) as exc_info:
        parse_swlrc(text)

    assert any(error.code == "token_start_order" for error in exc_info.value.result.errors)


@pytest.mark.parametrize("offset", [250, -250])
def test_offset_accepts_positive_and_negative_values(offset: int) -> None:
    text = f"[swlrc:1]\n[offset:{offset}]\n[tokenization:char]\n[00:00.000,00:01.000]\n"

    document = parse_swlrc(text)

    assert document.offset_ms == offset


def test_utf8_chinese_text_round_trips() -> None:
    document = parse_swlrc(read_example("swlrc-char-example.swlrc"))
    serialized = serialize_swlrc(document)

    assert "终于等到你" in serialized
    assert parse_swlrc(serialized) == document


def test_unknown_metadata_is_preserved() -> None:
    text = (
        "[swlrc:1]\n"
        "[x-custom:kept]\n"
        "[offset:0]\n"
        "[tokenization:char]\n"
        "[00:00.000,00:01.000]\n"
    )

    document = parse_swlrc(text)

    assert document.metadata["x-custom"] == "kept"
    assert "[x-custom:kept]" in serialize_swlrc(document)


def test_unknown_tokenization_is_syntax_error() -> None:
    text = "[swlrc:1]\n[offset:0]\n[tokenization:syllable]\n"

    with pytest.raises(SwlrcSyntaxError, match="Unsupported SWLRC tokenization"):
        parse_swlrc(text)


def test_token_overlap_is_warning_by_default_and_error_in_strict_mode() -> None:
    document = SwlrcDocument(
        tokenization="char",
        lines=[
            SwlrcLine(
                start_ms=0,
                end_ms=1000,
                tokens=[
                    SwlrcToken(text="你", start_ms=0, end_ms=700),
                    SwlrcToken(text="好", start_ms=500, end_ms=1000),
                ],
            )
        ],
    )

    tolerant = validate_swlrc(document)
    strict = validate_swlrc(document, allow_token_overlap=False)

    assert tolerant.ok
    assert tolerant.warnings[0].code == "token_overlap"
    assert not strict.ok
    assert strict.errors[0].code == "token_overlap"


def test_duration_exceeded_is_warning() -> None:
    document = SwlrcDocument(
        tokenization="char",
        metadata={"duration": "1000"},
        lines=[SwlrcLine(start_ms=0, end_ms=2500)],
    )

    result = validate_swlrc(document)

    assert result.ok
    assert result.warnings[0].code == "duration_exceeded"
