"""Typer CLI entrypoint."""

from __future__ import annotations

from typing import Annotated

import typer

from xingyu_lyrics_aligner.alignment.models import alignment_model_status, pull_alignment_model
from xingyu_lyrics_aligner.commands.align import align_command
from xingyu_lyrics_aligner.device import DeviceStrategy
from xingyu_lyrics_aligner.doctor import run_doctor
from xingyu_lyrics_aligner.i18n import configure_locale, normalize_locale
from xingyu_lyrics_aligner.i18n import translate as _
from xingyu_lyrics_aligner.model_registry import known_model_slots
from xingyu_lyrics_aligner.user_config import UserConfig, load_user_config, save_user_config

app = typer.Typer(help=_("app.help"), no_args_is_help=True)
models_app = typer.Typer(
    help=_("command.models.help"),
    invoke_without_command=True,
    no_args_is_help=False,
)
config_app = typer.Typer(help=_("command.config.help"), no_args_is_help=True)
app.add_typer(models_app, name="models")
app.add_typer(config_app, name="config")

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


@config_app.command("show", help=_("command.config.show.help"))
def config_show() -> None:
    """Show saved user preferences."""
    config = load_user_config()
    typer.echo(_("config.title"))
    typer.echo(f"{_('label.language')}: {config.locale or _('config.locale.not_set')}")


@config_app.command("set-locale", help=_("command.config.set_locale.help"))
def config_set_locale(
    locale: Annotated[
        str,
        typer.Argument(help=_("option.locale.help")),
    ],
) -> None:
    """Persist the default CLI locale."""
    normalized = normalize_locale(locale)
    if normalized != locale:
        typer.echo(_("error.unsupported_locale", locale=locale), err=True)
        raise typer.Exit(code=2)
    try:
        path = save_user_config(UserConfig(locale=normalized))
    except OSError as exc:
        typer.echo(_("error.config_write_failed", error=exc), err=True)
        raise typer.Exit(code=2) from exc
    configure_locale(normalized)
    typer.echo(_("config.locale.saved", locale=normalized, path=path))


@models_app.callback()
def models(ctx: typer.Context) -> None:
    """Show local model status when no model subcommand is selected."""
    if ctx.invoked_subcommand is None:
        models_status()


@models_app.command("list", help=_("command.models.list.help"))
def models_list() -> None:
    """List known model slots."""
    typer.echo(_("models.list.title"))
    for model in known_model_slots():
        display_name = _model_display_name(model.model_id, model.name)
        typer.echo(f"- {model.model_id}: {display_name} ({_('models.slot.status.placeholder')})")


@models_app.command("status", help=_("command.models.status.help"))
def models_status(
    language: Annotated[
        str,
        typer.Option("--language", help=_("option.language.help")),
    ] = "zh",
) -> None:
    """Show local model status."""
    typer.echo(_("models.status.title"))
    try:
        status = alignment_model_status(language)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    state = _("doctor.available") if status.available else _("doctor.not_available")
    typer.echo(f"- forced-aligner: {state}")
    typer.echo(f"  language: {status.language}")
    typer.echo(f"  model: {status.model_name}")
    typer.echo(f"  detail: {status.detail}")
    typer.echo("- vocal-separator: not required for v0.1.1")
    typer.echo(_("models.none_installed"))


@models_app.command("pull", help=_("command.models.pull.help"))
def models_pull(
    language: Annotated[
        str,
        typer.Option("--language", help=_("option.language.help")),
    ] = "zh",
    device: Annotated[
        DeviceStrategy,
        typer.Option("--device", help=_("option.device.help")),
    ] = DeviceStrategy.AUTO,
) -> None:
    """Explicitly download/preheat the local alignment model."""
    try:
        status = alignment_model_status(language)
        typer.echo(_("models.pull.notice"))
        typer.echo(f"language: {language}")
        typer.echo(f"model: {status.model_name}")
        typer.echo(f"source: {status.model_name}")
        typer.echo(_("models.pull.size_notice"))
        result = pull_alignment_model(language=language, device=device)
    except (RuntimeError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc

    typer.echo(_("models.pull.completed"))
    typer.echo(f"model: {result.model_name}")
    typer.echo(f"actual_alignment_device: {result.actual_device}")
    for warning in result.warnings:
        typer.echo(f"warning: {warning}")


app.command(name="align", help=_("command.align.help"))(align_command)


if __name__ == "__main__":
    app()
