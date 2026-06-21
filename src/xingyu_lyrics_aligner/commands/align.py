"""Typer command for trusted-lyrics CTC alignment."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from xingyu_lyrics_aligner.alignment.pipeline import AlignRequest, run_alignment
from xingyu_lyrics_aligner.device import DeviceStrategy
from xingyu_lyrics_aligner.i18n import translate as _


def align_command(
    audio: Annotated[
        Path,
        typer.Option(
            "--audio",
            "-a",
            exists=False,
            file_okay=True,
            dir_okay=False,
            help=_("option.audio.help"),
        ),
    ],
    lyrics: Annotated[
        Path,
        typer.Option(
            "--lyrics",
            "-l",
            exists=False,
            file_okay=True,
            dir_okay=False,
            help=_("option.lyrics.help"),
        ),
    ],
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            "-o",
            file_okay=False,
            dir_okay=True,
            help=_("option.output_dir.help"),
        ),
    ],
    language: Annotated[
        str,
        typer.Option("--language", help=_("option.language.help")),
    ] = "zh",
    device: Annotated[
        DeviceStrategy,
        typer.Option("--device", help=_("option.device.help")),
    ] = DeviceStrategy.AUTO,
    section_manifest: Annotated[
        Path | None,
        typer.Option("--section-manifest", help=_("option.section_manifest.help")),
    ] = None,
    lrc_offset_ms: Annotated[
        int,
        typer.Option("--lrc-offset-ms", help=_("option.lrc_offset_ms.help")),
    ] = 0,
    overwrite: Annotated[
        bool,
        typer.Option("--overwrite", help=_("option.overwrite.help")),
    ] = False,
    debug_output: Annotated[
        bool,
        typer.Option("--debug-output", help=_("option.debug_output.help")),
    ] = False,
) -> None:
    """Align trusted lyric lines directly with WhisperX CTC."""
    try:
        result = run_alignment(
            AlignRequest(
                audio=audio,
                lyrics=lyrics,
                output_dir=output_dir,
                language=language,
                device=device,
                section_manifest=section_manifest,
                lrc_offset_ms=lrc_offset_ms,
                overwrite=overwrite,
                debug_output=debug_output,
            )
        )
    except (FileNotFoundError, FileExistsError, RuntimeError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc

    typer.echo(_("align.completed", output_dir=result.output_dir))
    typer.echo(f"alignment.json: {result.output_dir / 'alignment.json'}")
    typer.echo(f"lyrics.lrc: {result.output_dir / 'lyrics.lrc'}")
    typer.echo(f"report.json: {result.output_dir / 'report.json'}")
