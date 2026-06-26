"""Typer CLI entrypoint."""

from __future__ import annotations

import subprocess
import sys
from argparse import Namespace
from pathlib import Path
from typing import Annotated

import typer

from xingyu_lyrics_aligner import __version__
from xingyu_lyrics_aligner.alignment.models import alignment_model_status, pull_alignment_model
from xingyu_lyrics_aligner.candidate_lyrics.script_normalization import (
    ScriptNormalizationError,
    normalize_transcript_script,
)
from xingyu_lyrics_aligner.candidate_lyrics.transcription import (
    CandidateLyricsError,
    extract_candidate_lyrics,
)
from xingyu_lyrics_aligner.commands.align import align_command
from xingyu_lyrics_aligner.device import DeviceStrategy
from xingyu_lyrics_aligner.doctor import run_doctor
from xingyu_lyrics_aligner.i18n import configure_locale, normalize_locale
from xingyu_lyrics_aligner.i18n import translate as _
from xingyu_lyrics_aligner.model_registry import known_model_slots
from xingyu_lyrics_aligner.user_config import UserConfig, load_user_config, save_user_config

app = typer.Typer(help=_("app.help"), no_args_is_help=True, invoke_without_command=True)
models_app = typer.Typer(
    help=_("command.models.help"),
    invoke_without_command=True,
    no_args_is_help=False,
)
config_app = typer.Typer(help=_("command.config.help"), no_args_is_help=True)
candidate_app = typer.Typer(help=_("command.candidate.help"), no_args_is_help=True)
app.add_typer(models_app, name="models")
app.add_typer(config_app, name="config")
app.add_typer(candidate_app, name="candidate")

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
    version_requested: Annotated[
        bool,
        typer.Option("--version", help=_("command.version.help"), is_eager=True),
    ] = False,
) -> None:
    """Configure process-wide CLI locale."""
    configure_locale(locale)
    if version_requested:
        typer.echo(f"xingyu-lyrics-aligner {__version__}")
        raise typer.Exit()


@app.command("version", help=_("command.version.help"))
def version() -> None:
    """Show package version."""

    typer.echo(f"xingyu-lyrics-aligner {__version__}")


def _upgrade_command(include_candidate_lyrics: bool) -> list[str]:
    package = (
        "xingyu-lyrics-aligner[candidate-lyrics]"
        if include_candidate_lyrics
        else "xingyu-lyrics-aligner"
    )
    return [sys.executable, "-m", "pip", "install", "--upgrade", package]


@app.command("update", help=_("command.update.help"))
@app.command("upgrade", help=_("command.update.help"))
def update(
    run: Annotated[
        bool,
        typer.Option("--run", help=_("option.update_run.help")),
    ] = False,
    candidate_lyrics: Annotated[
        bool,
        typer.Option("--candidate-lyrics", help=_("option.update_candidate_lyrics.help")),
    ] = False,
) -> None:
    """Print or run the recommended package upgrade command."""

    command = _upgrade_command(candidate_lyrics)
    typer.echo(_("update.current_version", version=__version__))
    typer.echo(_("update.command", command=" ".join(command)))
    if not run:
        typer.echo(_("update.dry_run_notice"))
        return
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as exc:
        typer.echo(_("update.failed", code=exc.returncode), err=True)
        raise typer.Exit(code=exc.returncode) from exc
    typer.echo(_("update.completed"))


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


@candidate_app.command("extract", help=_("command.candidate.extract.help"))
def candidate_extract(
    audio: Annotated[
        Path,
        typer.Option("--audio", help=_("option.audio.help")),
    ],
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help=_("option.candidate_output_dir.help")),
    ],
    language: Annotated[
        str | None,
        typer.Option("--language", help=_("option.language.help")),
    ] = None,
    model: Annotated[
        str,
        typer.Option("--model", help=_("option.candidate_model.help")),
    ] = "medium",
    device: Annotated[
        DeviceStrategy,
        typer.Option("--device", help=_("option.device.help")),
    ] = DeviceStrategy.AUTO,
    skip_separation: Annotated[
        bool,
        typer.Option("--skip-separation", help=_("option.candidate_skip_separation.help")),
    ] = False,
    no_vad: Annotated[
        bool,
        typer.Option("--no-vad", help=_("option.candidate_no_vad.help")),
    ] = False,
    condition_on_previous_text: Annotated[
        bool,
        typer.Option(
            "--condition-on-previous-text",
            help=_("option.candidate_condition_on_previous_text.help"),
        ),
    ] = False,
    keep_suspected_metadata: Annotated[
        bool,
        typer.Option(
            "--keep-suspected-metadata",
            help=_("option.candidate_keep_suspected_metadata.help"),
        ),
    ] = False,
    keep_intermediates: Annotated[
        bool,
        typer.Option("--keep-intermediates", help=_("option.candidate_keep_intermediates.help")),
    ] = False,
) -> None:
    """Extract ASR candidate lyrics from local audio."""

    args = Namespace(
        audio=audio,
        output_dir=output_dir,
        language=language,
        model=model,
        device=device.value,
        skip_separation=skip_separation,
        no_vad=no_vad,
        condition_on_previous_text=condition_on_previous_text,
        keep_suspected_metadata=keep_suspected_metadata,
        keep_intermediates=keep_intermediates,
    )
    try:
        report = extract_candidate_lyrics(args)
    except CandidateLyricsError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(_("candidate.extract.completed", path=report["outputs"]["transcript_cleaned"]))
    typer.echo(_("candidate.not_trusted"))


@candidate_app.command("normalize", help=_("command.candidate.normalize.help"))
def candidate_normalize(
    input_path: Annotated[
        Path,
        typer.Option("--input", help=_("option.candidate_normalize_input.help")),
    ],
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help=_("option.candidate_output_dir.help")),
    ] = None,
    target: Annotated[
        str,
        typer.Option("--to", help=_("option.candidate_normalize_target.help")),
    ] = "zh-Hans",
    output_name: Annotated[
        str | None,
        typer.Option("--output-name", help=_("option.candidate_normalize_output_name.help")),
    ] = None,
) -> None:
    """Create a script-normalized copy of candidate lyrics."""

    if target not in {"zh-Hans", "zh-Hant"}:
        typer.echo(_("candidate.normalize.invalid_target", target=target), err=True)
        raise typer.Exit(code=2)
    try:
        report = normalize_transcript_script(
            input_path,
            output_dir=output_dir,
            target=target,
            output_name=output_name,
        )
    except ScriptNormalizationError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(_("candidate.normalize.completed", path=report["output"]))
    typer.echo(_("candidate.normalize.source_preserved"))


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
