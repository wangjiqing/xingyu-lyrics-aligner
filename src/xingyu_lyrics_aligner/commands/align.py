"""Typer command for trusted-lyrics CTC alignment."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from xingyu_lyrics_aligner.alignment.pipeline import AlignRunResult
from xingyu_lyrics_aligner.api import AlignLyricsOptions, align_lyrics
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
    json_result: Annotated[
        bool,
        typer.Option("--json-result", help=_("option.json_result.help")),
    ] = False,
) -> None:
    """Align trusted lyric lines directly with WhisperX CTC."""
    try:
        result = align_lyrics(
            audio_path=audio,
            lyrics_path=lyrics,
            output_dir=output_dir,
            language=language,
            device=device,
            options=AlignLyricsOptions(
                section_manifest=section_manifest,
                lrc_offset_ms=lrc_offset_ms,
                overwrite=overwrite,
                debug_output=debug_output,
            ),
        )
    except (FileNotFoundError, FileExistsError, RuntimeError, ValueError) as exc:
        if json_result:
            typer.echo(
                json.dumps(
                    {
                        "success": False,
                        "error": {
                            "code": _error_code(exc),
                            "message": str(exc),
                        },
                    },
                    ensure_ascii=False,
                )
            )
            typer.echo(str(exc), err=True)
        else:
            typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc

    if json_result:
        typer.echo(json.dumps(_json_result_payload(result), ensure_ascii=False))
        return

    typer.echo(_("align.completed", output_dir=result.output_dir))
    for key, path in result.files.items():
        typer.echo(f"{key}: {path}")


def _json_result_payload(result: AlignRunResult) -> dict[str, object]:
    line_count = result.report.line_count
    aligned_line_count = result.report.aligned_or_partial_lines
    return {
        "success": True,
        "output_dir": str(result.output_dir),
        "files": {key: str(path) for key, path in result.files.items()},
        "summary": {
            "line_count": line_count,
            "aligned_line_count": aligned_line_count,
            "token_count": result.swlrc.token_count,
            "coverage": aligned_line_count / line_count if line_count else 0.0,
            "estimated_token_count": result.swlrc.estimated_token_count,
            "skipped_line_count": result.swlrc.skipped_line_count,
        },
        "warnings": result.report.warnings,
    }


def _error_code(exc: Exception) -> str:
    if isinstance(exc, FileExistsError):
        return "OUTPUT_EXISTS"
    if isinstance(exc, FileNotFoundError):
        return "INPUT_NOT_FOUND"
    if isinstance(exc, ValueError):
        return "INVALID_REQUEST"
    return "ALIGNMENT_FAILED"
