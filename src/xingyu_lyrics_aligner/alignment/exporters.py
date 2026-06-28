"""Export alignment JSON, LRC, and compact reports."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from xingyu_lyrics_aligner.formats.swlrc import SwlrcDocument, serialize_swlrc
from xingyu_lyrics_aligner.schemas.alignment import AlignmentDocument, AlignmentLine, ReportDocument

OUTPUT_FILES = ("alignment.json", "lyrics.lrc", "lyrics.swlrc", "report.json")


def format_lrc_time(seconds: float) -> str:
    """Format seconds as standard LRC mm:ss.xx."""
    bounded = max(0.0, seconds)
    minutes = int(bounded // 60)
    rest = bounded - minutes * 60
    return f"{minutes:02d}:{rest:05.2f}"


def render_lrc(lines: list[AlignmentLine], *, offset_ms: int = 0) -> str:
    """Render line-level LRC. Offset affects export only."""
    offset_seconds = offset_ms / 1000.0
    rows = [
        f"[{format_lrc_time(float(line.start) + offset_seconds)}]{line.text}"
        for line in lines
        if line.start is not None
    ]
    return "\n".join(rows) + ("\n" if rows else "")


def write_json(path: Path, model: BaseModel) -> None:
    """Write a Pydantic model as UTF-8 JSON."""
    path.write_text(
        json.dumps(model.model_dump(mode="json", exclude_none=True), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )


def ensure_output_paths(output_dir: Path, *, overwrite: bool) -> None:
    """Fail before inference if output files already exist."""
    existing = [output_dir / name for name in OUTPUT_FILES if (output_dir / name).exists()]
    if existing and not overwrite:
        names = ", ".join(path.name for path in existing)
        raise FileExistsError(f"Output file already exists: {names}. Use --overwrite to replace.")


def write_outputs(
    output_dir: Path,
    alignment: AlignmentDocument,
    report: ReportDocument,
    *,
    lrc_offset_ms: int,
    swlrc_text: str,
) -> None:
    """Write the official alignment output files."""
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "alignment.json", alignment)
    (output_dir / "lyrics.lrc").write_text(
        render_lrc(alignment.lines, offset_ms=lrc_offset_ms),
        encoding="utf-8",
    )
    (output_dir / "lyrics.swlrc").write_text(swlrc_text, encoding="utf-8")
    write_json(output_dir / "report.json", report)


def render_swlrc_text(swlrc_document: SwlrcDocument) -> str:
    """Serialize SWLRC through the format module's validator-backed serializer."""
    return serialize_swlrc(swlrc_document)
