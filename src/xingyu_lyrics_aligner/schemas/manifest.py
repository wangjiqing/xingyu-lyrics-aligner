"""Section manifest schema for manual structure-aware CTC alignment."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class Section(BaseModel):
    """One manual audio/lyrics section."""

    id: str
    audio_start: float = Field(ge=0.0)
    audio_end: float
    line_start: int = Field(ge=0)
    line_end: int = Field(ge=0)
    kind: str = "singing"

    @model_validator(mode="after")
    def validate_ranges(self) -> Section:
        if self.audio_end <= self.audio_start:
            raise ValueError("audio_end must be greater than audio_start")
        if self.line_end <= self.line_start:
            raise ValueError("line_end must be greater than line_start")
        return self


class SectionManifest(BaseModel):
    """Manual section manifest.

    v0.1.1 requires 0-based, line_end-exclusive ranges that cover every lyric line.
    """

    version: int = 1
    line_index_base: int = 0
    line_end_inclusive: bool = False
    sections: list[Section]

    @model_validator(mode="after")
    def validate_manifest_conventions(self) -> SectionManifest:
        if self.version != 1:
            raise ValueError("section manifest version must be 1")
        if self.line_index_base != 0:
            raise ValueError("line_index_base must be 0")
        if self.line_end_inclusive:
            raise ValueError("line_end_inclusive must be false")
        if not self.sections:
            raise ValueError("sections must not be empty")
        return self
