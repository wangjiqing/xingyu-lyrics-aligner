"""Map character timestamps back to display tokens and lyric lines."""

from __future__ import annotations

from dataclasses import dataclass

from xingyu_lyrics_aligner.alignment.text import LineSpec, TokenSpec
from xingyu_lyrics_aligner.schemas.alignment import AlignmentLine, AlignmentStatus, AlignmentToken


@dataclass(frozen=True)
class CharacterTiming:
    """One aligned character returned by a CTC aligner."""

    text: str
    start: float | None = None
    end: float | None = None
    score: float | None = None


def token_from_chars(token: TokenSpec, chars: list[CharacterTiming]) -> AlignmentToken:
    """Create a display token timestamp from its alignment characters."""
    timed = [char for char in chars if char.start is not None and char.end is not None]
    if not timed:
        return AlignmentToken(
            text=token.text,
            start=None,
            end=None,
            estimated=token.alignment_length > 0,
        )
    return AlignmentToken(text=token.text, start=timed[0].start, end=timed[-1].end)


def backfill_lines(
    line_specs: list[LineSpec],
    char_entries: list[CharacterTiming],
    *,
    foreground_switch_lines: set[int] | None = None,
    section_id: str | None = None,
    section_kind: str | None = None,
) -> tuple[list[AlignmentLine], list[str]]:
    """Backfill aligned character timings to trusted lyric lines."""
    foreground_switch_lines = foreground_switch_lines or set()
    lines_out: list[AlignmentLine] = []
    warnings: list[str] = []
    cursor = 0
    previous_end: float | None = None

    for spec in line_specs:
        line_length = len(spec.alignment_text)
        line_chars = char_entries[cursor : cursor + line_length]
        cursor += len(line_chars)

        token_outputs: list[AlignmentToken] = []
        token_cursor = 0
        for token in spec.tokens:
            token_chars = line_chars[token_cursor : token_cursor + token.alignment_length]
            token_cursor += len(token_chars)
            token_outputs.append(token_from_chars(token, token_chars))

        line_warnings: list[str] = []
        missing_chars = sum(1 for char in line_chars if char.start is None or char.end is None)
        if missing_chars:
            line_warnings.append("missing_character_timestamps")
        if len(line_chars) != line_length:
            line_warnings.append("character_count_mismatch")
        if spec.index in foreground_switch_lines or section_kind == "foreground_voice_switch":
            line_warnings.append("foreground_voice_switch")

        timed_tokens = [token for token in token_outputs if token.start is not None]
        if not timed_tokens:
            status = (
                AlignmentStatus.UNMATCHED
                if line_length == 0
                else AlignmentStatus.MISSING_TIMESTAMPS
            )
            line_warnings.append("line_without_timing")
            start = None
            end = None
        else:
            status = AlignmentStatus.PARTIAL if missing_chars else AlignmentStatus.ALIGNED
            start = timed_tokens[0].start
            end = timed_tokens[-1].end
            if previous_end is not None and start is not None and start < previous_end:
                line_warnings.append("timing_non_monotonic")
                warnings.append("timing_non_monotonic")
                status = AlignmentStatus.MANUAL_REVIEW_REQUIRED
            if start is not None and end is not None:
                duration = end - start
                chars = max(line_length, 1)
                if duration > 12.0 or duration / chars > 1.2:
                    line_warnings.append("duration_outlier")
            if end is not None:
                previous_end = max(previous_end if previous_end is not None else end, end)

        lines_out.append(
            AlignmentLine(
                index=spec.index,
                text=spec.text,
                start=start,
                end=end,
                status=status,
                warnings=line_warnings,
                tokens=token_outputs,
                section_id=section_id,
                section_kind=section_kind,
            )
        )

    if cursor != len(char_entries):
        warnings.append("character_count_mismatch")
    return lines_out, warnings
