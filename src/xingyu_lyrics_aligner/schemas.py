"""Pydantic models for future alignment jobs and outputs."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

from xingyu_lyrics_aligner.device import DeviceStrategy


class AlignmentMode(StrEnum):
    """Future alignment granularity modes."""

    LINE = "line"
    WORD = "word"
    CHARACTER = "character"


class ReviewStatus(StrEnum):
    """Human review state for generated timing spans."""

    UNREVIEWED = "unreviewed"
    NEEDS_REVIEW = "needs_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class JobManifest(BaseModel):
    """Future persisted job manifest."""

    audio_path: Path
    lyrics_path: Path
    audio_hash: str | None = None
    lyrics_hash: str | None = None
    device: DeviceStrategy = DeviceStrategy.AUTO
    model_version: str | None = None
    language: str | None = None
    alignment_mode: AlignmentMode = AlignmentMode.LINE
    created_time: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ModelManifest(BaseModel):
    """Metadata for a future local model package."""

    model_id: str
    name: str
    version: str
    local_path: Path | None = None
    required: bool = False
    implemented: bool = False
    license: str | None = None
    source_url: str | None = None


class TimedTextSpan(BaseModel):
    """One aligned text span at line, word, or character level."""

    text: str
    start_seconds: float
    end_seconds: float
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED


class AlignmentResult(BaseModel):
    """Internal alignment result format reserved for future engines."""

    job_id: str
    language: str | None = None
    model_version: str | None = None
    line_level: list[TimedTextSpan] = Field(default_factory=list)
    word_level: list[TimedTextSpan] = Field(default_factory=list)
    character_level: list[TimedTextSpan] = Field(default_factory=list)
    created_time: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ExportResult(BaseModel):
    """Future export metadata for LRC and JSON outputs."""

    job_id: str
    output_path: Path
    format: str
    includes_line_level: bool = False
    includes_word_level: bool = False
    includes_character_level: bool = False
    created_time: datetime = Field(default_factory=lambda: datetime.now(UTC))
