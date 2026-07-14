"""Versioned result artifact contract for Worker integrations."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ArtifactKind(StrEnum):
    """Stable product-level artifact kinds."""

    LRC = "LRC"
    SWLRC = "SWLRC"
    ALIGNMENT_JSON = "ALIGNMENT_JSON"
    REPORT_JSON = "REPORT_JSON"
    VOCALS = "VOCALS"
    ACCOMPANIMENT = "ACCOMPANIMENT"


class ResultArtifact(BaseModel):
    """One verified file exposed to an external Worker client."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    kind: ArtifactKind
    relative_path: str = Field(alias="relativePath", min_length=1)
    media_type: str = Field(alias="mediaType", min_length=1)
    exportable: bool = True
    temporary: bool = False

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or Path(value).is_absolute():
            raise ValueError("relativePath must be relative to the job directory")
        if ".." in path.parts:
            raise ValueError("relativePath must not escape the job directory")
        if not path.parts or path == PurePosixPath("."):
            raise ValueError("relativePath must identify a file")
        return path.as_posix()


class ResultArtifacts(BaseModel):
    """Versioned collection embedded in a successful Worker result."""

    model_config = ConfigDict(extra="forbid")

    artifacts_schema_version: Literal[1] = Field(default=1, alias="artifactsSchemaVersion")
    artifacts: list[ResultArtifact]
