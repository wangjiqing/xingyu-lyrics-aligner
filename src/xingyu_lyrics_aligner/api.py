"""Stable public Python API for local lyrics alignment."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from xingyu_lyrics_aligner.alignment.pipeline import AlignRequest, AlignRunResult, run_alignment
from xingyu_lyrics_aligner.device import DeviceStrategy


@dataclass(frozen=True)
class AlignLyricsOptions:
    """Optional knobs for :func:`align_lyrics`."""

    section_manifest: Path | None = None
    lrc_offset_ms: int = 0
    overwrite: bool = False
    debug_output: bool = False


def align_lyrics(
    *,
    audio_path: str | Path,
    lyrics_path: str | Path,
    output_dir: str | Path,
    language: str = "zh",
    device: DeviceStrategy | str = DeviceStrategy.AUTO,
    options: AlignLyricsOptions | None = None,
) -> AlignRunResult:
    """Align trusted lyrics to audio and return structured output metadata."""

    resolved_options = options or AlignLyricsOptions()
    return run_alignment(
        AlignRequest(
            audio=Path(audio_path),
            lyrics=Path(lyrics_path),
            output_dir=Path(output_dir),
            language=language,
            device=DeviceStrategy(device),
            section_manifest=resolved_options.section_manifest,
            lrc_offset_ms=resolved_options.lrc_offset_ms,
            overwrite=resolved_options.overwrite,
            debug_output=resolved_options.debug_output,
        )
    )
