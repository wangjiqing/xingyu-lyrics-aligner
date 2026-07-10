"""Trusted-lyrics CTC alignment orchestration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from xingyu_lyrics_aligner.alignment.audio import load_audio
from xingyu_lyrics_aligner.alignment.backmap import CharacterTiming, backfill_lines
from xingyu_lyrics_aligner.alignment.ctc import CtcSegment, WhisperXCtcAligner
from xingyu_lyrics_aligner.alignment.exporters import (
    ensure_output_paths,
    render_swlrc_text,
    write_outputs,
)
from xingyu_lyrics_aligner.alignment.quality import (
    count_non_monotonic,
    input_character_count,
    status_counts,
    timed_character_count,
)
from xingyu_lyrics_aligner.alignment.sections import (
    global_section,
    load_section_manifest,
    validate_sections,
)
from xingyu_lyrics_aligner.alignment.swlrc_exporter import SwlrcExportStats, build_swlrc_document
from xingyu_lyrics_aligner.alignment.text import (
    LineSpec,
    TrustedLyricLine,
    build_line_specs,
    parse_trusted_lyrics,
)
from xingyu_lyrics_aligner.device import DeviceStrategy
from xingyu_lyrics_aligner.schemas.alignment import (
    AlignmentDocument,
    AlignmentLine,
    AlignmentSource,
    AlignmentStatus,
    PresentationHint,
    PreservedHeaderLine,
    ReportDocument,
)
from xingyu_lyrics_aligner.schemas.manifest import Section


@dataclass(frozen=True)
class AlignRequest:
    """User-facing align command request."""

    audio: Path
    lyrics: Path
    output_dir: Path
    language: str
    device: DeviceStrategy
    section_manifest: Path | None = None
    lrc_offset_ms: int = 0
    overwrite: bool = False
    debug_output: bool = False


@dataclass(frozen=True)
class AlignRunResult:
    """Files and documents produced by one align run."""

    alignment: AlignmentDocument
    report: ReportDocument
    output_dir: Path
    swlrc: SwlrcExportStats

    @property
    def files(self) -> dict[str, Path]:
        """Stable file contract for local CLI integrations."""
        return {
            "alignment_json": self.output_dir / "alignment.json",
            "lrc": self.output_dir / "lyrics.lrc",
            "swlrc": self.output_dir / "lyrics.swlrc",
            "report": self.output_dir / "report.json",
        }


def run_alignment(request: AlignRequest) -> AlignRunResult:
    """Run trusted-lyrics CTC alignment and write official outputs."""
    validate_request(request)
    ensure_output_paths(request.output_dir, overwrite=request.overwrite)

    trusted_lyrics = parse_trusted_lyrics(request.lyrics)
    singing_source_lines = trusted_lyrics.singing_lines
    if not trusted_lyrics.lines:
        raise ValueError("Lyrics file contains no non-empty lines.")
    if not singing_source_lines:
        raise ValueError("Lyrics contain no singing lines after header classification.")
    line_specs = build_line_specs([line.text for line in singing_source_lines])
    if input_character_count(line_specs) == 0:
        raise ValueError("Lyrics contain no alignable characters after normalization.")

    loaded_audio = load_audio(request.audio)
    sections, section_warnings = resolve_sections(
        request.section_manifest,
        line_count=len(line_specs),
        audio_duration=loaded_audio.duration_seconds,
    )

    aligner = WhisperXCtcAligner(language=request.language, requested_device=request.device)
    all_lines: list[AlignmentLine] = []
    all_chars: list[CharacterTiming] = []
    warnings = list(aligner.device.warnings) + section_warnings + trusted_lyrics.warnings

    for section in sections:
        section_line_specs = line_specs[section.line_start : section.line_end]
        segment_text = "".join(line.alignment_text for line in section_line_specs)
        chars = aligner.align(
            CtcSegment(
                text=segment_text,
                start=section.audio_start,
                end=section.audio_end,
                id=section.id,
                kind=section.kind,
            ),
            loaded_audio.samples,
        )
        section_lines, section_backmap_warnings = backfill_lines(
            section_line_specs,
            chars,
            section_id=None if section.id == "global" else section.id,
            section_kind=None if section.id == "global" else section.kind,
        )
        all_lines.extend(section_lines)
        all_chars.extend(chars)
        warnings.extend(section_backmap_warnings)

    all_lines.sort(key=lambda line: line.index)
    all_lines = [
        line.model_copy(
            update={"source_line_index": singing_source_lines[line.index].source_line_index}
        )
        for line in all_lines
    ]
    first_start = next((line.start for line in all_lines if line.start is not None), None)
    first_start_ms = round(first_start * 1000) if first_start is not None else None
    preserved_headers, presentation_hints = build_header_protocol(
        trusted_lyrics.preserved_header_lines,
        first_start_ms=first_start_ms,
    )
    source = AlignmentSource(
        audio_name=request.audio.name,
        alignment_model=aligner.align_model_name,
        requested_device=aligner.device.requested,
        actual_alignment_device=aligner.device.actual,
    )
    alignment = AlignmentDocument(
        language=request.language,
        source=source,
        lines=all_lines,
        warnings=dedupe_warnings(warnings),
        firstAlignedLyricStartMs=first_start_ms,
        preservedHeaderLines=preserved_headers,
        presentationHints=presentation_hints,
    )
    swlrc_result = build_swlrc_document(alignment)
    report = build_report(
        language=request.language,
        source=source,
        line_specs=line_specs,
        char_entries=all_chars,
        lines=all_lines,
        warnings=dedupe_warnings(alignment.warnings + swlrc_result.stats.warnings),
        estimated_token_count=swlrc_result.stats.estimated_token_count,
        skipped_line_count=swlrc_result.stats.skipped_line_count,
        swlrc_warnings=swlrc_result.stats.warnings,
        first_aligned_lyric_start_ms=first_start_ms,
        preserved_header_lines=preserved_headers,
        presentation_hints=presentation_hints,
    )
    write_outputs(
        request.output_dir,
        alignment,
        report,
        lrc_offset_ms=request.lrc_offset_ms,
        swlrc_text=render_swlrc_text(swlrc_result.document),
    )
    if request.debug_output:
        write_debug_summary(
            request.output_dir / "debug.summary.json",
            sections=sections,
            character_entries=all_chars,
        )
    return AlignRunResult(
        alignment=alignment,
        report=report,
        output_dir=request.output_dir,
        swlrc=swlrc_result.stats,
    )


def validate_request(request: AlignRequest) -> None:
    """Validate filesystem inputs before expensive work."""
    if not request.audio.exists():
        raise FileNotFoundError(f"Audio file does not exist: {request.audio}")
    if not request.lyrics.exists():
        raise FileNotFoundError(f"Lyrics file does not exist: {request.lyrics}")
    if not request.audio.is_file():
        raise ValueError(f"Audio path is not a file: {request.audio}")
    if not request.lyrics.is_file():
        raise ValueError(f"Lyrics path is not a file: {request.lyrics}")
    if request.section_manifest is not None and not request.section_manifest.exists():
        raise FileNotFoundError(f"Section manifest does not exist: {request.section_manifest}")
    if request.output_dir.exists() and not request.output_dir.is_dir():
        raise ValueError(
            f"Output directory path exists but is not a directory: {request.output_dir}"
        )


def resolve_sections(
    manifest_path: Path | None,
    *,
    line_count: int,
    audio_duration: float,
) -> tuple[list[Section], list[str]]:
    """Resolve either global or manual section mode."""
    if manifest_path is None:
        return [global_section(audio_duration, line_count)], []
    manifest = load_section_manifest(manifest_path)
    warnings = validate_sections(
        manifest.sections,
        line_count=line_count,
        audio_duration=audio_duration,
    )
    for section in manifest.sections:
        if section.kind == "foreground_voice_switch":
            warnings.append("foreground_voice_switch")
    return manifest.sections, dedupe_warnings(warnings)


def build_report(
    *,
    language: str,
    source: AlignmentSource,
    line_specs: list[LineSpec],
    char_entries: list[CharacterTiming],
    lines: list[AlignmentLine],
    warnings: list[str],
    estimated_token_count: int = 0,
    skipped_line_count: int = 0,
    swlrc_warnings: list[str] | None = None,
    first_aligned_lyric_start_ms: int | None = None,
    preserved_header_lines: list[PreservedHeaderLine] | None = None,
    presentation_hints: list[PresentationHint] | None = None,
) -> ReportDocument:
    """Build compact statistics without copying full lyric text."""
    input_chars = input_character_count(line_specs)
    timed_chars = timed_character_count(char_entries)
    aligned_or_partial = sum(
        1 for line in lines if line.status in {AlignmentStatus.ALIGNED, AlignmentStatus.PARTIAL}
    )
    return ReportDocument(
        language=language,
        source=source,
        line_count=len(lines),
        aligned_or_partial_lines=aligned_or_partial,
        input_alignment_characters=input_chars,
        timed_character_entries=timed_chars,
        missing_character_timestamps=max(0, input_chars - timed_chars),
        character_count_matches=input_chars == len(char_entries),
        non_monotonic_line_count=count_non_monotonic(lines),
        status_counts=status_counts(lines),
        estimated_token_count=estimated_token_count,
        skipped_line_count=skipped_line_count,
        swlrc_warnings=swlrc_warnings or [],
        warnings=warnings,
        firstAlignedLyricStartMs=first_aligned_lyric_start_ms,
        preservedHeaderLines=preserved_header_lines or [],
        presentationHints=presentation_hints or [],
    )


def build_header_protocol(
    source_lines: list[TrustedLyricLine], *, first_start_ms: int | None
) -> tuple[list[PreservedHeaderLine], list[PresentationHint]]:
    """Build display-only intro hints; never place them on the lyric timeline."""
    hints: list[PresentationHint] = []
    if first_start_ms is not None and first_start_ms > 0 and source_lines:
        for index in range(len(source_lines)):
            start = first_start_ms * index // len(source_lines)
            end = first_start_ms * (index + 1) // len(source_lines)
            hints.append(PresentationHint(suggestedStartMs=start, suggestedEndMs=end))
    preserved = []
    for index, line in enumerate(source_lines):
        reason = "lrc_metadata" if line.kind.value == "LRC_METADATA" else "non_singing_header"
        preserved.append(
            PreservedHeaderLine(
                text=line.text,
                kind="LRC_METADATA" if reason == "lrc_metadata" else (line.header_kind or "HEADER"),
                lineClassification=line.kind.value,
                sourceLineIndex=line.source_line_index,
                nonAlignmentReason=reason,
                presentationHints=hints[index] if hints else None,
            )
        )
    return preserved, hints


def dedupe_warnings(warnings: list[str]) -> list[str]:
    """Keep warning order stable while removing duplicates."""
    seen: set[str] = set()
    out: list[str] = []
    for warning in warnings:
        if warning not in seen:
            seen.add(warning)
            out.append(warning)
    return out


def write_debug_summary(
    path: Path,
    *,
    sections: list[Section],
    character_entries: list[CharacterTiming],
) -> None:
    """Write a local debug summary without raw WhisperX output or lyric text."""
    payload = {
        "section_count": len(sections),
        "sections": [
            {
                "id": section.id,
                "kind": section.kind,
                "audio_start": section.audio_start,
                "audio_end": section.audio_end,
                "line_start": section.line_start,
                "line_end": section.line_end,
            }
            for section in sections
        ],
        "character_entries": len(character_entries),
        "timed_character_entries": timed_character_count(character_entries),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
