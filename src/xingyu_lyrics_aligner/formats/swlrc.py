"""SWLRC v1 parser, serializer, and validator."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

SwlrcTokenization = Literal["char", "word", "mixed"]

_SUPPORTED_TOKENIZATIONS = {"char", "word", "mixed"}
_TIME_RE = re.compile(r"^(?P<minute>\d{2}):(?P<second>\d{2})\.(?P<millisecond>\d{3})$")
_HEADER_RE = re.compile(r"^\[(?P<key>[A-Za-z][A-Za-z0-9_-]*):(?P<value>.*)\]$")
_LINE_RE = re.compile(r"^\[(?P<start>[^,\]]+),(?P<end>[^\]]+)\]$")
_TOKEN_RE = re.compile(r"^<(?P<start>[^,>]+),(?P<end>[^>]+)>(?P<text>.*)$")


class SwlrcSyntaxError(ValueError):
    """Raised when SWLRC text cannot be parsed."""


class SwlrcValidationError(ValueError):
    """Raised when a parsed SWLRC document violates required v1 semantics."""

    def __init__(self, result: SwlrcValidationResult) -> None:
        self.result = result
        messages = "; ".join(diagnostic.message for diagnostic in result.errors)
        super().__init__(messages or "Invalid SWLRC document")


class SwlrcSeverity(StrEnum):
    """Validation diagnostic severity."""

    ERROR = "error"
    WARNING = "warning"


class SwlrcDiagnostic(BaseModel):
    """One parser or validator diagnostic."""

    severity: SwlrcSeverity
    code: str
    message: str
    line_number: int | None = None


class SwlrcValidationResult(BaseModel):
    """SWLRC validation result with hard errors and semantic warnings."""

    errors: list[SwlrcDiagnostic] = Field(default_factory=list)
    warnings: list[SwlrcDiagnostic] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Return true when no hard validation errors were found."""

        return not self.errors


class SwlrcToken(BaseModel):
    """One timed lyric token."""

    text: str
    start_ms: int
    end_ms: int
    line_number: int | None = None


class SwlrcLine(BaseModel):
    """One timed lyric line containing zero or more timed tokens."""

    start_ms: int
    end_ms: int
    tokens: list[SwlrcToken] = Field(default_factory=list)
    line_number: int | None = None

    @property
    def text(self) -> str:
        """Return display text reconstructed from tokens."""

        return "".join(token.text for token in self.tokens)


class SwlrcDocument(BaseModel):
    """SWLRC v1 document model."""

    version: int = 1
    offset_ms: int = 0
    tokenization: SwlrcTokenization
    metadata: dict[str, str] = Field(default_factory=dict)
    lines: list[SwlrcLine] = Field(default_factory=list)


def parse_swlrc(text: str) -> SwlrcDocument:
    """Parse and validate SWLRC v1 text."""

    physical_lines = text.splitlines()
    if not physical_lines or physical_lines[0].removeprefix("\ufeff") != "[swlrc:1]":
        raise SwlrcSyntaxError("SWLRC v1 files must start with [swlrc:1]")

    metadata: dict[str, str] = {}
    offset_ms: int | None = None
    tokenization: str | None = None
    lyric_lines: list[SwlrcLine] = []
    current_line: SwlrcLine | None = None

    for line_number, raw_line in enumerate(physical_lines[1:], start=2):
        line = raw_line.strip()
        if not line:
            continue

        line_match = _LINE_RE.fullmatch(line)
        if line_match:
            current_line = SwlrcLine(
                start_ms=_parse_time(line_match.group("start"), line_number),
                end_ms=_parse_time(line_match.group("end"), line_number),
                line_number=line_number,
            )
            lyric_lines.append(current_line)
            continue

        token_match = _TOKEN_RE.fullmatch(line)
        if token_match:
            if current_line is None:
                raise SwlrcSyntaxError(f"Line {line_number}: token appears before a lyric line")
            current_line.tokens.append(
                SwlrcToken(
                    start_ms=_parse_time(token_match.group("start"), line_number),
                    end_ms=_parse_time(token_match.group("end"), line_number),
                    text=token_match.group("text"),
                    line_number=line_number,
                )
            )
            continue

        header_match = _HEADER_RE.fullmatch(line)
        if header_match:
            key = header_match.group("key")
            value = header_match.group("value")
            if key == "swlrc":
                raise SwlrcSyntaxError(
                    f"Line {line_number}: [swlrc:1] is only valid as the first line"
                )
            if key == "offset":
                offset_ms = _parse_integer(value, key, line_number)
            elif key == "tokenization":
                tokenization = value
            else:
                metadata[key] = value
            continue

        raise SwlrcSyntaxError(f"Line {line_number}: invalid SWLRC syntax")

    if offset_ms is None:
        raise SwlrcSyntaxError("Missing required [offset:...] header")
    if tokenization is None:
        raise SwlrcSyntaxError("Missing required [tokenization:...] header")
    if tokenization not in _SUPPORTED_TOKENIZATIONS:
        raise SwlrcSyntaxError(f"Unsupported SWLRC tokenization: {tokenization}")

    document = SwlrcDocument(
        offset_ms=offset_ms,
        tokenization=tokenization,  # type: ignore[arg-type]
        metadata=metadata,
        lines=lyric_lines,
    )
    result = validate_swlrc(document)
    if not result.ok:
        raise SwlrcValidationError(result)
    return document


def serialize_swlrc(document: SwlrcDocument) -> str:
    """Serialize a SWLRC v1 document to normalized UTF-8 text."""

    result = validate_swlrc(document)
    if not result.ok:
        raise SwlrcValidationError(result)

    output = ["[swlrc:1]"]
    for key in ("title", "artist", "album", "duration", "language"):
        value = document.metadata.get(key)
        if value is not None:
            output.append(f"[{key}:{value}]")
    for key, value in document.metadata.items():
        if key not in {"title", "artist", "album", "duration", "language"}:
            output.append(f"[{key}:{value}]")
    output.append(f"[offset:{document.offset_ms}]")
    output.append(f"[tokenization:{document.tokenization}]")
    for line in document.lines:
        output.append(f"[{_format_time(line.start_ms)},{_format_time(line.end_ms)}]")
        for token in line.tokens:
            output.append(f"<{_format_time(token.start_ms)},{_format_time(token.end_ms)}>{token.text}")
    return "\n".join(output) + "\n"


def validate_swlrc(
    document: SwlrcDocument,
    *,
    allow_token_overlap: bool = True,
    duration_tolerance_ms: int = 1000,
) -> SwlrcValidationResult:
    """Validate a SWLRC document and return errors plus semantic warnings."""

    result = SwlrcValidationResult()
    if document.version != 1:
        result.errors.append(
            _diagnostic("unsupported_version", f"Unsupported SWLRC version: {document.version}")
        )
    if document.tokenization not in _SUPPORTED_TOKENIZATIONS:
        result.errors.append(
            _diagnostic(
                "unsupported_tokenization",
                f"Unsupported SWLRC tokenization: {document.tokenization}",
            )
        )

    max_end_ms = 0
    for line_index, line in enumerate(document.lines):
        if line.start_ms >= line.end_ms:
            result.errors.append(
                _diagnostic(
                    "invalid_line_range",
                    "Line start time must be earlier than line end time",
                    line.line_number,
                )
            )
        max_end_ms = max(max_end_ms, line.end_ms)

        previous_start_ms: int | None = None
        previous_end_ms: int | None = None
        for token in line.tokens:
            if not line.start_ms <= token.start_ms < token.end_ms <= line.end_ms:
                result.errors.append(
                    _diagnostic(
                        "token_out_of_line_range",
                        "Token time must satisfy line.start <= token.start < token.end <= line.end",
                        token.line_number,
                    )
                )
            if previous_start_ms is not None and token.start_ms < previous_start_ms:
                result.errors.append(
                    _diagnostic(
                        "token_start_order",
                        "Tokens in the same line must be ordered by non-decreasing start time",
                        token.line_number,
                    )
                )
            if previous_end_ms is not None and token.start_ms < previous_end_ms:
                diagnostic = _diagnostic(
                    "token_overlap",
                    f"Token overlaps the previous token in lyric line {line_index + 1}",
                    token.line_number,
                    severity=SwlrcSeverity.WARNING if allow_token_overlap else SwlrcSeverity.ERROR,
                )
                if allow_token_overlap:
                    result.warnings.append(diagnostic)
                else:
                    result.errors.append(diagnostic)
            previous_start_ms = token.start_ms
            previous_end_ms = token.end_ms

    duration_value = document.metadata.get("duration")
    if duration_value is not None:
        try:
            duration_ms = _parse_integer(duration_value, "duration", None)
        except SwlrcSyntaxError as exc:
            result.errors.append(_diagnostic("invalid_duration", str(exc)))
        else:
            effective_end_ms = max_end_ms + document.offset_ms
            if effective_end_ms > duration_ms + duration_tolerance_ms:
                result.warnings.append(
                    _diagnostic(
                        "duration_exceeded",
                        "Lyric timing extends beyond duration plus tolerance",
                        severity=SwlrcSeverity.WARNING,
                    )
                )

    return result


def _parse_time(value: str, line_number: int | None) -> int:
    match = _TIME_RE.fullmatch(value)
    if match is None:
        location = f"Line {line_number}: " if line_number is not None else ""
        raise SwlrcSyntaxError(f"{location}invalid time format: {value}")
    minute = int(match.group("minute"))
    second = int(match.group("second"))
    millisecond = int(match.group("millisecond"))
    if second >= 60:
        location = f"Line {line_number}: " if line_number is not None else ""
        raise SwlrcSyntaxError(f"{location}invalid time seconds: {value}")
    return ((minute * 60) + second) * 1000 + millisecond


def _format_time(value_ms: int) -> str:
    if value_ms < 0:
        raise SwlrcValidationError(
            SwlrcValidationResult(
                errors=[
                    _diagnostic(
                        "negative_time",
                        "SWLRC file-local timestamps must be greater than or equal to zero",
                    )
                ]
            )
        )
    total_seconds, millisecond = divmod(value_ms, 1000)
    minute, second = divmod(total_seconds, 60)
    return f"{minute:02d}:{second:02d}.{millisecond:03d}"


def _parse_integer(value: str, key: str, line_number: int | None) -> int:
    try:
        return int(value)
    except ValueError as exc:
        location = f"Line {line_number}: " if line_number is not None else ""
        raise SwlrcSyntaxError(f"{location}[{key}:...] must be an integer") from exc


def _diagnostic(
    code: str,
    message: str,
    line_number: int | None = None,
    *,
    severity: SwlrcSeverity = SwlrcSeverity.ERROR,
) -> SwlrcDiagnostic:
    return SwlrcDiagnostic(
        severity=severity,
        code=code,
        message=message,
        line_number=line_number,
    )
