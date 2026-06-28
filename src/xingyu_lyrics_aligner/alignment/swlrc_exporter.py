"""Convert alignment documents to SWLRC v1 documents."""

from __future__ import annotations

import re
from dataclasses import dataclass

from xingyu_lyrics_aligner.formats.swlrc import (
    SwlrcDocument,
    SwlrcLine,
    SwlrcToken,
    SwlrcTokenization,
    validate_swlrc,
)
from xingyu_lyrics_aligner.schemas.alignment import (
    AlignmentDocument,
    AlignmentLine,
    AlignmentToken,
)

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


@dataclass(frozen=True)
class SwlrcExportStats:
    """Auditable statistics for SWLRC export degradation."""

    token_count: int
    estimated_token_count: int
    skipped_line_count: int
    warnings: list[str]


@dataclass(frozen=True)
class SwlrcExportResult:
    """SWLRC document plus export statistics."""

    document: SwlrcDocument
    stats: SwlrcExportStats


@dataclass(frozen=True)
class _TokenCandidate:
    text: str
    start_ms: int | None
    end_ms: int | None
    estimated: bool = False


def build_swlrc_document(alignment: AlignmentDocument) -> SwlrcExportResult:
    """Build a validated SWLRC v1 document from a public alignment document."""

    tokenization = _detect_tokenization(alignment)
    swlrc_lines: list[SwlrcLine] = []
    estimated_token_count = 0
    skipped_line_count = 0
    warnings: list[str] = []

    for line in alignment.lines:
        if line.start is None or line.end is None or line.start >= line.end:
            skipped_line_count += 1
            warnings.append(f"swlrc_skipped_line:{line.index}:missing_line_timing")
            continue

        line_start_ms = _seconds_to_ms(line.start)
        line_end_ms = _seconds_to_ms(line.end)
        if line_start_ms >= line_end_ms:
            skipped_line_count += 1
            warnings.append(f"swlrc_skipped_line:{line.index}:invalid_line_range")
            continue

        candidates = _line_token_candidates(line, tokenization)
        if not candidates:
            candidates = _fallback_candidates_from_text(line.text, tokenization)
        if not candidates:
            skipped_line_count += 1
            warnings.append(f"swlrc_skipped_line:{line.index}:no_exportable_tokens")
            continue

        filled = estimate_missing_token_times(
            candidates,
            line_start_ms=line_start_ms,
            line_end_ms=line_end_ms,
        )
        if filled is None:
            skipped_line_count += 1
            warnings.append(f"swlrc_skipped_line:{line.index}:unrecoverable_token_timing")
            continue

        tokens = [
            SwlrcToken(text=token.text, start_ms=token.start_ms, end_ms=token.end_ms)
            for token in filled
            if token.start_ms is not None and token.end_ms is not None
        ]
        estimated_token_count += sum(1 for token in filled if token.estimated)
        swlrc_lines.append(SwlrcLine(start_ms=line_start_ms, end_ms=line_end_ms, tokens=tokens))

    document = SwlrcDocument(
        offset_ms=0,
        tokenization=tokenization,
        metadata={"language": alignment.language},
        lines=swlrc_lines,
    )
    validation = validate_swlrc(document)
    if not validation.ok:
        messages = ", ".join(error.message for error in validation.errors)
        raise ValueError(f"Generated invalid SWLRC document: {messages}")
    warnings.extend(f"swlrc_validation_warning:{warning.code}" for warning in validation.warnings)
    return SwlrcExportResult(
        document=document,
        stats=SwlrcExportStats(
            token_count=sum(len(line.tokens) for line in swlrc_lines),
            estimated_token_count=estimated_token_count,
            skipped_line_count=skipped_line_count,
            warnings=_dedupe(warnings),
        ),
    )


def estimate_missing_token_times(
    tokens: list[_TokenCandidate],
    *,
    line_start_ms: int,
    line_end_ms: int,
) -> list[_TokenCandidate] | None:
    """Fill missing token ranges from surrounding token or line boundaries."""

    if line_start_ms >= line_end_ms:
        return None
    output = list(tokens)
    index = 0
    while index < len(output):
        token = output[index]
        if token.start_ms is not None and token.end_ms is not None:
            if token.start_ms >= token.end_ms:
                return None
            index += 1
            continue

        run_start = index
        while index < len(output) and (
            output[index].start_ms is None or output[index].end_ms is None
        ):
            index += 1
        run_end = index

        left = output[run_start - 1].end_ms if run_start > 0 else line_start_ms
        right = output[run_end].start_ms if run_end < len(output) else line_end_ms
        if left is None or right is None or left >= right:
            return None

        estimated = _split_range(left, right, run_end - run_start)
        if len(estimated) != run_end - run_start:
            return None
        output[run_start:run_end] = [
            _TokenCandidate(
                text=original.text,
                start_ms=start,
                end_ms=end,
                estimated=True,
            )
            for original, (start, end) in zip(output[run_start:run_end], estimated, strict=True)
        ]

    return output


def _line_token_candidates(
    line: AlignmentLine,
    tokenization: SwlrcTokenization,
) -> list[_TokenCandidate]:
    candidates: list[_TokenCandidate] = []
    for token in line.tokens:
        if tokenization == "char" and _contains_cjk(token.text):
            candidates.extend(_split_cjk_token(token))
        else:
            text = token.text.strip()
            if text:
                candidates.append(
                    _TokenCandidate(
                        text=text,
                        start_ms=_optional_seconds_to_ms(token.start),
                        end_ms=_optional_seconds_to_ms(token.end),
                        estimated=token.estimated,
                    )
                )
    return candidates


def _split_cjk_token(token: AlignmentToken) -> list[_TokenCandidate]:
    parts = [char for char in token.text if not char.isspace()]
    if not parts:
        return []
    start_ms = _optional_seconds_to_ms(token.start)
    end_ms = _optional_seconds_to_ms(token.end)
    if start_ms is None or end_ms is None:
        return [
            _TokenCandidate(text=part, start_ms=None, end_ms=None, estimated=True) for part in parts
        ]
    if len(parts) == 1:
        return [
            _TokenCandidate(
                text=parts[0],
                start_ms=start_ms,
                end_ms=end_ms,
                estimated=token.estimated,
            )
        ]
    ranges = _split_range(start_ms, end_ms, len(parts))
    if len(ranges) != len(parts):
        return [
            _TokenCandidate(text=part, start_ms=None, end_ms=None, estimated=True) for part in parts
        ]
    return [
        _TokenCandidate(text=part, start_ms=start, end_ms=end, estimated=True)
        for part, (start, end) in zip(parts, ranges, strict=True)
    ]


def _fallback_candidates_from_text(
    text: str,
    tokenization: SwlrcTokenization,
) -> list[_TokenCandidate]:
    if tokenization == "word":
        parts = [part for part in text.split() if part]
    else:
        parts = [char for char in text if not char.isspace()]
    return [
        _TokenCandidate(text=part, start_ms=None, end_ms=None, estimated=True) for part in parts
    ]


def _detect_tokenization(alignment: AlignmentDocument) -> SwlrcTokenization:
    if alignment.language.lower().startswith("zh"):
        return "char"
    has_cjk = any(_contains_cjk(token.text) for line in alignment.lines for token in line.tokens)
    if has_cjk:
        return "mixed"
    return "word"


def _split_range(start_ms: int, end_ms: int, count: int) -> list[tuple[int, int]]:
    if count <= 0 or start_ms >= end_ms:
        return []
    duration = end_ms - start_ms
    if duration < count:
        return []
    ranges: list[tuple[int, int]] = []
    for index in range(count):
        start = start_ms + round(duration * index / count)
        end = start_ms + round(duration * (index + 1) / count)
        if start >= end:
            end = start + 1
        ranges.append((start, min(end, end_ms)))
    return ranges


def _seconds_to_ms(value: float) -> int:
    return max(0, round(value * 1000))


def _optional_seconds_to_ms(value: float | None) -> int | None:
    return None if value is None else _seconds_to_ms(value)


def _contains_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text))


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            output.append(value)
    return output
