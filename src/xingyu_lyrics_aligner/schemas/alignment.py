"""Stable public alignment output schemas for v0.1.1."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class AlignmentStatus(StrEnum):
    """Line-level timing status."""

    ALIGNED = "aligned"
    PARTIAL = "partial"
    MISSING_TIMESTAMPS = "missing_timestamps"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"
    UNMATCHED = "unmatched"


class AlignmentToken(BaseModel):
    """One display token with timing derived from aligned characters."""

    text: str
    start: float | None = None
    end: float | None = None
    estimated: bool = False


class AlignmentLine(BaseModel):
    """One trusted lyric line with line and token timestamps."""

    index: int
    text: str
    start: float | None = None
    end: float | None = None
    status: AlignmentStatus
    warnings: list[str] = Field(default_factory=list)
    tokens: list[AlignmentToken] = Field(default_factory=list)
    section_id: str | None = None
    section_kind: str | None = None


class AlignmentSource(BaseModel):
    """Source and runtime metadata stored with alignment.json."""

    audio_name: str
    alignment_engine: str = "whisperx_ctc"
    alignment_model: str
    requested_device: str
    actual_alignment_device: str


class AlignmentDocument(BaseModel):
    """Core v0.1.1 output consumed by later UI/highlighting work."""

    version: int = 1
    language: str
    source: AlignmentSource
    lines: list[AlignmentLine]
    warnings: list[str] = Field(default_factory=list)


class ReportDocument(BaseModel):
    """Compact run report without full lyric text or raw model output."""

    version: int = 1
    language: str
    source: AlignmentSource
    line_count: int
    aligned_or_partial_lines: int
    input_alignment_characters: int
    timed_character_entries: int
    missing_character_timestamps: int
    character_count_matches: bool
    non_monotonic_line_count: int
    status_counts: dict[str, int]
    warnings: list[str] = Field(default_factory=list)
