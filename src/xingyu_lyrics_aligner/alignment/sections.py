"""Manual section manifest loading and validation."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from xingyu_lyrics_aligner.schemas.manifest import Section, SectionManifest


def load_section_manifest(path: Path) -> SectionManifest:
    """Load a v1 section manifest from JSON."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return SectionManifest.model_validate(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid section manifest JSON: {exc}") from exc
    except ValidationError as exc:
        raise ValueError(f"Invalid section manifest: {exc}") from exc


def validate_sections(
    sections: list[Section],
    *,
    line_count: int,
    audio_duration: float,
) -> list[str]:
    """Validate section coverage and return non-fatal review warnings."""
    warnings: list[str] = []
    previous_line_end = 0
    previous_audio_end = 0.0
    seen_ids: set[str] = set()

    for section in sections:
        if section.id in seen_ids:
            raise ValueError(f"Duplicate section id: {section.id}")
        seen_ids.add(section.id)

        if section.line_start != previous_line_end:
            raise ValueError("Section lyric ranges must cover every line exactly once")
        if section.line_end > line_count:
            raise ValueError(f"Section {section.id} line range exceeds lyric line count")
        if section.audio_end > audio_duration + 0.25:
            raise ValueError(f"Section {section.id} exceeds audio duration")
        if section.audio_start + 0.25 < previous_audio_end:
            raise ValueError(f"Section {section.id} overlaps the previous audio range")
        if section.audio_start < previous_audio_end or section.audio_start > previous_audio_end:
            warnings.append("section_boundary_review")

        previous_line_end = section.line_end
        previous_audio_end = section.audio_end

    if previous_line_end != line_count:
        raise ValueError("Section lyric ranges must cover every line exactly once")
    return warnings


def global_section(audio_duration: float, line_count: int) -> Section:
    """Represent the default whole-song alignment as one synthetic section."""
    return Section(
        id="global",
        audio_start=0.0,
        audio_end=audio_duration,
        line_start=0,
        line_end=line_count,
        kind="singing",
    )
