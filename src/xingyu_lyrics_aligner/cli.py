"""Typer CLI entrypoint."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from xingyu_lyrics_aligner.device import DeviceStrategy
from xingyu_lyrics_aligner.doctor import run_doctor
from xingyu_lyrics_aligner.i18n import configure_locale
from xingyu_lyrics_aligner.i18n import translate as _
from xingyu_lyrics_aligner.model_registry import known_model_slots

app = typer.Typer(help=_("app.help"), no_args_is_help=True)
models_app = typer.Typer(help=_("command.models.help"), no_args_is_help=True)
app.add_typer(models_app, name="models")

MODEL_DISPLAY_KEYS = {
    "forced-aligner": "models.slot.aligner",
    "vocal-separator": "models.slot.separator",
}


def _localized_bool(value: bool) -> str:
    return _("label.yes") if value else _("label.no")


def _model_display_name(model_id: str, fallback: str) -> str:
    key = MODEL_DISPLAY_KEYS.get(model_id)
    return _(key) if key else fallback


@app.callback()
def main(
    locale: Annotated[
        str | None,
        typer.Option("--locale", help=_("option.locale.help")),
    ] = None,
) -> None:
    """Configure process-wide CLI locale."""
    configure_locale(locale)


@app.command(help=_("command.doctor.help"))
def doctor() -> None:
    """Check local runtime prerequisites."""
    report = run_doctor()
    caps = report.capabilities
    typer.echo(_("doctor.title"))
    typer.echo(f"{_('doctor.python')}: {caps.python_version}")
    typer.echo(f"{_('doctor.os')}: {caps.os_name} {caps.os_release}")
    typer.echo(f"{_('doctor.machine')}: {caps.machine}")
    typer.echo(f"{_('doctor.apple_silicon')}: {_localized_bool(caps.is_apple_silicon)}")
    typer.echo(
        f"{_('doctor.cuda')}: "
        f"{_('doctor.available') if caps.cuda_available else _('doctor.not_available')}"
    )
    typer.echo(
        f"{_('doctor.mps')}: "
        f"{_('doctor.available') if caps.mps_available else _('doctor.not_available')}"
    )
    ffmpeg_status = caps.ffmpeg_path if caps.ffmpeg_path else _("doctor.not_detected")
    typer.echo(f"{_('doctor.ffmpeg')}: {ffmpeg_status}")
    typer.echo(_("doctor.summary.ready"))


@models_app.command("list", help=_("command.models.list.help"))
def models_list() -> None:
    """List known model slots."""
    typer.echo(_("models.list.title"))
    for model in known_model_slots():
        display_name = _model_display_name(model.model_id, model.name)
        typer.echo(f"- {model.model_id}: {display_name} ({_('models.slot.status.placeholder')})")


@models_app.command("status", help=_("command.models.status.help"))
def models_status() -> None:
    """Show local model status."""
    typer.echo(_("models.status.title"))
    typer.echo(_("models.none_installed"))
    for model in known_model_slots():
        typer.echo(f"- {model.model_id}: {_('doctor.not_available')}")


@app.command(help=_("command.align.help"))
def align(
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
    device: Annotated[
        DeviceStrategy,
        typer.Option("--device", help=_("option.device.help")),
    ] = DeviceStrategy.AUTO,
    language: Annotated[
        str | None,
        typer.Option("--language", help=_("option.language.help")),
    ] = None,
) -> None:
    """Validate an alignment request without running inference."""
    missing_paths = [path for path in (audio, lyrics) if not path.exists()]
    if missing_paths:
        for path in missing_paths:
            typer.echo(_("error.file_missing", path=path), err=True)
        raise typer.Exit(code=2)

    typer.echo(_("align.request"))
    typer.echo(f"{_('option.audio.help')} {audio}")
    typer.echo(f"{_('option.lyrics.help')} {lyrics}")
    typer.echo(f"{_('label.device')}: {device.value}")
    typer.echo(f"{_('label.language')}: {language or 'auto'}")
    typer.echo(_("align.not_implemented"))
